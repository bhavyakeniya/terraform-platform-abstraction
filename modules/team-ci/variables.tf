variable "account_id" {
  description = "Destination AWS account."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "account_id must be twelve digits."
  }
}
variable "team_id" {
  description = "Registered team, matching the backend and consumer."
  type        = string
  nullable    = false
  validation {
    condition     = length(var.team_id) <= 16 && can(regex("^[a-z][a-z0-9]*(-[a-z0-9]+)*$", var.team_id))
    error_message = "Invalid team identifier."
  }
}
variable "environment" {
  description = "Registered environment, matching the GitHub environment."
  type        = string
  nullable    = false
  validation {
    condition     = length(var.environment) <= 8 && can(regex("^[a-z][a-z0-9]*(-[a-z0-9]+)*$", var.environment))
    error_message = "Invalid environment identifier."
  }
}
variable "oidc_provider_arn" {
  description = "Existing account-level GitHub OIDC provider; shared by all teams."
  type        = string
  nullable    = false
  validation {
    condition     = var.oidc_provider_arn == "arn:aws:iam::${var.account_id}:oidc-provider/token.actions.githubusercontent.com"
    error_message = "Use this account's GitHub Actions OIDC provider."
  }
}
variable "oidc_subject" {
  description = "Exact verified subject claim for the caller repository and protected GitHub environment; no wildcards."
  type        = string
  nullable    = false
  validation {
    condition     = startswith(var.oidc_subject, "repo:") && can(regex(":environment:${var.environment}(:|$)", var.oidc_subject)) && !strcontains(var.oidc_subject, "*") && !strcontains(var.oidc_subject, "?")
    error_message = "Require an exact repository/environment subject, verified from your GitHub OIDC configuration."
  }
}

variable "region" {
  description = "Exact backend region for DynamoDB permissions."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[a-z]{2}-[a-z]+-[0-9]+$", var.region)) && !startswith(var.region, "cn-")
    error_message = "Use the configured commercial AWS region."
  }
}
