# allowed_account_ids guards resource-management operations here (confirmed
# wrong in an earlier revision of this comment: the S3 backend block also
# accepts allowed_account_ids -- see backend.hcl.json, rendered by
# render_inputs in scripts/team_platform.py -- so state read/write is guarded
# there too). Two separate guards for two separate operations: this one never
# runs until a provider is actually configured, which happens after backend
# init has already touched state.

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.account_id]
}
