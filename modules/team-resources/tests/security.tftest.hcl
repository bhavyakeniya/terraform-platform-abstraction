# T02: ownership/encryption/versioning/TLS/tags/force_destroy on every bucket.
# T03: private/public settings and anonymous current-object GET exactly.
# T04: exact policy actions/resources/denies/trust; ownership-deny key/
#      operator/account asserted separately from ARN scope.
# T06 (Task 4 portion): oversized-policy rejection.
# T08 (Task 4 portion): every reachable reserved-suffix key, positive
#      neighbors, and the maximum generated length of 51 characters.
#
# Policy assertions inspect the actual jsonencode() output of the real
# module resources -- never a mocked aws_iam_policy_document data source.

mock_provider "aws" {}

variables {
  team_id               = "payments"
  environment           = "test"
  account_id            = "000000000000"
  owner                 = "team@example.invalid"
  trusted_principal_arn = "arn:aws:iam::000000000000:role/fixture-source"
  buckets = {
    reports = { visibility = "private" }
    assets  = { visibility = "public" }
  }
}

# --- T02: controls apply to every bucket, private and public alike ---------

run "every_bucket_has_ownership_encryption_versioning_tags" {
  command = plan

  assert {
    condition     = aws_s3_bucket_ownership_controls.this["reports"].rule[0].object_ownership == "BucketOwnerEnforced"
    error_message = "private bucket must have BucketOwnerEnforced ownership"
  }
  assert {
    condition     = aws_s3_bucket_ownership_controls.this["assets"].rule[0].object_ownership == "BucketOwnerEnforced"
    error_message = "public bucket must have BucketOwnerEnforced ownership"
  }

  assert {
    condition     = aws_s3_bucket_versioning.this["reports"].versioning_configuration[0].status == "Enabled"
    error_message = "private bucket must have versioning enabled"
  }
  assert {
    condition     = aws_s3_bucket_versioning.this["assets"].versioning_configuration[0].status == "Enabled"
    error_message = "public bucket must have versioning enabled"
  }

  # rule is a set block (unordered, not addressable by [0]); one() extracts
  # the single element.
  assert {
    condition     = one(aws_s3_bucket_server_side_encryption_configuration.this["reports"].rule).apply_server_side_encryption_by_default[0].sse_algorithm == "AES256"
    error_message = "private bucket must default to AES256 encryption"
  }
  assert {
    condition     = one(aws_s3_bucket_server_side_encryption_configuration.this["assets"].rule).apply_server_side_encryption_by_default[0].sse_algorithm == "AES256"
    error_message = "public bucket must default to AES256 encryption"
  }

  assert {
    condition     = aws_s3_bucket.this["reports"].force_destroy == false
    error_message = "force_destroy must be false"
  }
  assert {
    condition     = aws_s3_bucket.this["assets"].force_destroy == false
    error_message = "force_destroy must be false"
  }

  assert {
    condition = (
      aws_s3_bucket.this["reports"].tags["Team"] == "payments" &&
      aws_s3_bucket.this["reports"].tags["Environment"] == "test" &&
      aws_s3_bucket.this["reports"].tags["Owner"] == "team@example.invalid" &&
      aws_s3_bucket.this["reports"].tags["ManagedBy"] == "Terraform"
    )
    error_message = "expected exact platform tags on every bucket"
  }

  assert {
    condition     = jsondecode(local.bucket_policies["reports"]).Statement[0].Sid == "DenyInsecureTransport"
    error_message = "private bucket policy must deny insecure transport"
  }
  assert {
    condition     = jsondecode(local.bucket_policies["assets"]).Statement[0].Sid == "DenyInsecureTransport"
    error_message = "public bucket policy must also deny insecure transport"
  }
  assert {
    condition     = jsondecode(local.bucket_policies["reports"]).Statement[0].Condition.Bool["aws:SecureTransport"] == "false"
    error_message = "TLS denial must condition on aws:SecureTransport=false"
  }
}

# --- T03: private/public settings and anonymous current-object GET exactly -

run "private_bucket_fully_blocks_public_access_and_grants_none" {
  command = plan

  assert {
    condition = (
      aws_s3_bucket_public_access_block.this["reports"].block_public_acls == true &&
      aws_s3_bucket_public_access_block.this["reports"].ignore_public_acls == true &&
      aws_s3_bucket_public_access_block.this["reports"].block_public_policy == true &&
      aws_s3_bucket_public_access_block.this["reports"].restrict_public_buckets == true
    )
    error_message = "private bucket must have all four public-access-block flags true"
  }

  assert {
    condition     = length(jsondecode(local.bucket_policies["reports"]).Statement) == 1
    error_message = "private bucket policy must contain only the TLS-denial statement, no anonymous grant"
  }
}

run "public_bucket_relaxes_only_policy_flags_and_grants_current_object_get_only" {
  command = plan

  assert {
    condition = (
      aws_s3_bucket_public_access_block.this["assets"].block_public_acls == true &&
      aws_s3_bucket_public_access_block.this["assets"].ignore_public_acls == true &&
      aws_s3_bucket_public_access_block.this["assets"].block_public_policy == false &&
      aws_s3_bucket_public_access_block.this["assets"].restrict_public_buckets == false
    )
    error_message = "public bucket must keep ACL flags blocked and relax only policy/restrict flags"
  }

  assert {
    condition = (
      jsondecode(local.bucket_policies["assets"]).Statement[1].Sid == "AllowPublicReadCurrentObjects" &&
      jsondecode(local.bucket_policies["assets"]).Statement[1].Effect == "Allow" &&
      jsondecode(local.bucket_policies["assets"]).Statement[1].Principal == "*" &&
      jsondecode(local.bucket_policies["assets"]).Statement[1].Action == "s3:GetObject"
    )
    error_message = "public bucket must grant exactly anonymous s3:GetObject"
  }

  assert {
    condition     = jsondecode(local.bucket_policies["assets"]).Statement[1].Resource == "arn:aws:s3:::${local.bucket_names["assets"]}/*"
    error_message = "anonymous grant must target current objects only (bucket/*), never the bucket ARN itself (no listing)"
  }

  assert {
    condition     = length(jsondecode(local.bucket_policies["assets"]).Statement) == 2
    error_message = "public bucket policy must contain exactly TLS-denial plus the one anonymous-read statement -- no list/write/delete grant"
  }
}

# --- T04: exact policy actions/resources/denies/trust ----------------------

run "workload_policy_exact_allow_statements" {
  command = plan

  # Independent fixture contract for the actual attached policy, including
  # all fields/statements. An extra fifth allow or an unexpected condition
  # must fail even when each of the four expected statements still exists.
  # Round-trip the expected object to compare decoded JSON types consistently.
  assert {
    condition = jsondecode(aws_iam_role_policy.workload_s3.policy) == jsondecode(jsonencode({
      Version = "2012-10-17"
      Statement = [
        {
          Sid      = "ListOwnedBuckets"
          Effect   = "Allow"
          Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
          Resource = ["arn:aws:s3:::sumup--test--payments--assets", "arn:aws:s3:::sumup--test--payments--reports"]
        },
        {
          Sid      = "ReadWriteOwnedObjects"
          Effect   = "Allow"
          Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
          Resource = ["arn:aws:s3:::sumup--test--payments--assets/*", "arn:aws:s3:::sumup--test--payments--reports/*"]
        },
        {
          Sid    = "DenyOutsideOwnedResources"
          Effect = "Deny"
          Action = "s3:*"
          NotResource = [
            "arn:aws:s3:::sumup--test--payments--assets",
            "arn:aws:s3:::sumup--test--payments--reports",
            "arn:aws:s3:::sumup--test--payments--assets/*",
            "arn:aws:s3:::sumup--test--payments--reports/*",
          ]
        },
        {
          Sid    = "DenyWrongResourceAccount"
          Effect = "Deny"
          Action = ["s3:ListBucket", "s3:GetBucketLocation", "s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
          Resource = [
            "arn:aws:s3:::sumup--test--payments--assets",
            "arn:aws:s3:::sumup--test--payments--reports",
            "arn:aws:s3:::sumup--test--payments--assets/*",
            "arn:aws:s3:::sumup--test--payments--reports/*",
          ]
          Condition = {
            StringNotEquals = { "s3:ResourceAccount" = "000000000000" }
          }
        },
      ]
    }))
    error_message = "the attached workload policy must match the entire four-statement contract, with no extra permissions or fields"
  }

  assert {
    condition = (
      jsondecode(local.workload_policy_json).Statement[0].Sid == "ListOwnedBuckets" &&
      jsondecode(local.workload_policy_json).Statement[0].Effect == "Allow" &&
      toset(jsondecode(local.workload_policy_json).Statement[0].Action) == toset(["s3:ListBucket", "s3:GetBucketLocation"]) &&
      toset(jsondecode(local.workload_policy_json).Statement[0].Resource) == toset(local.owned_bucket_arns)
    )
    error_message = "ListOwnedBuckets statement must be exactly list/locate on the declared bucket ARNs, nothing more"
  }

  assert {
    condition = (
      jsondecode(local.workload_policy_json).Statement[1].Sid == "ReadWriteOwnedObjects" &&
      jsondecode(local.workload_policy_json).Statement[1].Effect == "Allow" &&
      toset(jsondecode(local.workload_policy_json).Statement[1].Action) == toset(["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]) &&
      toset(jsondecode(local.workload_policy_json).Statement[1].Resource) == toset(local.owned_object_arns)
    )
    error_message = "ReadWriteOwnedObjects statement must be exactly get/put/delete on the declared object ARNs"
  }
}

run "workload_policy_denies_outside_owned_and_excludes_foreign_arn" {
  command = plan

  assert {
    condition = (
      jsondecode(local.workload_policy_json).Statement[2].Sid == "DenyOutsideOwnedResources" &&
      jsondecode(local.workload_policy_json).Statement[2].Effect == "Deny" &&
      jsondecode(local.workload_policy_json).Statement[2].Action == "s3:*" &&
      toset(jsondecode(local.workload_policy_json).Statement[2].NotResource) == toset(local.owned_resources)
    )
    error_message = "DenyOutsideOwnedResources must be an exact NotResource deny over the owned set"
  }

  assert {
    condition     = !contains(jsondecode(local.workload_policy_json).Statement[2].NotResource, "arn:aws:s3:::sumup--test--reporting--reports")
    error_message = "another team's bucket ARN must never appear in the owned/exempted set"
  }
}

run "workload_policy_ownership_deny_key_operator_account" {
  command = plan

  # Asserted separately from ARN scope: this checks the condition key,
  # operator, and account value in isolation from the Resource list above.
  assert {
    condition     = jsondecode(local.workload_policy_json).Statement[3].Sid == "DenyWrongResourceAccount"
    error_message = "expected the fourth statement to be the resource-account ownership deny"
  }
  assert {
    condition     = keys(jsondecode(local.workload_policy_json).Statement[3].Condition)[0] == "StringNotEquals"
    error_message = "ownership deny must use the StringNotEquals operator"
  }
  assert {
    condition     = keys(jsondecode(local.workload_policy_json).Statement[3].Condition.StringNotEquals)[0] == "s3:ResourceAccount"
    error_message = "ownership deny must condition on the s3:ResourceAccount key"
  }
  assert {
    condition     = jsondecode(local.workload_policy_json).Statement[3].Condition.StringNotEquals["s3:ResourceAccount"] == var.account_id
    error_message = "ownership deny must compare against this team's own account_id"
  }
}

run "trust_exact_configured_principal_only" {
  command = plan

  assert {
    condition = (
      length(jsondecode(aws_iam_role.workload.assume_role_policy).Statement) == 1 &&
      jsondecode(aws_iam_role.workload.assume_role_policy).Statement[0].Effect == "Allow" &&
      jsondecode(aws_iam_role.workload.assume_role_policy).Statement[0].Action == "sts:AssumeRole" &&
      jsondecode(aws_iam_role.workload.assume_role_policy).Statement[0].Principal.AWS == var.trusted_principal_arn
    )
    error_message = "trust policy must contain exactly one statement trusting only the configured principal"
  }
}

# --- T06 (Task 4 portion): oversized-policy rejection -----------------------

run "rejects_oversized_inline_policy" {
  command = plan

  variables {
    environment = "environ8"         # 8 chars (max)
    team_id     = "teamid1234567890" # 16 chars (max)
    buckets = {
      bkt0000000000001 = { visibility = "private" }
      bkt0000000000002 = { visibility = "private" }
      bkt0000000000003 = { visibility = "private" }
      bkt0000000000004 = { visibility = "private" }
      bkt0000000000005 = { visibility = "private" }
      bkt0000000000006 = { visibility = "private" }
      bkt0000000000007 = { visibility = "private" }
      bkt0000000000008 = { visibility = "private" }
      bkt0000000000009 = { visibility = "private" }
      bkt0000000000010 = { visibility = "private" }
      bkt0000000000011 = { visibility = "private" }
      bkt0000000000012 = { visibility = "private" }
      bkt0000000000013 = { visibility = "private" }
      bkt0000000000014 = { visibility = "private" }
      bkt0000000000015 = { visibility = "private" }
      bkt0000000000016 = { visibility = "private" }
      bkt0000000000017 = { visibility = "private" }
      bkt0000000000018 = { visibility = "private" }
      bkt0000000000019 = { visibility = "private" }
      bkt0000000000020 = { visibility = "private" }
      bkt0000000000021 = { visibility = "private" }
      bkt0000000000022 = { visibility = "private" }
      bkt0000000000023 = { visibility = "private" }
      bkt0000000000024 = { visibility = "private" }
      bkt0000000000025 = { visibility = "private" }
      bkt0000000000026 = { visibility = "private" }
      bkt0000000000027 = { visibility = "private" }
      bkt0000000000028 = { visibility = "private" }
      bkt0000000000029 = { visibility = "private" }
      bkt0000000000030 = { visibility = "private" }
      bkt0000000000031 = { visibility = "private" }
      bkt0000000000032 = { visibility = "private" }
      bkt0000000000033 = { visibility = "private" }
      bkt0000000000034 = { visibility = "private" }
      bkt0000000000035 = { visibility = "private" }
    }
  }

  expect_failures = [aws_iam_role_policy.workload_s3]
}

# --- T08 (Task 4 portion): full reserved-suffix sweep + neighbors/boundary -

run "rejects_s3alias_suffix" {
  command = plan
  variables {
    buckets = { s3alias = { visibility = "private" } }
  }
  expect_failures = [var.buckets]
}

run "rejects_s3alias_suffix_with_prefix" {
  command = plan
  variables {
    buckets = { reports-s3alias = { visibility = "private" } }
  }
  expect_failures = [var.buckets]
}

run "rejects_x_s3_suffix" {
  command = plan
  variables {
    buckets = { x-s3 = { visibility = "private" } }
  }
  expect_failures = [var.buckets]
}

run "rejects_ol_s3_suffix" {
  command = plan
  variables {
    buckets = { ol-s3 = { visibility = "private" } }
  }
  expect_failures = [var.buckets]
}

run "rejects_table_s3_suffix" {
  command = plan
  variables {
    buckets = { table-s3 = { visibility = "private" } }
  }
  expect_failures = [var.buckets]
}

run "rejects_an_suffix" {
  command = plan
  variables {
    buckets = { an = { visibility = "private" } }
  }
  expect_failures = [var.buckets]
}

run "rejects_an_suffix_with_prefix" {
  command = plan
  variables {
    buckets = { reports-an = { visibility = "private" } }
  }
  expect_failures = [var.buckets]
}

run "accepts_positive_neighbor_keys" {
  command = plan
  variables {
    buckets = {
      s3alias-v2 = { visibility = "private" }
      x-s3-data  = { visibility = "private" }
      annual     = { visibility = "private" }
    }
  }
  assert {
    condition     = length(output.bucket_names) == 3
    error_message = "positive-neighbor bucket keys must be accepted"
  }
}

run "accepts_maximum_51_character_name" {
  command = plan
  variables {
    environment = "environ8"         # 8 chars (max)
    team_id     = "teamid1234567890" # 16 chars (max)
    buckets = {
      bucketkey0000001 = { visibility = "private" } # 16 chars (max)
    }
  }
  assert {
    condition     = length(output.bucket_names["bucketkey0000001"]) == 51
    error_message = "expected maximum-length components to produce 51 characters, leaving 12 below S3's limit"
  }
}
