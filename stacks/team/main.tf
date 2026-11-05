# One module invocation per root run (Section 3.2). Never iterate over teams
# here -- that's what distinct per-team backend keys and separate root
# invocations are for, not a for_each at this layer.

module "team" {
  source = "../../modules/team-resources"

  permissions_boundary_arn = var.permissions_boundary_arn
  team_id                  = var.team_id
  environment              = var.environment
  account_id               = var.account_id
  owner                    = var.owner
  buckets                  = var.buckets
  trusted_principal_arn    = var.trusted_principal_arn
}
