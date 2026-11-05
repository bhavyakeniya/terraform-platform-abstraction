# Section 3.2: "allowed_account_ids and an authenticated caller check" are
# two distinct mechanisms. allowed_account_ids (providers.tf) is a provider-
# level guard that isn't exercised under a full mock_provider. This data
# source's postcondition is the second, explicit, independently testable
# check: it fails the plan if the authenticated caller's account doesn't
# match the configured account_id, and can be exercised in tests via
# override_data without needing a real AWS account.

data "aws_caller_identity" "current" {
  lifecycle {
    postcondition {
      condition     = self.account_id == var.account_id
      error_message = "authenticated caller account ${self.account_id} does not match configured account_id ${var.account_id}."
    }
  }
}
