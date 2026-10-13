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
  description = "Initial worker count. Two nodes leave room for the app, Ingress and monitoring."
  type        = number
  default     = 2
}

variable "ingress_mode" {
  description = <<-EOT
    How traffic reaches the Traefik Ingress controller:
      "nlb"      - nodes in private subnets behind a NAT gateway; an AWS Network Load
                   Balancer fronts Traefik. The production-style layout.
      "hostport" - nodes in public subnets; Traefik listens on port 80 of every node.
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

variable "ingress_allowed_cidrs" {
  description = "Who may reach the app on port 80 in hostport mode."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "cluster_endpoint_public_access_cidrs" {
  description = <<-EOT
    CIDRs allowed to reach the public Kubernetes API. Every request still needs a valid
    IAM identity. GitHub-hosted runners have no fixed IPs, so the CI deploy job needs
    0.0.0.0/0 unless you run a self-hosted runner.
  EOT
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "github_repository" {
  description = "GitHub repository (owner/name) whose workflow may deploy to the cluster."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "Use the owner/name form, for example octocat/seatlock."
  }
}

variable "github_deploy_auth" {
  description = <<-EOT
    How GitHub Actions authenticates to AWS:
      "oidc"       - short-lived role sessions through the GitHub OIDC provider (preferred).
      "access_key" - a dedicated IAM user whose key is stored as GitHub secrets. Only for
                     accounts whose policies forbid creating OIDC providers. The key is
                     destroyed together with the cluster.
  EOT
  type        = string
  default     = "oidc"

  validation {
    condition     = contains(["oidc", "access_key"], var.github_deploy_auth)
    error_message = "github_deploy_auth must be \"oidc\" or \"access_key\"."
  }
}

variable "create_github_oidc_provider" {
  description = "With oidc auth: set false if this AWS account already has the GitHub Actions OIDC provider."
  type        = bool
  default     = true
}

variable "app_namespace" {
  description = "Kubernetes namespace the CI deploy identity is limited to."
  type        = string
  default     = "seatlock"
}
