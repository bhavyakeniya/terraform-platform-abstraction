# Declaration-specific check only. T07's team-independent generic checks
# (output projection, wrong-caller-account rejection) live in
# generic.tftest.hcl and run once, not here -- this file is invoked once per
# team/example (check_batch, check-examples), so it must stay cheap.

mock_provider "aws" {
  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "000000000000"
    }
  }
}

run "check_example" {
  # No variables block: every value comes from -var-file. This is the run
  # make check-examples (and check_batch, per real team) drives, proving the
  # actual rendered declaration plans successfully through the real module's
  # full validation chain (naming, reserved suffixes, visibility, policy
  # construction) -- not a synthetic fixture. Assertions also verify that
  # no declared bucket is dropped or exposed under a different output key.
  # Terraform test variable precedence is
  # run-level > file-level > -var-file, confirmed empirically -- so this
  # file must never add variables of its own, or -var-file would be shadowed.
  command = plan

  assert {
    condition     = length(output.bucket_names) == length(var.buckets)
    error_message = "the root must expose exactly as many buckets as the declaration requests"
  }

  assert {
    condition     = toset(keys(output.bucket_names)) == toset(keys(var.buckets))
    error_message = "the root's bucket-name keys must match the declaration exactly"
  }
}
