# Terraform Platform Abstraction

A Terraform platform abstraction for a fintech infrastructure-platform team:
one module provisions one team's S3 buckets and IAM role, one generic root
runs that module against an isolated backend, and a small Python helper
plus a GitHub Actions workflow turn a team's one-file declaration into a
validated, tested change — without the team ever touching Terraform.

Each team owns a separate repository with one JSON declaration per environment
(`dev`, `staging`, `prod`). A platform-owned reusable workflow does the rest.

CI runs and passes on GitHub for all four repositories. AWS deployment is
deliberately disabled in the environment catalogs, so automatic runs validate
without credentials and plan/apply stay behind a manual dispatch. No real team
data exists and nothing has been deployed to AWS.
Start with the [environment and delivery guide](docs/environments-and-delivery.md).

## Repositories

| Repository | Role |
| --- | --- |
| [terraform-platform-abstraction](https://github.com/bhavyakeniya/terraform-platform-abstraction) | This repository: the module, generic root, helper, CI and docs |
| [team-payments](https://github.com/bhavyakeniya/team-payments) | Example consuming team — JSON declarations only |
| [team-customers](https://github.com/bhavyakeniya/team-customers) | Example consuming team — JSON declarations only |
| [team-accounting](https://github.com/bhavyakeniya/team-accounting) | Example consuming team — JSON declarations only |

Each team repository holds 11 files: six JSON declarations and expectations, a
`team.json`, a README, a `.gitignore`, a two-target Makefile, and a thin
workflow that calls this platform's reusable workflow at a pinned commit. No
Terraform, no provider or backend configuration, no pipeline logic. Their CI checks out this
repository, renders their declarations, and runs them through the real module
under `mock_provider` — proving the abstraction works across repository
boundaries, not just inside this one. See
[docs/team-repo-tests.md](docs/team-repo-tests.md).

## Where to find things

| Document | Read it for |
| --- | --- |
| This file | Setup, architecture, security model, CI/CD, walkthrough outline |
| [docs/environments-and-delivery.md](docs/environments-and-delivery.md) | Current onboarding, environments, S3/DynamoDB state, shared plan/apply, migration and retirement |
| [docs/security-scanning.md](docs/security-scanning.md) | Blocking Trivy/Checkov gates, pinned tools, explicit exceptions and negative tests |
| [docs/assumptions.md](docs/assumptions.md) | Assumptions, design justifications, limitations, and questions before deployment |
| [docs/consumers.md](docs/consumers.md) | Three independent consumer projects, local commands, shared CI, changes, and emulator evidence |
| [docs/verification.md](docs/verification.md) | Exact test counts and results, requirement-by-requirement evidence, what's proven vs. blocked and why |
| [modules/team-resources/README.md](modules/team-resources/README.md) | The module's inputs/outputs, naming formulas, full security contract, how to test it standalone |
| [docs/team-lifecycle.md](docs/team-lifecycle.md) | The full onboarding walkthrough and every offboarding option (not just deletion) |
| [docs/offboarding-procedures.md](docs/offboarding-procedures.md) | Manual retain/destroy procedures; conceptual archive, transfer, and export options |
| [docs/operations.md](docs/operations.md) | Operator-facing: the real plan/apply procedure, backend/public-control prerequisites, drain-before-revoke, state recovery |
| [docs/localstack.md](docs/localstack.md) | Running the isolated consumer integration and reading its evidence |
| [docs/team-repo-tests.md](docs/team-repo-tests.md) | How the three team repositories are checked, and how to run those checks |

## Setup

```bash
uv sync --locked
```

Pinned versions: Python 3.13.15 (`.python-version`), Terraform 1.17.1
(`.terraform-version`, resolved AWS provider 6.71.0 — see the committed
`.terraform.lock.hcl` files), uv 0.12.3+. Terraform itself is not installed
by `uv sync`; fetch the pinned release directly if you don't already have
it:

```bash
mkdir -p .local/bin
curl -fsSL -o /tmp/terraform.zip \
  "https://releases.hashicorp.com/terraform/$(cat .terraform-version)/terraform_$(cat .terraform-version)_$(uname -s | tr A-Z a-z)_$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/').zip"
unzip -o -q /tmp/terraform.zip -d .local/bin && chmod +x .local/bin/terraform
```

`make check` finds `.local/bin/terraform` automatically if present, falling
back to `terraform` on `PATH` otherwise (the exact scheme CI uses — see
`.github/workflows/terraform.yml`).

## The declaration a team writes

Generate a separate team project from the platform checkout:

```bash
uv run python -m scripts.onboard --team-id logistics \
  --owner logistics@example.invalid --destination ../logistics
```

The scaffold includes dev/staging/prod, expectations, local commands and a thin
shared-workflow caller template. Edit `environments/dev/resources.json`:

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

Update that environment's `expectations.json` to match its business requirements
and explicitly permitted public keys. Teams supply no Terraform, backend choices,
provider settings or deployment scripts. See [the delivery guide](docs/environments-and-delivery.md)
for activation and the small platform-controlled registration. `examples/minimal`
and `examples/mixed` remain as declaration fixtures for the fixture-smoke and
security-scan paths.

## Running the checks locally

Full checks require Trivy 0.73.0. Checkov and its dependencies are installed
automatically into an isolated locked environment. See
[security scanning](docs/security-scanning.md) for setup and scope exceptions.

```bash
make check
```

Runs, in Makefile order: the Trivy/Checkov security gates and their scanner
canaries, `terraform fmt -check`, the full Python test suite, the module's
native `terraform test` suites (contract + security), the root's
team-independent generic checks (run once, not per team), the backend and CI
module contracts, both committed examples through the real
render→mocked-root-test pipeline, the fixture-smoke path, and all nine consumer
declarations. Everything is credential-free — no AWS account, no
LocalStack, and nothing reaches the network beyond installing pinned
dependencies (`uv sync`, the scanner environment) and Terraform's own provider
download. Exact current case counts live in one place —
[docs/verification.md](docs/verification.md) — rather than duplicated
here where they'd drift out of sync; `make check`'s own output is always
the immediate source of truth. Individual pieces:

```bash
make fmt-check         # terraform fmt -check -recursive
make test-python       # uv run pytest tests/ -q
make security          # independent Trivy + locked Checkov rules
make test-security     # real negative scanner canaries
make test-module       # module contract.tftest.hcl + security.tftest.hcl
make test-root-generic # root's team-independent checks (output projection, wrong-account) -- run once
make test-backend      # team-backend and team-ci module contracts
make check-examples    # render each example, run its declaration-specific check through the real root
make fixture-smoke     # local mirror of the CI fixture-smoke job
make test-consumers    # the three consumer mirrors (also part of `make check`)
make test-localstack   # opt-in real-provider emulator lifecycle; free Hobby token required
```

Routine Terraform initialization uses `-lockfile=readonly` in the Make targets
and Python helper, including the paths invoked by CI. Tests use the committed
provider selections; dependency upgrades are separate reviewed changes across
the Python lock file and all six committed Terraform lock files. Module and root
inputs have descriptions and reject top-level nulls, except
`permissions_boundary_arn`, which defaults to `null` so the module stays usable
without the platform's CI-provisioned boundary.
The security suite checks the complete attached IAM policy, and each rendered
declaration check verifies its output bucket count and keys.

CLI commands (`uv run python scripts/team_platform.py <command>`):
`validate --file`, `render --file --team-id --config --out`,
`smoke-check --fixtures-dir --config`. `smoke-check` renders ephemeral
fixtures and runs them through the real root under `mock_provider`; it backs
the always-run fixture-smoke CI job and is also what `consumer_platform`
calls per environment.

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
different `(team, key)` splits can never produce the same name.

**Only buckets carry the `sumup--` prefix.** S3 is a single global namespace, so
the prefix reduces the chance of colliding with an unrelated account. IAM is
account-scoped, so a role gains nothing from a company prefix; roles are grouped
by their IAM path instead (`/team-platform/runtime/<env>/<team>/`), which is what
an SCP or permissions boundary matches on. The role name still repeats
environment and team because
[AWS requires friendly names to be unique within an account](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_identifiers.html)
and a path does not make two identically named roles distinct.

- **No account ID in workload bucket names.** It stays in state keys, account
  guards and IAM resource-owner checks. Names are unique within the configured
  environment/team/key set, not across S3's global namespace — a collision
  fails rather than importing or renaming anything.
- **Max generated length 51 characters**, 12 below S3's limit. Spare characters
  do not make a deployed bucket renameable; that is a reviewed migration.
- **SSE-S3, not customer-managed KMS.** SSE-KMS reads require signed requests,
  which would break the required anonymous public-read case. A deliberate v1
  scope choice — see [docs/assumptions.md](docs/assumptions.md).

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

The one workload role per team gets exactly four inline statements:

1. **Allow** list/locate on its own buckets
2. **Allow** get/put/delete on its own objects
3. **Deny** everything else, by `NotResource`
4. **Deny** even those allowed actions if the resource's account differs from
   the team's registered account (`s3:ResourceAccount` — a readable bucket name
   is not ownership proof)

Full contract and every test: [modules/team-resources/README.md](modules/team-resources/README.md).

### CI

| Workflow | Trigger | Jobs |
| --- | --- | --- |
| `terraform.yml` (this repo) | PR, push, dispatch | `security` (Trivy/Checkov), `checks` (full local suite), `fixture-smoke` (always, no AWS) |
| `team-infrastructure.yml` (reusable) | called by each team repo | `check` (credential-free, automatic), `deploy` (manual dispatch only), `localstack` (opt-in) |

No job in **`terraform.yml`** — this repository's own validation workflow —
holds cloud credentials, runs `apply`, or takes more than `contents: read`.
`team-infrastructure.yml` is different by design: it also lives here, and its
`deploy` job requests `id-token: write`, assumes a short-lived OIDC role and
runs `apply`. That job never fires automatically; it requires a manual dispatch
from the default branch. What this proves versus what it does not:
[docs/verification.md](docs/verification.md).

## Scope boundaries

**Published and CI-verified:** the module, generic root, declaration contract,
consumer change-selection pipeline, tests, environment catalogs, backend and CI
bootstrap modules, the shared plan/apply workflow, and the LocalStack harness.
All four repositories run their checks on GitHub.

**Not verified:** anything requiring AWS. No account is enrolled, OIDC trust and
protected environments are not configured, and no plan or apply has run against
real infrastructure. The three teams are demonstrations, not production
onboarding. `docs/verification.md` separates what is proven from what is not.

## Second pass

Onboarding a real team, enabling authorized plan/review/apply, and
real-provider acceptance are deliberately deferred — see
[docs/operations.md](docs/operations.md) and
[docs/verification.md](docs/verification.md). Nothing in this release implies
that authorization.
