# Scanner-only composition: exercise private AND explicitly public branches,
# backend controls, and deployment IAM with concrete inputs. Never apply it.
terraform {
  required_version = "~> 1.17.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
provider "aws" {
  region              = "eu-central-1"
  allowed_account_ids = ["000000000000"]
}
module "private" {
  source                   = "../../modules/team-resources"
  account_id               = "000000000000"
  team_id                  = "private-scan"
  environment              = "test"
  owner                    = "security@example.invalid"
  trusted_principal_arn    = "arn:aws:iam::000000000000:role/fixture-source"
  permissions_boundary_arn = "arn:aws:iam::000000000000:policy/sumup-boundary--test--private-scan"
  buckets                  = { data = { visibility = "private" } }
}
# Direct anonymous-read buckets are an explicit assignment requirement. Scope
# these two exceptions to the public fixture ONLY; private modules stay checked.
#trivy:ignore:AWS-0087
#trivy:ignore:AWS-0093
module "public" {
  source                   = "../../modules/team-resources"
  account_id               = "000000000000"
  team_id                  = "public-scan"
  environment              = "test"
  owner                    = "security@example.invalid"
  trusted_principal_arn    = "arn:aws:iam::000000000000:role/fixture-source"
  permissions_boundary_arn = "arn:aws:iam::000000000000:policy/sumup-boundary--test--public-scan"
  buckets                  = { assets = { visibility = "public" } }
}
module "backend" {
  source     = "../../modules/team-backend"
  account_id = "000000000000"
  team_id    = "security"
}
module "ci" {
  source            = "../../modules/team-ci"
  account_id        = "000000000000"
  region            = "eu-central-1"
  team_id           = "security"
  environment       = "test"
  oidc_provider_arn = "arn:aws:iam::000000000000:oidc-provider/token.actions.githubusercontent.com"
  oidc_subject      = "repo:example/security:environment:test"
}
