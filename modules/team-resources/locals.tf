# Section 3.3 naming formulas. Bucket names depend on environment/team/key,
# not account: identical contexts in different accounts would collide in S3.
# No timestamps, random suffixes, or list-index dependence.

locals {
  bucket_names = {
    for key, value in var.buckets :
    key => format("sumup--%s--%s--%s", var.environment, var.team_id, key)
  }

  role_name = format("tfp--%s--%s--s3", var.environment, var.team_id)
  role_path = format("/team-platform/runtime/%s/%s/", var.environment, var.team_id)

  tags = {
    Team        = var.team_id
    Environment = var.environment
    Owner       = var.owner
    ManagedBy   = "Terraform"
  }
}
