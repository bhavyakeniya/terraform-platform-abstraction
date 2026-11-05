# Terraform Platform Abstraction

[![CI](https://github.com/bhavyakeniya/terraform-platform-abstraction/actions/workflows/terraform.yml/badge.svg?branch=main&event=push)](https://github.com/bhavyakeniya/terraform-platform-abstraction/actions/workflows/terraform.yml)

A team that needs AWS resources writes one JSON file — which S3 buckets it
needs, and whether each one is public or private — and gets a validated,
tested change, without touching Terraform or designing any CI. The platform
guarantees every team's resources look the same: same naming, same
encryption, same least-privilege IAM role, whether it's the first team or the
three-hundredth.

Each team owns a separate repository with one JSON declaration per environment
(`dev`, `staging`, `prod`). A platform-owned reusable workflow does the rest.

CI runs and passes on GitHub for all four repositories below. AWS deployment
is deliberately disabled for now, so automatic runs validate without
credentials and plan/apply stay behind a manual dispatch. No real team data
exists and nothing has been deployed to AWS.

## Repositories

| Repository | Role |
| --- | --- |
| [terraform-platform-abstraction](https://github.com/bhavyakeniya/terraform-platform-abstraction) | This repository: the module, generic root, helper, CI and docs |
| [team-payments](https://github.com/bhavyakeniya/team-payments) | Example consuming team — JSON declarations only |
| [team-customers](https://github.com/bhavyakeniya/team-customers) | Example consuming team — JSON declarations only |
| [team-accounting](https://github.com/bhavyakeniya/team-accounting) | Example consuming team — JSON declarations only |

A team repository has no Terraform, no provider or backend configuration, and
no pipeline logic — just JSON and a thin workflow that calls this platform's
reusable workflow at a pinned commit. Their CI checks out this repository and
runs their declarations through the real module under `mock_provider`,
proving the platform works across repository boundaries, not just inside
this one.

## Setup

```bash
uv sync --locked
```

Pinned versions: Python 3.13.15 (`.python-version`), Terraform 1.17.1
(`.terraform-version`, resolved AWS provider 6.71.0), uv 0.12.3+. Terraform
itself is not installed by `uv sync`; fetch the pinned release directly if
you don't already have it:

```bash
mkdir -p .local/bin
curl -fsSL -o /tmp/terraform.zip \
  "https://releases.hashicorp.com/terraform/$(cat .terraform-version)/terraform_$(cat .terraform-version)_$(uname -s | tr A-Z a-z)_$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/').zip"
unzip -o -q /tmp/terraform.zip -d .local/bin && chmod +x .local/bin/terraform
```

`make check` finds `.local/bin/terraform` automatically if present, falling
back to `terraform` on `PATH` otherwise — the same scheme CI uses.

## The declaration a team writes

Generate a separate team project from the platform checkout:

```bash
uv run python -m scripts.onboard --team-id logistics \
  --owner logistics@example.invalid --destination ../logistics
```

The scaffold includes dev/staging/prod, expectations, and a thin
shared-workflow caller. Edit `environments/dev/resources.json`:

```json
{
  "schema_version": 2,
  "environment": "dev",
  "owner": "logistics@example.invalid",
  "buckets": {
    "reports": {"visibility": "private"},
    "assets": {"visibility": "public"}
  }
}
```

That's the whole interface: no Terraform, no backend choices, no provider
settings, no deployment scripts. See [using the platform](docs/consumers.md)
for everyday changes and [the delivery guide](docs/environments-and-delivery.md)
for activation.

## Running the checks locally

```bash
make check
```

One command. No AWS account, no credentials, no LocalStack. The only network
access is installing pinned dependencies and Terraform's provider download.
It runs the full test suite, the security scanners (Trivy + Checkov), and
every example declaration through the real module.

The full command reference and what each one checks:
[docs/team-repo-tests.md](docs/team-repo-tests.md#every-make-target).
Exact pass/fail counts: [docs/verification.md](docs/verification.md).

## Architecture

```
team repo:  environments/<env>/resources.json      <- the only thing a team owns
                      |
platform:   consumer_platform.py + environments.py <- validate, derive context, render
                      |
                      v
            stacks/team/            <- generic root, one module call per run
                      |
                      v
            modules/team-resources/ <- one team's buckets + one IAM role
```

**One module, one root, no per-team code.** Going from 1 team to 300+ means
running the same root again with different rendered variables. The module, the
root and the workflow never change.

`scripts/consumer_matrix.py` decides what runs: an edit under
`environments/<env>/` selects exactly that environment, a shared-file edit
selects all of them, and a removed environment fails closed unless an approved
retirement receipt accompanies it. The 300-team case in
`tests/test_environments.py` generates 300 distinct backends and 900 CI bindings
from one registry with no platform change.

### Naming

| Thing | Format | Example |
| --- | --- | --- |
| Bucket | `sumup--<env>--<team>--<key>` | `sumup--dev--payments--reports` |
| Workload role | `<env>--<team>--s3` | `dev--payments--s3` |
| State object | `workloads/<account>/<env>/teams/<team>/terraform.tfstate` | |
| Backend bucket + lock table | `sumup--tfstate--<account>--<team>` | |

`--` is an unambiguous separator because no identifier may contain it, so two
different `(team, key)` splits can never produce the same name. Only buckets
carry the `sumup--` prefix — S3 is a global namespace, IAM is not. Full
reasoning, reserved-name rules, and length limits:
[modules/team-resources/README.md](modules/team-resources/README.md) and
[docs/assumptions.md](docs/assumptions.md).

### State isolation

One bucket and one DynamoDB lock table per **team/account**, shared only across
that team's environments in that account.

| Property | Value |
| --- | --- |
| Encryption / versioning / private access | enabled on the backend bucket |
| Locking | DynamoDB, one row per environment state |
| Per-run isolation | fresh `TF_DATA_DIR`; GitHub never cancels in-flight runs |
| CI identity | scoped OIDC role and workload permissions boundary, provisioned separately |

DynamoDB locking is deprecated upstream and retained here deliberately; a CLI
upgrade needs backend tests and a migration review.

### Security model

Every bucket, public or private: BucketOwnerEnforced ownership, SSE-S3
encryption, versioning, TLS-only access, `force_destroy = false`, platform tags.

| Setting | Private | Public |
| --- | --- | --- |
| `block_public_acls` / `ignore_public_acls` | `true` | `true` |
| `block_public_policy` / `restrict_public_buckets` | `true` | `false` |
| Anonymous access | none | `s3:GetObject` on current objects only |

The one workload role per team can only reach that team's own buckets and
objects, nothing else, and loses that access entirely if the resource's AWS
account ever differs from the team's registered account. Every statement and
its test: [modules/team-resources/README.md](modules/team-resources/README.md).

### CI

| Workflow | Trigger | Jobs |
| --- | --- | --- |
| `terraform.yml` (this repo) | PR, push, dispatch | `security` (Trivy/Checkov), `checks` (full local suite), `fixture-smoke` (always, no AWS) |
| `team-infrastructure.yml` (reusable) | called by each team repo | `check` (credential-free, automatic), `deploy` (manual dispatch only), `localstack` (opt-in) |

No job in `terraform.yml` holds cloud credentials, runs `apply`, or takes
more than `contents: read`. `team-infrastructure.yml`'s `deploy` job is
different by design — it assumes a short-lived OIDC role and runs `apply` —
but only on a manual dispatch, never automatically. Full trigger-by-trigger
behavior: [the delivery guide](docs/environments-and-delivery.md#cicd-what-actually-happens).
What all of this proves versus what it does not: [docs/verification.md](docs/verification.md).

## Current status

Published and CI-verified: the module, generic root, declaration contract,
consumer change-selection pipeline, tests, environment catalogs, backend and
CI bootstrap modules, the shared plan/apply workflow, and the LocalStack
harness. All four repositories run their checks on GitHub.

Not verified: anything requiring AWS. No account is enrolled, OIDC trust and
protected environments are not configured, and no plan or apply has run
against real infrastructure. The three teams are demonstrations, AWS
deployment remains disabled, and [docs/verification.md](docs/verification.md)
separates what is proven from what is not.

## Documentation

**Using the platform**
- [docs/consumers.md](docs/consumers.md) — onboard a team, make everyday changes, offboarding options
- [docs/environments-and-delivery.md](docs/environments-and-delivery.md) — onboarding, environments, state, CI triggers, migration
- [docs/team-repo-tests.md](docs/team-repo-tests.md) — every check, every `make` target, how to run them
- [docs/localstack.md](docs/localstack.md) — running the real-provider emulator suite

**Understanding the design**
- [modules/team-resources/README.md](modules/team-resources/README.md) — inputs/outputs, naming formulas, full security contract
- [docs/assumptions.md](docs/assumptions.md) — design justifications, limitations, open questions
- [docs/verification.md](docs/verification.md) — current evidence: what's proven, what's blocked, why
- [docs/verification-history.md](docs/verification-history.md) — dated run records and narrative evidence

**Operating it**
- [docs/operations.md](docs/operations.md) — plan/apply procedure, state recovery, drain-before-revoke
- [docs/offboarding-procedures.md](docs/offboarding-procedures.md) — retain/destroy commands
- [docs/security-scanning.md](docs/security-scanning.md) — Trivy/Checkov gates, pinned tools, exceptions
