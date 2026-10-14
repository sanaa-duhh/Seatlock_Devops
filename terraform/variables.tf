variable "region" {
  description = "AWS region for every resource."
  type        = string
  default     = "ap-southeast-2"
}

variable "cluster_name" {
  description = "EKS cluster name; also used to name the VPC and IAM roles."
  type        = string
  default     = "seatlock-demo"
}

variable "cluster_version" {
  description = "EKS Kubernetes version. Pick one in standard support: aws eks describe-cluster-versions."
  type        = string
  default     = "1.37"
}

variable "vpc_cidr" {
  description = "VPC address range; subnets are carved from it."
  type        = string
  default     = "10.42.0.0/16"
}

variable "node_instance_types" {
  description = "Instance types for the managed node group."
  type        = list(string)
  default     = ["t3.medium"]
}

variable "node_desired_size" {
  description = <<-EOT
    Initial worker count. A t3.medium runs at most 17 Pods (VPC CNI IP limit), and the
    platform (monitoring, Argo CD, Loki, Ingress, add-ons) needs about 35 before the HPA
    adds any backend Pods, so three nodes leave room to scale.
  EOT
  type        = number
  default     = 3
}

variable "ingress_mode" {
  description = <<-EOT
    How traffic reaches the Traefik Ingress controller:
      "nlb"      - nodes in private subnets behind a NAT gateway; an AWS Network Load
                   Balancer fronts Traefik. The production-style layout.
      "hostport" - nodes in public subnets; Traefik listens on ingress_host_port (8080) of every node.
                   No NAT gateway or load balancer. For accounts where load balancer
                   creation is not yet enabled, and the cheaper option for short demos.
  EOT
  type        = string
  default     = "nlb"

  validation {
    condition     = contains(["nlb", "hostport"], var.ingress_mode)
    error_message = "ingress_mode must be \"nlb\" or \"hostport\"."
  }
}

variable "ingress_host_port" {
  description = <<-EOT
    hostport mode: node port Traefik listens on. Not 80, because the EKS Pod Identity
    agent declares hostPort 80 on every node and the scheduler treats that as taken.
  EOT
  type        = number
  default     = 8080
}

variable "ingress_allowed_cidrs" {
  description = "Who may reach the app on ingress_host_port in hostport mode."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "cluster_endpoint_public_access_cidrs" {
  description = <<-EOT
    CIDRs allowed to reach the public Kubernetes API. Every request still needs a valid
    IAM identity. Narrow it to your own IP (x.x.x.x/32) when you administer from one place;
    CI never calls the cluster, because Argo CD pulls deployments from Git.
  EOT
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

