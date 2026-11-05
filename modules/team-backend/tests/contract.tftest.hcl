mock_provider "aws" {}
variables {
  account_id = "123456789012"
  team_id    = "payments"
}
run "private_versioned_encrypted_backend" {
  command = plan
  assert {
    condition     = aws_s3_bucket.state.bucket == "sumup--tfstate--123456789012--payments" && aws_dynamodb_table.locks.name == aws_s3_bucket.state.bucket
    error_message = "Bucket and table must follow the uniform per-team/account convention."
  }
  assert {
    condition     = aws_s3_bucket_versioning.state.versioning_configuration[0].status == "Enabled" && one(aws_s3_bucket_server_side_encryption_configuration.state.rule).apply_server_side_encryption_by_default[0].sse_algorithm == "AES256"
    error_message = "State must be versioned and encrypted."
  }
  assert {
    condition     = aws_s3_bucket_public_access_block.state.block_public_acls && aws_s3_bucket_public_access_block.state.ignore_public_acls && aws_s3_bucket_public_access_block.state.block_public_policy && aws_s3_bucket_public_access_block.state.restrict_public_buckets && !aws_s3_bucket.state.force_destroy
    error_message = "Backend must remain private and protected against populated deletion."
  }
  assert {
    condition     = aws_dynamodb_table.locks.hash_key == "LockID" && aws_dynamodb_table.locks.attribute == toset([{ name = "LockID", type = "S" }]) && aws_dynamodb_table.locks.billing_mode == "PAY_PER_REQUEST" && aws_dynamodb_table.locks.deletion_protection_enabled && aws_dynamodb_table.locks.server_side_encryption[0].enabled && aws_dynamodb_table.locks.point_in_time_recovery[0].enabled
    error_message = "DynamoDB must implement Terraform's LockID contract and retain recovery protections."
  }
}

run "reject_reserved_backend_suffix" {
  command = plan
  variables { team_id = "team-an" }
  expect_failures = [aws_s3_bucket.state]
}
run "maximum_backend_name_has_headroom" {
  command = plan
  variables { team_id = "abcdefghijklmnop" }
  assert {
    condition     = length(aws_s3_bucket.state.bucket) == 46
    error_message = "The longest backend name should be 46 characters, below the S3 maximum."
  }
}
