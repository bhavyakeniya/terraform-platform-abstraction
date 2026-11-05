mock_provider "aws" {}
override_data {
  target = data.aws_caller_identity.current
  values = { account_id = "000000000000" }
}
variables {
  account_id = "000000000000"
  region     = "eu-central-1"
  team_ids   = ["payments", "customers", "accounting"]
  ci_bindings = {
    payments-dev = { team_id = "payments", environment = "dev", oidc_subject = "repo:example/payments:environment:dev" }
  }
}
run "one_backend_per_team_and_one_ci_role_per_binding" {
  command = plan
  assert {
    condition     = length(output.backends) == 3 && length(output.execution_roles) == 1
    error_message = "Bootstrap must keep team backends and environment CI identities separate."
  }
}
run "reject_duplicate_ci_bindings" {
  command = plan
  variables {
    ci_bindings = {
      first  = { team_id = "payments", environment = "dev", oidc_subject = "repo:example/payments:environment:dev" }
      second = { team_id = "payments", environment = "dev", oidc_subject = "repo:example/payments:environment:dev" }
    }
  }
  expect_failures = [var.ci_bindings]
}
