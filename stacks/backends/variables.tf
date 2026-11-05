variable "account_id" {
  description = "Explicit bootstrap destination account."
  type        = string
  nullable    = false
}
variable "region" {
  description = "Region for the team backend resources."
  type        = string
  nullable    = false
}
variable "team_ids" {
  description = "Registered teams in this account. Removing one is blocked by prevent_destroy."
  type        = set(string)
  nullable    = false
  validation {
    condition     = length(var.team_ids) > 0
    error_message = "At least one team is required."
  }
}
variable "ci_bindings" {
  description = "Platform-approved team/environment OIDC bindings; empty until real GitHub identities are known."
  type = map(object({
    team_id      = string
    environment  = string
    oidc_subject = string
  }))
  nullable = false
  default  = {}
  validation {
    condition     = alltrue([for binding in values(var.ci_bindings) : contains(var.team_ids, binding.team_id)])
    error_message = "Every CI binding must belong to a provisioned team backend."
  }
  validation {
    condition     = length(distinct([for binding in values(var.ci_bindings) : "${binding.environment}--${binding.team_id}"])) == length(var.ci_bindings)
    error_message = "Duplicate team/environment CI bindings are forbidden."
  }
}

