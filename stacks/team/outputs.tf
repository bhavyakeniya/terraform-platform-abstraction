output "role_arn" {
  description = "ARN of the S3 workload role for the selected team and environment."
  value       = module.team.role_arn
}

output "bucket_names" {
  description = "S3 bucket names for the selected team and environment, keyed by declaration key."
  value       = module.team.bucket_names
}

output "bucket_arns" {
  description = "S3 bucket ARNs for the selected team and environment, keyed by declaration key."
  value       = module.team.bucket_arns
}

output "visibility" {
  description = "Declared public or private visibility for the selected team and environment, keyed by bucket declaration key."
  value       = module.team.visibility
}
