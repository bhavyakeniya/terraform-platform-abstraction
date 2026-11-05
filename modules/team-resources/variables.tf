# Section 3.2: no defaults anywhere. Python enforces the closed declaration
# format; these validations repeat the essential type/value checks directly
# in Terraform for any direct module consumer, per Section 3.1.

variable "team_id" {
  description = "Stable team identifier derived from its declaration directory by the platform."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[a-z][a-z0-9]*(-[a-z0-9]+)*$", var.team_id)) && length(var.team_id) <= 16
    error_message = "team_id must match ^[a-z][a-z0-9]*(-[a-z0-9]+)*$ with max length 16."
  }
}

variable "environment" {
  description = "Platform-selected environment used in resource names, tags, and state context."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[a-z][a-z0-9]*(-[a-z0-9]+)*$", var.environment)) && length(var.environment) <= 8
    error_message = "environment must match ^[a-z][a-z0-9]*(-[a-z0-9]+)*$ with max length 8."
  }
}

variable "account_id" {
  description = "Target commercial AWS account ID used for trust and resource-ownership checks."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "account_id must be exactly 12 digits."
  }
}

variable "owner" {
  description = "Tag-safe owner contact metadata supplied by the team; not an authorization identity."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9 ._:/=+@-]{0,127}$", var.owner))
    error_message = "owner must be tag-safe contact metadata matching ^[A-Za-z0-9][A-Za-z0-9 ._:/=+@-]{0,127}$."
  }

  validation {
    condition     = trimspace(var.owner) == var.owner
    error_message = "owner must not have leading or trailing whitespace."
  }
}

variable "buckets" {
  description = "Nonempty map keyed by stable bucket purpose, with explicit public/private visibility."
  nullable    = false
  type = map(object({
    visibility = string
  }))

  validation {
    condition     = length(var.buckets) > 0
    error_message = "buckets must declare at least one bucket."
  }

  validation {
    condition = alltrue([
      for key, value in var.buckets : contains(["public", "private"], value.visibility)
    ])
    error_message = "every bucket visibility must be exactly \"public\" or \"private\"."
  }

  validation {
    condition = alltrue([
      for key, value in var.buckets :
      can(regex("^[a-z][a-z0-9]*(-[a-z0-9]+)*$", key)) && length(key) <= 16
    ])
    error_message = "every bucket key must match ^[a-z][a-z0-9]*(-[a-z0-9]+)*$ with max length 16."
  }

  # Blocking precondition on completed names: a bad key fails here, at
  # variable-validation time, never as a warning-only check block or an AWS
  # create error. Pinned to the Section 3.3 reserved-suffix table; recheck
  # against AWS's bucket-naming-rules page on dependency changes.
  validation {
    condition = alltrue(flatten([
      for key, value in var.buckets : [
        for name in [format("sumup--%s--%s--%s", var.environment, var.team_id, key)] : (
          length(name) <= 63 &&
          !endswith(name, "-s3alias") &&
          !endswith(name, "--ol-s3") &&
          !endswith(name, "--x-s3") &&
          !endswith(name, "--table-s3") &&
          !endswith(name, "-an")
        )
      ]
    ]))
    error_message = "a completed bucket name would exceed 63 characters or end with an AWS-reserved suffix (-s3alias, --ol-s3, --x-s3, --table-s3, -an)."
  }
}

variable "trusted_principal_arn" {
  description = "Exact existing same-account IAM role allowed to assume the generated workload role."
  type        = string
  nullable    = false

  # Cross-variable validation (Terraform >= 1.9): must be an exact same-account
  # IAM role ARN. No wildcard assumption, no account-root trust.
  validation {
    condition     = can(regex("^arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_-]{1,64}$", var.trusted_principal_arn))
    error_message = "trusted_principal_arn must be an IAM role ARN matching ^arn:aws:iam::<12 digits>:role/<name>$ (no wildcard, no account-root trust)."
  }

  validation {
    condition     = can(regex("^arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_-]{1,64}$", var.trusted_principal_arn)) ? regex("^arn:aws:iam::([0-9]{12}):role/.+$", var.trusted_principal_arn)[0] == var.account_id : true
    error_message = "trusted_principal_arn must be a same-account IAM role ARN (its account must equal account_id)."
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
