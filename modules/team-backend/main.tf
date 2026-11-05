locals {
  name = "sumup--tfstate--${var.account_id}--${var.team_id}"
  tags = { Team = var.team_id, ManagedBy = "Terraform", Component = "terraform-backend" }
}

# Access logging is outside this take-home scope; see docs/security-scanning.md.
#trivy:ignore:AWS-0089
resource "aws_s3_bucket" "state" {
  #checkov:skip=CKV_AWS_18:Access logging requires a separate log destination; outside this take-home scope (docs/security-scanning.md).
  #checkov:skip=CKV_AWS_144:Cross-region replication requires a separate region/role/retention design; outside scope.
  #checkov:skip=CKV_AWS_145:SSE-S3 is the documented encryption contract; customer-managed KMS is not required here.
  #checkov:skip=CKV2_AWS_61:No automatic data/state expiry is chosen; retention is an explicit operator decision.
  #checkov:skip=CKV2_AWS_62:No notification consumer is required; do not invent event destinations for this abstraction.
  bucket        = local.name
  force_destroy = false
  tags          = local.tags
  lifecycle {
    prevent_destroy = true
    precondition {
      condition     = alltrue([for suffix in ["-s3alias", "--ol-s3", ".mrap", "--x-s3", "--table-s3", "-an"] : !endswith(local.name, suffix)])
      error_message = "The completed backend bucket name has an AWS-reserved suffix; choose another team identifier."
    }
  }
}
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration { status = "Enabled" }
  lifecycle { prevent_destroy = true }
}
# SSE-S3 is the documented encryption choice; this waives CMK policy only.
#trivy:ignore:AWS-0132
resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id
  rule { object_ownership = "BucketOwnerEnforced" }
}
resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport", Effect = "Deny", Principal = "*", Action = "s3:*"
      Resource  = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}
# AWS-managed encryption is deliberate; customer-managed KMS is outside scope.
#trivy:ignore:AWS-0025
resource "aws_dynamodb_table" "locks" {
  #checkov:skip=CKV_AWS_119:AWS-managed DynamoDB encryption is deliberate; see docs/security-scanning.md.
  name                        = local.name
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "LockID"
  deletion_protection_enabled = true
  attribute {
    name = "LockID"
    type = "S"
  }
  server_side_encryption { enabled = true }
  point_in_time_recovery { enabled = true }
  tags = local.tags
  lifecycle { prevent_destroy = true }
}
output "bucket_name" {
  description = "Private, versioned team backend bucket."
  value       = aws_s3_bucket.state.id
}
output "dynamodb_table" {
  description = "Team lock table, with one distinct LockID per environment state."
  value       = aws_dynamodb_table.locks.name
}
