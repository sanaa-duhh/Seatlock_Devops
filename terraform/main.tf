data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs          = slice(data.aws_availability_zones.available.names, 0, 2)
  public_nodes = var.ingress_mode == "hostport"
}

# Network: two public subnets and two private subnets across two AZs.
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "6.7.3"

  name = var.cluster_name
  cidr = var.vpc_cidr
  azs  = local.azs

  public_subnets  = [for i in range(2) : cidrsubnet(var.vpc_cidr, 8, 101 + i)]
  private_subnets = [for i in range(2) : cidrsubnet(var.vpc_cidr, 8, 1 + i)]

  # Private nodes reach the internet through one shared NAT gateway (cheap; production
  # would use one per AZ). Public nodes have their own public IPs and need no NAT.
  enable_nat_gateway      = !local.public_nodes
  single_nat_gateway      = true
  map_public_ip_on_launch = local.public_nodes
  enable_dns_hostnames    = true

  # Tags that let Kubernetes place public and internal load balancers.
  public_subnet_tags  = { "kubernetes.io/role/elb" = "1" }
  private_subnet_tags = { "kubernetes.io/role/internal-elb" = "1" }
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "20.37.1"

  cluster_name    = var.cluster_name
  cluster_version = var.cluster_version
  vpc_id          = module.vpc.vpc_id
  # The control plane's network interfaces always live in the private subnets.
  control_plane_subnet_ids = module.vpc.private_subnets
  subnet_ids               = local.public_nodes ? module.vpc.public_subnets : module.vpc.private_subnets

  cluster_endpoint_public_access       = true
  cluster_endpoint_private_access      = true
  cluster_endpoint_public_access_cidrs = var.cluster_endpoint_public_access_cidrs

  # Whoever runs terraform apply becomes cluster admin through an EKS access entry.
  authentication_mode                      = "API"
  enable_cluster_creator_admin_permissions = true

  # Workload AWS permissions use EKS Pod Identity, which needs no IAM OIDC provider.
  enable_irsa = false

  cluster_addons = {
    coredns                = {}
    kube-proxy             = {}
    vpc-cni                = { before_compute = true }
    eks-pod-identity-agent = { before_compute = true }
    metrics-server         = {} # feeds CPU metrics to the HorizontalPodAutoscaler
  }

  eks_managed_node_groups = {
    default = {
      instance_types = var.node_instance_types
      min_size       = 1
      max_size       = 3
      desired_size   = var.node_desired_size
    }
  }

  # In hostport mode Traefik answers on port 80 of every node.
  node_security_group_additional_rules = local.public_nodes ? {
    ingress_http = {
      description = "HTTP to the Traefik Ingress controller"
      type        = "ingress"
      protocol    = "tcp"
      from_port   = 80
      to_port     = 80
      cidr_blocks = var.ingress_allowed_cidrs
    }
  } : {}

  # The GitHub Actions deploy identity may only manage resources inside the app namespace.
  access_entries = {
    github_deploy = {
      principal_arn = local.github_deploy_principal_arn
      policy_associations = {
        namespace_admin = {
          policy_arn = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
          access_scope = {
            type       = "namespace"
            namespaces = [var.app_namespace]
          }
        }
      }
    }
  }
}

# EBS CSI driver, so the PostgreSQL StatefulSet can claim encrypted gp3 volumes.
# Its controller gets AWS credentials through an EKS Pod Identity association.
data "aws_iam_policy_document" "ebs_csi_trust" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ebs_csi" {
  name               = "${var.cluster_name}-ebs-csi"
  assume_role_policy = data.aws_iam_policy_document.ebs_csi_trust.json
}

resource "aws_iam_role_policy_attachment" "ebs_csi" {
  role       = aws_iam_role.ebs_csi.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}

resource "aws_eks_pod_identity_association" "ebs_csi" {
  cluster_name    = module.eks.cluster_name
  namespace       = "kube-system"
  service_account = "ebs-csi-controller-sa"
  role_arn        = aws_iam_role.ebs_csi.arn
}

resource "aws_eks_addon" "ebs_csi" {
  cluster_name                = module.eks.cluster_name
  addon_name                  = "aws-ebs-csi-driver"
  resolve_conflicts_on_create = "OVERWRITE"

  # The association must exist before the controller Pods start.
  depends_on = [aws_eks_pod_identity_association.ebs_csi, aws_iam_role_policy_attachment.ebs_csi]
}
