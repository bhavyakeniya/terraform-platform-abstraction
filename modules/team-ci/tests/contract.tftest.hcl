mock_provider "aws" {
  mock_resource "aws_iam_policy" {
    defaults = {
      arn = "arn:aws:iam::123456789012:policy/sumup-boundary--dev--payments"
    }
    override_during = plan
  }
}
variables {
  region            = "eu-central-1"
  account_id        = "123456789012"
  team_id           = "payments"
  environment       = "dev"
  oidc_provider_arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
  oidc_subject      = "repo:example/payments:environment:dev"
}
run "scoped_ci_identity_and_boundary" {
  command = plan
  assert {
    condition = jsondecode(aws_iam_role.ci.assume_role_policy) == jsondecode(jsonencode({
      Version = "2012-10-17", Statement = [{
        Effect = "Allow", Principal = { Federated = var.oidc_provider_arn }, Action = "sts:AssumeRoleWithWebIdentity"
        Condition = { StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = "repo:example/payments:environment:dev"
        } }
      }]
    }))
    error_message = "CI trust must match only the exact repository/environment and STS audience."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.ci.policy).Statement[4].Condition["ForAllValues:StringEquals"]["dynamodb:LeadingKeys"] == ["sumup--tfstate--123456789012--payments/workloads/123456789012/dev/teams/payments/terraform.tfstate", "sumup--tfstate--123456789012--payments/workloads/123456789012/dev/teams/payments/terraform.tfstate-md5"]
    error_message = "CI must not lock other environments or teams."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.ci.policy).Statement[6].Condition.StringEquals["iam:PermissionsBoundary"] == "arn:aws:iam::123456789012:policy/sumup-boundary--dev--payments" && jsondecode(aws_iam_role_policy.ci.policy).Statement[8].Effect == "Deny" && jsondecode(aws_iam_role_policy.ci.policy).Statement[8].Action == "iam:DeleteRolePermissionsBoundary"
    error_message = "Workload boundary must be required on creation and protected against removal."
  }
  assert {
    condition     = jsondecode(aws_iam_policy.workload_boundary.policy).Statement[0].Resource == ["arn:aws:s3:::sumup--dev--payments--*", "arn:aws:s3:::sumup--dev--payments--*/*"] && length(jsondecode(aws_iam_policy.workload_boundary.policy).Statement) == 1
    error_message = "The workload ceiling must stay within the team's own environment buckets."
  }
}
run "reject_wildcard_oidc_subject" {
  command = plan
  variables { oidc_subject = "repo:example/*:environment:dev" }
  expect_failures = [var.oidc_subject]
}

run "reject_a_different_environment_subject" {
  command = plan
  variables { oidc_subject = "repo:example/payments:environment:devx" }
  expect_failures = [var.oidc_subject]
}
run "private_recovery_and_region_scope" {
  command = plan
  assert {
    condition     = jsondecode(aws_iam_role_policy.ci.policy).Statement[9].Action == "s3:PutObject" && jsondecode(aws_iam_role_policy.ci.policy).Statement[9].Resource == "arn:aws:s3:::sumup--tfstate--123456789012--payments/recovery/dev/*" && jsondecode(aws_iam_role_policy.ci.policy).Statement[9].Condition.StringEquals["s3:x-amz-server-side-encryption"] == "AES256"
    error_message = "Emergency state upload must be encrypted and scoped to this team's environment."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.ci.policy).Statement[4].Resource == "arn:aws:dynamodb:eu-central-1:123456789012:table/sumup--tfstate--123456789012--payments"
    error_message = "DynamoDB access must use the exact backend region."
  }
}
run "whole_ci_policy_contract" {
  command = plan
  assert {
    condition     = jsondecode(aws_iam_role_policy.ci.policy) == jsondecode(file("${path.module}/tests/ci-policy.json"))
    error_message = "CI permissions must exactly match the independently reviewed policy fixture, including no extra statements or fields."
  }
}
