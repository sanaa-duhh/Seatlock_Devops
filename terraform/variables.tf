variable "region" {
  description = "AWS region for every resource."
  type        = string
  default     = "ap-south-1"
}

variable "cluster_name" {
  description = "EKS cluster name; also used to name the VPC and IAM roles."
  type        = string
  default     = "seatlock-demo"
}

variable "cluster_version" {
  description = "EKS Kubernetes version. Pick one in standard support: aws eks describe-cluster-versions."
  type        = string
  default     = "1.35"
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
  description = "GitHub repository (owner/name) whose main-branch workflow may deploy to the cluster."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "Use the owner/name form, for example octocat/seatlock."
  }
}

variable "app_namespace" {
  description = "Kubernetes namespace the CI deploy role is limited to."
  type        = string
  default     = "seatlock"
}

variable "create_github_oidc_provider" {
  description = "Set false if this AWS account already has the GitHub Actions OIDC provider."
  type        = bool
  default     = true
}
