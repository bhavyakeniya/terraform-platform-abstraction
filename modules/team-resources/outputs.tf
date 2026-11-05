output "role_arn" {
  description = "ARN of the S3 workload role for this team and environment."
  value       = aws_iam_role.workload.arn
}

output "bucket_names" {
  description = "S3 bucket names keyed by their declaration keys."
  value       = { for key, b in aws_s3_bucket.this : key => b.bucket }
}

output "bucket_arns" {
  description = "S3 bucket ARNs keyed by their declaration keys."
  value       = { for key, b in aws_s3_bucket.this : key => b.arn }
}

output "visibility" {
  description = "Declared public or private visibility keyed by bucket declaration key."
  value       = { for key, v in var.buckets : key => v.visibility }
}
