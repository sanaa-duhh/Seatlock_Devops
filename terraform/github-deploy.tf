# Identity that GitHub Actions uses to deploy. Either way it can only describe this
# cluster, and its EKS access entry (main.tf) limits it to the app namespace.

locals {
  use_oidc = var.github_deploy_auth == "oidc"
  github_deploy_principal_arn = (local.use_oidc
    ? aws_iam_role.github_deploy[0].arn
  : aws_iam_user.github_deploy[0].arn)
}

data "aws_iam_policy_document" "github_deploy" {
  statement {
    sid       = "ReadClusterEndpoint"
    actions   = ["eks:DescribeCluster"]
    resources = [module.eks.cluster_arn]
  }
}

# --- Preferred: OIDC. Short-lived tokens, no AWS keys stored in GitHub. ---------------

# An AWS account can hold only one provider per URL, so reuse an existing one if present.
resource "aws_iam_openid_connect_provider" "github" {
  count          = local.use_oidc && var.create_github_oidc_provider ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_openid_connect_provider" "github" {
  count = local.use_oidc && !var.create_github_oidc_provider ? 1 : 0
  url   = "https://token.actions.githubusercontent.com"
}

data "aws_iam_policy_document" "github_trust" {
  count = local.use_oidc ? 1 : 0

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type = "Federated"
      identifiers = [var.create_github_oidc_provider
        ? aws_iam_openid_connect_provider.github[0].arn
      : data.aws_iam_openid_connect_provider.github[0].arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Only the production environment of this one repository may assume the role.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:environment:production"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  count                = local.use_oidc ? 1 : 0
  name                 = "${var.cluster_name}-github-deploy"
  assume_role_policy   = data.aws_iam_policy_document.github_trust[0].json
  max_session_duration = 3600
}

resource "aws_iam_role_policy" "github_deploy" {
  count  = local.use_oidc ? 1 : 0
  name   = "describe-cluster"
  role   = aws_iam_role.github_deploy[0].id
  policy = data.aws_iam_policy_document.github_deploy.json
}

# --- Fallback: a dedicated deploy user, for accounts that forbid OIDC providers. ------

resource "aws_iam_user" "github_deploy" {
  count = local.use_oidc ? 0 : 1
  name  = "${var.cluster_name}-github-deploy"
}

resource "aws_iam_user_policy" "github_deploy" {
  count  = local.use_oidc ? 0 : 1
  name   = "describe-cluster"
  user   = aws_iam_user.github_deploy[0].name
  policy = data.aws_iam_policy_document.github_deploy.json
}

# Lives only as long as the cluster; terraform destroy deletes it.
resource "aws_iam_access_key" "github_deploy" {
  count = local.use_oidc ? 0 : 1
  user  = aws_iam_user.github_deploy[0].name
}
