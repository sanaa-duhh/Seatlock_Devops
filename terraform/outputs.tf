output "region" {
  value = var.region
}

output "cluster_name" {
  value = module.eks.cluster_name
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "ingress_mode" {
  value = var.ingress_mode
}

output "vpc_id" {
  value = module.vpc.vpc_id
}

output "public_subnet_ids" {
  value = module.vpc.public_subnets
}

output "private_subnet_ids" {
  value = module.vpc.private_subnets
}

output "github_deploy_auth" {
  value = var.github_deploy_auth
}

output "github_deploy_role_arn" {
  description = "oidc auth: set as the AWS_DEPLOY_ROLE_ARN repository variable."
  value       = local.use_oidc ? aws_iam_role.github_deploy[0].arn : ""
}

output "github_deploy_access_key_id" {
  description = "access_key auth: set as the AWS_ACCESS_KEY_ID repository secret."
  value       = local.use_oidc ? "" : aws_iam_access_key.github_deploy[0].id
  sensitive   = true
}

output "github_deploy_secret_access_key" {
  description = "access_key auth: set as the AWS_SECRET_ACCESS_KEY repository secret."
  value       = local.use_oidc ? "" : aws_iam_access_key.github_deploy[0].secret
  sensitive   = true
}

output "configure_kubectl" {
  value = "aws eks update-kubeconfig --region ${var.region} --name ${module.eks.cluster_name}"
}
