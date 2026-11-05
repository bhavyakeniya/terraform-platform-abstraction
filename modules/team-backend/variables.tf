variable "account_id" {
  description = "AWS account that owns this team's private backend."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "account_id must be twelve digits."
  }
}
variable "team_id" {
  description = "Stable team identifier; never rename a live backend without migration."
  type        = string
  nullable    = false
  validation {
    condition     = length(var.team_id) <= 16 && can(regex("^[a-z][a-z0-9]*(-[a-z0-9]+)*$", var.team_id))
    error_message = "team_id must be a lowercase identifier of at most 16 characters."
  }
}
