# Terraform Platform Abstraction

[![CI](https://github.com/bhavyakeniya/terraform-platform-abstraction/actions/workflows/terraform.yml/badge.svg?branch=main&event=push)](https://github.com/bhavyakeniya/terraform-platform-abstraction/actions/workflows/terraform.yml)

Teams declare their S3 buckets in JSON. Shared Terraform applies consistent
naming, encryption, and access rules, with separate state for each team and
environment.

Each team has its own repository with configurations for dev, staging, and
prod. A platform-owned reusable workflow validates and deploys them.

## Repositories

| Repository | Role |
| --- | --- |
| [terraform-platform-abstraction](https://github.com/bhavyakeniya/terraform-platform-abstraction) | This repository: the module, generic root, helper, CI and docs |
| [team-payments](https://github.com/bhavyakeniya/team-payments) | Example consuming team |
| [team-customers](https://github.com/bhavyakeniya/team-customers) | Example consuming team |
| [team-accounting](https://github.com/bhavyakeniya/team-accounting) | Example consuming team |

Teams maintain JSON and a small workflow caller pinned to a platform commit.
The shared Terraform and pipeline implementation stay in this repository.

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

Before running the full checks, install **Trivy 0.73.0** on `PATH`; see
[security scanning setup](docs/security-scanning.md#run-locally).
Checkov and its dependencies are installed automatically in a locked environment.

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

Update `environments/dev/expectations.json` to match this example too. The
scaffold initially requires a `data` bucket and permits no public buckets:

```json
{
  "required_buckets": ["reports", "assets"],
  "allowed_public_buckets": ["assets"]
}
```

Run `make check` from the generated `../logistics` project to validate all its
environments. See [using the platform](docs/consumers.md) for everyday changes
and [the delivery guide](docs/environments-and-delivery.md) for CI activation.

## Running the checks locally

From the platform checkout:

```bash
make check
```

This runs the test suite, Trivy and Checkov, and every example declaration
through the real module. It needs no AWS account, credentials, or LocalStack;
network access is used to install pinned dependencies and the AWS provider.

The full command reference and what each one checks:
[docs/team-repo-tests.md](docs/team-repo-tests.md#every-make-target).
Exact pass/fail counts: [docs/verification.md](docs/verification.md).

## Architecture

```
team repo:  environments/<env>/                    <- declaration + expectations
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

Team workflows check pull requests and pushes without AWS credentials.
Deployment requires AWS enrollment and a manual dispatch from the default
branch. Each apply creates a fresh plan inside the job; see the
[delivery guide](docs/environments-and-delivery.md#cicd-what-actually-happens)
for the full trigger and approval behavior.

## Current status

- **GitHub CI:** checks run in all four public repositories.
- **LocalStack:** integration passed against earlier source snapshots; current
  source has not been reverified in the emulator.
- **AWS:** deployment is disabled. No real team is enrolled and AWS/OIDC
  acceptance has not run.

See [verification.md](docs/verification.md) for recorded results and outstanding
checks.

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
