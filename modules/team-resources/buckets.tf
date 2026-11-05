# Section 3.4: BucketOwnerEnforced ownership, SSE-S3/AES256 encryption,
# versioning, TLS-only access, force_destroy=false, platform tags. Separate
# control resources, one composed policy per bucket, no ACL resources.

# Access logging is outside this take-home scope; see docs/security-scanning.md.
#trivy:ignore:AWS-0089
resource "aws_s3_bucket" "this" {
  #checkov:skip=CKV_AWS_18:Access logging requires a separate log destination; outside this take-home scope (docs/security-scanning.md).
  #checkov:skip=CKV_AWS_144:Cross-region replication requires a separate region/role/retention design; outside scope.
  #checkov:skip=CKV_AWS_145:SSE-S3 is the documented encryption contract; customer-managed KMS is not required here.
  #checkov:skip=CKV2_AWS_61:No automatic data/state expiry is chosen; retention is an explicit operator decision.
  #checkov:skip=CKV2_AWS_62:No notification consumer is required; do not invent event destinations for this abstraction.
  for_each = var.buckets

  bucket        = local.bucket_names[each.key]
  force_destroy = false

  tags = local.tags
}

resource "aws_s3_bucket_ownership_controls" "this" {
  for_each = var.buckets

  bucket = aws_s3_bucket.this[each.key].id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = var.buckets

  bucket = aws_s3_bucket.this[each.key].id

  versioning_configuration {
    status = "Enabled"
  }
}

# SSE-S3 is the documented encryption choice; this waives CMK policy only.
#trivy:ignore:AWS-0132
resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = var.buckets

  bucket = aws_s3_bucket.this[each.key].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Section 3.4 table: private buckets keep all four flags true; approved public
# buckets relax only block_public_policy/restrict_public_buckets so the
# anonymous-read bucket policy below can take effect. ACL-related flags stay
# true in both cases -- no ACL resources are ever used by this module.
resource "aws_s3_bucket_public_access_block" "this" {
  for_each = var.buckets

  bucket = aws_s3_bucket.this[each.key].id

  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = var.buckets[each.key].visibility == "public" ? false : true
  restrict_public_buckets = var.buckets[each.key].visibility == "public" ? false : true
}

resource "aws_s3_bucket_policy" "this" {
  for_each = var.buckets

  bucket = aws_s3_bucket.this[each.key].id
  policy = local.bucket_policies[each.key]

  # Order policy creation after ownership/public-access controls (Section 3.4).
  depends_on = [
    aws_s3_bucket_ownership_controls.this,
    aws_s3_bucket_public_access_block.this,
  ]
}

locals {
  # jsonencode from deterministic ARNs (local.bucket_names, not the
  # aws_s3_bucket resources' computed .arn), not a mocked policy-document
  # data source: the generated JSON is directly inspectable in tests and
  # plans, and evaluable at plan time before any bucket exists. TLS denial
  # is always present; anonymous read is current-object GetObject only
  # (never list/write/delete/historical-version) and only for buckets
  # declared public.
  bucket_policies = {
    for key, name in local.bucket_names : key => jsonencode({
      Version = "2012-10-17"
      Statement = concat(
        [
          {
            Sid       = "DenyInsecureTransport"
            Effect    = "Deny"
            Principal = "*"
            Action    = "s3:*"
            Resource  = ["arn:aws:s3:::${name}", "arn:aws:s3:::${name}/*"]
            Condition = {
              Bool = {
                "aws:SecureTransport" = "false"
              }
            }
          }
        ],
        var.buckets[key].visibility == "public" ? [
          {
            Sid       = "AllowPublicReadCurrentObjects"
            Effect    = "Allow"
            Principal = "*"
            Action    = "s3:GetObject"
            Resource  = "arn:aws:s3:::${name}/*"
          }
        ] : []
      )
    })
  }
}
