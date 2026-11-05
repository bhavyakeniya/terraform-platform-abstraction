# Section 3.2: this root's inputs are the module's inputs plus region, which
# configures the provider rather than the module. team_id/environment/
# account_id/owner/buckets/trusted_principal_arn are re-validated by the
# module's own variable blocks when it is instantiated below; duplicating
# those checks here would just be the same regex twice. region has no other
# validator, so it gets one here.

variable "team_id" {
  description = "Stable team identifier derived from the selected declaration directory."
  type        = string
  nullable    = false
}

variable "environment" {
  description = "Platform-selected environment for this team's resource names and tags."
  type        = string
  nullable    = false
}

variable "account_id" {
  description = "Expected AWS account for provider operations and the authenticated caller check."
  type        = string
  nullable    = false
}

variable "owner" {
  description = "Team owner contact metadata forwarded to resource tags."
  type        = string
  nullable    = false
}

variable "buckets" {
  description = "Team-declared bucket keys and explicit visibility, forwarded to the module."
  nullable    = false
  type = map(object({
    visibility = string
  }))
}

variable "trusted_principal_arn" {
  description = "Platform-approved existing same-account role that can assume the workload role."
  type        = string
  nullable    = false
}

variable "region" {
  description = "Explicit platform-selected commercial AWS region for resource operations."
  type        = string
  nullable    = false

  # Structurally excludes GovCloud (three hyphenated letter groups before the
  # digit, not two); the China partition can't be distinguished from a
  # commercial region name by shape alone, so it's explicitly denylisted too.
  # A pragmatic approximation, not a partition table -- allowed_account_ids
  # in providers.tf is the real safety mechanism.
  validation {
    condition     = can(regex("^[a-z]{2}-[a-z]+-[0-9]+$", var.region)) && !startswith(var.region, "cn-")
    error_message = "region must be a supported commercial AWS region, e.g. eu-central-1."
  }
}

variable "permissions_boundary_arn" {
  description = "Platform-managed boundary required for live CI; null only for legacy/local module consumers."
  type        = string
  default     = null
  validation {
    condition     = var.permissions_boundary_arn == null ? true : var.permissions_boundary_arn == "arn:aws:iam::${var.account_id}:policy/sumup-boundary--${var.environment}--${var.team_id}"
    error_message = "Use the platform boundary for this exact account/team/environment."
  }
}
