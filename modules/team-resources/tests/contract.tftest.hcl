# T01: bucket count varies, workload role count never does.
# T05: reordering keys, changing owner, and adding a bucket preserve existing
#      resource identities (no replacement).
# Essential direct-input failures (T06, Task 3 portion): Terraform repeats the
# type/value checks Python already enforces, for any direct module consumer.

mock_provider "aws" {}

variables {
  team_id               = "payments"
  environment           = "test"
  account_id            = "000000000000"
  owner                 = "team@example.invalid"
  trusted_principal_arn = "arn:aws:iam::000000000000:role/fixture-source"
  buckets = {
    reports = { visibility = "private" }
  }
}

# --- T01: role count is invariant under bucket count ------------------------

run "one_bucket_one_role" {
  command = plan

  assert {
    condition     = length(output.bucket_names) == 1
    error_message = "expected exactly one bucket"
  }

  assert {
    condition     = output.bucket_names["reports"] == "sumup--test--payments--reports"
    error_message = "bucket names must use sumup--environment--team--key without an account component"
  }

  assert {
    condition     = aws_iam_role.workload.name == "test--payments--s3"
    error_message = "expected a single, deterministically named workload role"
  }
}

run "three_buckets_still_one_role" {
  command = plan

  variables {
    buckets = {
      reports = { visibility = "private" }
      assets  = { visibility = "public" }
      logs    = { visibility = "private" }
    }
  }

  assert {
    condition     = length(output.bucket_names) == 3
    error_message = "expected three buckets"
  }

  assert {
    condition     = aws_iam_role.workload.name == "test--payments--s3"
    error_message = "role must stay the same single role regardless of bucket count"
  }
}

# --- T05: stable identities across reorder/owner-change/add -----------------

run "initial_apply" {
  command = apply

  variables {
    buckets = {
      reports = { visibility = "private" }
      assets  = { visibility = "public" }
    }
  }

  assert {
    condition     = length(output.bucket_names) == 2
    error_message = "expected two buckets on initial apply"
  }
}

run "reorder_keys_no_change" {
  command = plan

  variables {
    buckets = {
      assets  = { visibility = "public" }
      reports = { visibility = "private" }
    }
  }

  assert {
    condition     = output.bucket_names["reports"] == run.initial_apply.bucket_names["reports"]
    error_message = "reordering declared keys must not change the reports bucket name"
  }

  assert {
    condition     = output.bucket_names["assets"] == run.initial_apply.bucket_names["assets"]
    error_message = "reordering declared keys must not change the assets bucket name"
  }
}

run "owner_change_no_replacement" {
  command = apply

  variables {
    owner = "new-owner@example.invalid"
    buckets = {
      reports = { visibility = "private" }
      assets  = { visibility = "public" }
    }
  }

  # A mocked computed attribute (arn) only changes if the resource is
  # destroyed and recreated. An unchanged arn after apply proves the owner
  # tag change was applied in place, not as a replacement.
  assert {
    condition     = output.bucket_arns["reports"] == run.initial_apply.bucket_arns["reports"]
    error_message = "changing owner must not replace the reports bucket"
  }

  assert {
    condition     = output.bucket_arns["assets"] == run.initial_apply.bucket_arns["assets"]
    error_message = "changing owner must not replace the assets bucket"
  }
}

run "add_bucket_preserves_existing" {
  command = apply

  variables {
    owner = "new-owner@example.invalid"
    buckets = {
      reports = { visibility = "private" }
      assets  = { visibility = "public" }
      logs    = { visibility = "private" }
    }
  }

  assert {
    condition     = output.bucket_arns["reports"] == run.initial_apply.bucket_arns["reports"]
    error_message = "adding a bucket must preserve the existing reports bucket identity"
  }

  assert {
    condition     = output.bucket_arns["assets"] == run.initial_apply.bucket_arns["assets"]
    error_message = "adding a bucket must preserve the existing assets bucket identity"
  }

  assert {
    condition     = length(output.bucket_names) == 3
    error_message = "expected three buckets after addition"
  }
}

# --- Essential direct-input failures (Terraform repeats Python's checks) ----

run "rejects_empty_buckets" {
  command = plan

  variables {
    buckets = {}
  }

  expect_failures = [var.buckets]
}

run "rejects_invalid_visibility" {
  command = plan

  variables {
    buckets = {
      reports = { visibility = "Public" }
    }
  }

  expect_failures = [var.buckets]
}

run "rejects_invalid_bucket_key" {
  command = plan

  variables {
    buckets = {
      "Reports" = { visibility = "private" }
    }
  }

  expect_failures = [var.buckets]
}

run "rejects_reserved_suffix_bucket_key" {
  command = plan

  variables {
    buckets = {
      "x-s3" = { visibility = "private" }
    }
  }

  expect_failures = [var.buckets]
}

run "rejects_invalid_team_id" {
  command = plan

  variables {
    team_id = "Payments"
  }

  expect_failures = [var.team_id]
}

run "rejects_invalid_account_id" {
  command = plan

  variables {
    account_id = "12345"
  }

  expect_failures = [var.account_id]
}

run "rejects_wrong_account_trusted_principal" {
  command = plan

  variables {
    trusted_principal_arn = "arn:aws:iam::111111111111:role/fixture-source"
  }

  expect_failures = [var.trusted_principal_arn]
}

run "rejects_account_root_trust" {
  command = plan

  variables {
    trusted_principal_arn = "arn:aws:iam::000000000000:root"
  }

  expect_failures = [var.trusted_principal_arn]
}

run "rejects_wildcard_trust" {
  command = plan

  variables {
    trusted_principal_arn = "arn:aws:iam::000000000000:role/*"
  }

  expect_failures = [var.trusted_principal_arn]
}

run "rejects_tag_unsafe_owner" {
  command = plan

  variables {
    owner = "team, other@example.invalid"
  }

  expect_failures = [var.owner]
}

run "live_permissions_boundary_is_attached" {
  command = plan
  variables {
    permissions_boundary_arn = "arn:aws:iam::000000000000:policy/sumup-boundary--test--payments"
  }
  assert {
    condition     = aws_iam_role.workload.permissions_boundary == "arn:aws:iam::000000000000:policy/sumup-boundary--test--payments"
    error_message = "The platform-supplied workload permissions boundary must reach the actual role."
  }
}
run "reject_another_teams_permissions_boundary" {
  command = plan
  variables {
    permissions_boundary_arn = "arn:aws:iam::000000000000:policy/sumup-boundary--test--customers"
  }
  expect_failures = [var.permissions_boundary_arn]
}
