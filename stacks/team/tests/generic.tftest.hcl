# T07: the generic root projects module outputs, and rejects a mocked
# caller identity whose account doesn't match the configured account_id.
#
# Team-independent: both runs use a fixed synthetic fixture, never real
# declaration content, so they belong here -- run once as part of the
# general test pass -- not in declaration.tftest.hcl, which check_batch and
# check-examples invoke once per team/example. Splitting them out means a
# 50-team batch no longer re-runs these same two generic checks 50 times.

mock_provider "aws" {
  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "000000000000"
    }
  }
}

run "projects_outputs" {
  # Computed attributes like role_arn/bucket_arns are only known after
  # apply, even under mock_provider -- a plan-only run legitimately leaves
  # them unknown, matching real Terraform behavior for not-yet-created
  # resources.
  command = apply

  variables {
    team_id               = "payments"
    environment           = "test"
    account_id            = "000000000000"
    owner                 = "team@example.invalid"
    region                = "eu-central-1"
    trusted_principal_arn = "arn:aws:iam::000000000000:role/fixture-source"
    buckets = {
      reports = { visibility = "private" }
      assets  = { visibility = "public" }
    }
  }

  assert {
    condition     = output.role_arn != null
    error_message = "expected role_arn to be projected from the module"
  }

  assert {
    condition     = output.bucket_names["reports"] == "sumup--test--payments--reports"
    error_message = "expected bucket_names to be projected from the module with the deterministic name"
  }

  assert {
    condition     = output.visibility["assets"] == "public"
    error_message = "expected visibility to be projected from the module"
  }

  assert {
    condition     = length(output.bucket_arns) == 2
    error_message = "expected bucket_arns to be projected for both declared buckets"
  }
}

run "rejects_mocked_wrong_caller_account" {
  command = plan

  variables {
    team_id               = "payments"
    environment           = "test"
    account_id            = "000000000000"
    owner                 = "team@example.invalid"
    region                = "eu-central-1"
    trusted_principal_arn = "arn:aws:iam::000000000000:role/fixture-source"
    buckets = {
      reports = { visibility = "private" }
    }
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "999999999999"
    }
  }

  expect_failures = [data.aws_caller_identity.current]
}
