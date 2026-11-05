locals {
  suffix      = "${var.environment}--${var.team_id}"
  bucket      = "sumup--tfstate--${var.account_id}--${var.team_id}"
  state_key   = "workloads/${var.account_id}/${var.environment}/teams/${var.team_id}/terraform.tfstate"
  runtime_arn = "arn:aws:iam::${var.account_id}:role/team-platform/runtime/${var.environment}/${var.team_id}/${local.suffix}--s3"
  bucket_arn  = "arn:aws:s3:::sumup--${local.suffix}--*"
  tags        = { Team = var.team_id, Environment = var.environment, ManagedBy = "Terraform" }
}

# The CI role can update an inline policy on its workload role. A protected
# permissions boundary prevents that capability becoming an IAM escalation.
resource "aws_iam_policy" "workload_boundary" {
  name = "sumup-boundary--${local.suffix}"
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Action = ["s3:ListBucket", "s3:GetBucketLocation", "s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    Resource  = [local.bucket_arn, "${local.bucket_arn}/*"]
    Condition = { StringEquals = { "s3:ResourceAccount" = var.account_id } }
  }] })
  tags = local.tags
}
resource "aws_iam_role" "ci" {
  name                 = "sumup-ci--${local.suffix}"
  max_session_duration = 3600
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Federated = var.oidc_provider_arn }, Action = "sts:AssumeRoleWithWebIdentity"
    Condition = { StringEquals = {
      "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
      "token.actions.githubusercontent.com:sub" = var.oidc_subject
    } }
  }] })
  tags = local.tags
}
resource "aws_iam_role_policy" "ci" {
  name = "terraform-team-environment"
  role = aws_iam_role.ci.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Sid = "OwnWorkloadBuckets", Effect = "Allow", Action = [
      "s3:CreateBucket", "s3:DeleteBucket", "s3:GetBucket*", "s3:GetEncryptionConfiguration", "s3:GetAccelerateConfiguration",
      "s3:GetLifecycleConfiguration", "s3:GetReplicationConfiguration", "s3:ListBucket", "s3:ListBucketVersions",
      "s3:PutBucketPolicy", "s3:DeleteBucketPolicy", "s3:PutBucketVersioning", "s3:PutEncryptionConfiguration",
      "s3:PutBucketPublicAccessBlock", "s3:PutBucketOwnershipControls",
      "s3:PutBucketTagging"
    ], Resource = local.bucket_arn },
    { Sid = "ListOwnStatePrefix", Effect = "Allow", Action = "s3:ListBucket", Resource = "arn:aws:s3:::${local.bucket}",
    Condition = { StringLike = { "s3:prefix" = [local.state_key, "${local.state_key}/*"] } } },
    { Sid = "OwnStateObject", Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = "arn:aws:s3:::${local.bucket}/${local.state_key}" },
    { Sid = "LocateBackend", Effect = "Allow", Action = "s3:GetBucketLocation", Resource = "arn:aws:s3:::${local.bucket}" },
    { Sid      = "OwnStateLock", Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"],
      Resource = "arn:aws:dynamodb:${var.region}:${var.account_id}:table/${local.bucket}",
    Condition = { "ForAllValues:StringEquals" = { "dynamodb:LeadingKeys" = ["${local.bucket}/${local.state_key}", "${local.bucket}/${local.state_key}-md5"] } } },
    { Sid = "DescribeOwnLockTable", Effect = "Allow", Action = "dynamodb:DescribeTable", Resource = "arn:aws:dynamodb:${var.region}:${var.account_id}:table/${local.bucket}" },
    { Sid = "CreateBoundedWorkloadRole", Effect = "Allow", Action = ["iam:CreateRole", "iam:PutRolePermissionsBoundary"], Resource = local.runtime_arn,
    Condition = { StringEquals = { "iam:PermissionsBoundary" = aws_iam_policy.workload_boundary.arn } } },
    { Sid = "ManageOwnWorkloadRole", Effect = "Allow", Action = [
      "iam:GetRole", "iam:ListRoleTags", "iam:UpdateRole", "iam:UpdateRoleDescription", "iam:DeleteRole", "iam:TagRole", "iam:UntagRole", "iam:UpdateAssumeRolePolicy",
      "iam:ListRolePolicies", "iam:GetRolePolicy", "iam:PutRolePolicy", "iam:DeleteRolePolicy",
      "iam:ListAttachedRolePolicies", "iam:ListInstanceProfilesForRole"
    ], Resource = local.runtime_arn },
    { Sid = "ProtectBoundary", Effect = "Deny", Action = "iam:DeleteRolePermissionsBoundary", Resource = local.runtime_arn },
    { Sid      = "PrivateEmergencyState", Effect = "Allow", Action = "s3:PutObject",
      Resource = "arn:aws:s3:::${local.bucket}/recovery/${var.environment}/*",
    Condition = { StringEquals = { "s3:x-amz-server-side-encryption" = "AES256" } } }

  ] })
}
output "execution_role_arn" {
  description = "Register this ARN for the team/environment shared workflow."
  value       = aws_iam_role.ci.arn
}
output "permissions_boundary_arn" {
  description = "Mandatory ceiling on every live pipeline-created workload role."
  value       = aws_iam_policy.workload_boundary.arn
}
