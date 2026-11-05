# Section 3.4: exactly one workload role, trusting only the configured
# principal. No IAM administration, no bucket-policy administration, no
# backend access, no deployment role, no permissions-boundary infrastructure
# -- those are privileged platform/bootstrap work outside this module.

resource "aws_iam_role" "workload" {
  name                 = local.role_name
  path                 = local.role_path
  permissions_boundary = var.permissions_boundary_arn

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "TrustConfiguredPrincipalOnly"
        Effect    = "Allow"
        Principal = { AWS = var.trusted_principal_arn }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = local.tags
}

resource "aws_iam_role_policy" "workload_s3" {
  name   = "s3-access"
  role   = aws_iam_role.workload.id
  policy = local.workload_policy_json

  lifecycle {
    precondition {
      # AWS: aggregate inline role policy size <= 10,240 characters,
      # whitespace excluded (verified against the current IAM quotas page).
      # jsonencode() output is already compact with no inserted whitespace,
      # so its length already matches how IAM counts the policy.
      condition     = length(local.workload_policy_json) <= 10240
      error_message = "generated inline policy is ${length(local.workload_policy_json)} characters, over the IAM role inline-policy aggregate limit of 10240; declare fewer buckets for this team."
    }
  }
}

locals {
  # S3 bucket ARNs have no account/region component (arn:aws:s3:::<name>),
  # so they're computable directly from the deterministic bucket_names map
  # without depending on the aws_s3_bucket resources existing. This keeps
  # the whole policy -- and the size precondition above -- evaluable at plan
  # time, before any bucket is created.
  owned_bucket_arns = [for name in local.bucket_names : "arn:aws:s3:::${name}"]
  owned_object_arns = [for name in local.bucket_names : "arn:aws:s3:::${name}/*"]
  owned_resources   = concat(local.owned_bucket_arns, local.owned_object_arns)

  # Section 3.4's exact four statements:
  #  1. list/locate the declared buckets
  #  2. read/write/delete the declared buckets' objects
  #  3. deny everything else in S3 (NotResource over the owned set)
  #  4. deny the allowed operations if the resource-account context ever
  #     differs from account_id -- a bucket's readable name is not
  #     ownership proof. s3:ResourceAccount condition-key
  #     support per listed action needs re-verification against the pinned
  #     provider/AWS release (Task 4 security audit).
  workload_policy_json = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ListOwnedBuckets"
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = local.owned_bucket_arns
      },
      {
        Sid      = "ReadWriteOwnedObjects"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = local.owned_object_arns
      },
      {
        Sid         = "DenyOutsideOwnedResources"
        Effect      = "Deny"
        Action      = "s3:*"
        NotResource = local.owned_resources
      },
      {
        Sid      = "DenyWrongResourceAccount"
        Effect   = "Deny"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation", "s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = local.owned_resources
        Condition = {
          StringNotEquals = {
            "s3:ResourceAccount" = var.account_id
          }
        }
      }
    ]
  })
}
