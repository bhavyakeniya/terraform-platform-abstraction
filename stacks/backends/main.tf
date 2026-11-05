# Operated by the platform administrator, never by a team workload workflow.
# Initial local bootstrap state must be secured and migrated to an independently
# provisioned platform backend; it cannot safely store itself in a team bucket.
provider "aws" {
  region              = var.region
  allowed_account_ids = [var.account_id]
}
data "aws_caller_identity" "current" {
  lifecycle {
    postcondition {
      condition     = self.account_id == var.account_id
      error_message = "Bootstrap caller is in the wrong AWS account."
    }
  }
}
module "team_backend" {
  for_each   = var.team_ids
  source     = "../../modules/team-backend"
  account_id = var.account_id
  team_id    = each.key
}
output "backends" {
  description = "Team-specific backend destinations; environments use distinct object keys."
  value = { for team, backend in module.team_backend : team => {
    bucket = backend.bucket_name, dynamodb_table = backend.dynamodb_table
  } }
}
module "team_ci" {
  for_each          = var.ci_bindings
  source            = "../../modules/team-ci"
  account_id        = var.account_id
  team_id           = each.value.team_id
  environment       = each.value.environment
  region            = var.region
  oidc_provider_arn = "arn:aws:iam::${var.account_id}:oidc-provider/token.actions.githubusercontent.com"
  oidc_subject      = each.value.oidc_subject
  depends_on        = [module.team_backend]
}
output "execution_roles" {
  description = "Per-team/environment CI identities for platform registration."
  value       = { for key, binding in module.team_ci : key => binding.execution_role_arn }
}
