# Terraform Platform Abstraction

A Terraform platform abstraction for a fintech infrastructure-platform team:
one module provisions one team's S3 buckets and IAM role, one generic root
runs that module against an isolated backend, and a small Python helper
plus a GitHub Actions workflow turn a team's one-file declaration into a
validated, tested change — without the team ever touching Terraform.

Teams now use independent projects with `environments/dev`, `staging` and `prod`.
Each environment declares its own JSON config. A platform-owned reusable workflow
runs checks and plans; an explicit manual dispatch can create and apply a fresh
saved plan. Each team/account gets a private, versioned, encrypted S3 backend and
DynamoDB lock table, provisioned by the platform operator.

Everything remains local: AWS deployment is disabled in the fixture catalogs,
workflow activation requires a real published platform SHA, and live GitHub/AWS
acceptance is pending. No real team data or AWS deployment has been created.
Start with [environment and delivery guide](docs/environments-and-delivery.md).

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

Runs, in order: `terraform fmt -check`, the full Python test suite, the
module's native `terraform test` suites (contract + security), backend/CI/bootstrap
contracts, all nine consumer declarations, and the root's
team-independent generic checks (run once, not per team), both committed
examples through the real render→mocked-root-test pipeline, and the
fixture-smoke path. Everything is credential-free — no AWS account, no
LocalStack, nothing reaches the network except Terraform's own provider
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
make check-examples    # render each example, run its declaration-specific check through the real root
make fixture-smoke     # local mirror of the CI fixture-smoke job
make test-consumers    # opt-in checks for the three portable consumer examples
make test-localstack   # opt-in real-provider emulator lifecycle; free Hobby token required
```

Routine Terraform initialization uses `-lockfile=readonly` in the Make targets
and Python helper, including the paths invoked by CI. Tests use the committed
provider selections; dependency upgrades are separate reviewed changes to both
lock files. Module/root inputs have descriptions and reject top-level nulls.
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
consumer/environments/<env>/resources.json  <- team-owned declaration
        |
        v
consumer_platform.py / environments.py     <- strict validation and platform context
  validate -> derive_context -> render_inputs -> inputs.tfvars.json / backend.hcl.json
        |
        v
stacks/team/  (generic root, one module invocation per run)
        |
        v
modules/team-resources/  (one team's buckets + one IAM role)
```

**One module, one root, no per-team code.** `modules/team-resources`
provisions exactly one team's resources; `stacks/team` configures the
provider and invokes that module once. Scaling from 1 to 300+ teams means
running the same root repeatedly with different rendered variables — never
editing the module, the root, or the workflow. `scripts/team_platform.py`'s
`scripts/consumer_matrix.py` proves this on the consumer side by classifying
Git changes within a team repository: an edit under `environments/<env>/`
selects exactly that environment, a shared-file edit selects all of them, and
removing an environment fails closed without a signed retirement receipt
(`tests/test_environments.py`). The same file's 300-team case generates 300
distinct backends and 900 CI bindings from one registry with no platform code
change.

**State isolation.** Each team/account has its own bucket and DynamoDB table,
both named `sumup--tfstate--<account-id>--<team-id>`. State objects use
`workloads/<account>/<environment>/teams/<team-id>/terraform.tfstate`.
The backend module enables encryption, versioning, private access and deletion
safeguards. Every live invocation has a fresh `TF_DATA_DIR`; DynamoDB handles
locking and GitHub does not cancel in-flight deployments. Scoped CI identities
and mandatory workload boundaries are provisioned separately from workloads.
DynamoDB locking is deprecated upstream, retained here as explicitly requested;
CLI upgrades require backend tests and migration review.

**Naming.** `sumup--<environment>--<team-id>--<bucket-key>` for
buckets, `tfp--<environment>--<team-id>--s3` for the role. The double-hyphen
separator is unambiguous because no identifier component may contain `--`
itself (enforced by the identifier regex), so two different `(team_id,
bucket_key)` splits can never collide into the same string within an environment.
For example: `sumup--dev--payments--reports`.

- **Account IDs are absent from workload bucket names.** They remain in state keys,
  account guards, and IAM resource-owner checks. Names are unique within the
  configured environment/team/key set, not guaranteed globally: the same
  identifiers in another account or region would request the same name, and
  an unrelated AWS account may already own it. An unavailable name fails; do
  not silently import it or invent a suffix. This is a deliberate limitation
  of the single-target scope.
- **Maximum generated length is 51 characters**, leaving 12 below S3's
  63-character limit. Changing names after deployment requires a reviewed
  migration; spare characters do not make an existing bucket renameable.
- **SSE-S3 (not customer-managed KMS) is the deliberate v1 default**,
  because SSE-KMS object reads require signed requests and would break the
  assignment's anonymous-public-read requirement. Private production data
  is a separate scope decision gated on asking about classification/key
  ownership first. See Section 3.4, "Encryption decision."

**Security model.** Every bucket: BucketOwnerEnforced ownership, SSE-S3
encryption, versioning, TLS-only access (anonymous HTTP denied
unconditionally), `force_destroy = false`, platform tags. Private buckets
keep all four S3 public-access-block flags `true`; public buckets relax
only `block_public_policy`/`restrict_public_buckets` and grant exactly
anonymous `s3:GetObject` on current objects — never listing, writing,
deleting, or historical versions. The one workload IAM role per team gets
an exact four-statement inline policy: allow list/locate on its own
buckets, allow get/put/delete on its own objects, deny everything else by
`NotResource`, and deny even its own allowed actions if the resource's AWS
account ever differs from the team's registered account (`s3:ResourceAccount`
condition — readable names are not ownership proof). Full detail and every
test: `modules/team-resources/README.md`.

**Platform CI.** `.github/workflows/terraform.yml` runs on PR, push, and manual
dispatch with three jobs: `security` (Trivy/Checkov gates), `checks` (the full
local suite), and `fixture-smoke`, which runs unconditionally on every event to
exercise the render-and-mocked-root path independently of any real team. Per-team
change selection is not a platform-repository concern — teams own separate
repositories, so that selection happens in
`.github/workflows/team-infrastructure.yml` via `scripts/consumer_matrix.py`.
The platform workflow's live-runner result remains unverified until publication.
No job holds cloud credentials,
runs `apply`, or writes with more than `contents: read`. See
`docs/verification.md` for what's proven by this (readiness) versus what
it is explicitly not (an AWS-authorization or full-scale-correctness
proof).

**Team delivery.** `.github/workflows/team-infrastructure.yml` supplies environment
checks, post-merge plans and manually dispatched fresh-plan/apply. It uses scoped
OIDC identities and non-cancelling concurrency. See the [delivery guide](docs/environments-and-delivery.md).

## Scope boundaries

This release delivers the module, generic root, declaration contract,
consumer change-selection pipeline, and tests. It explicitly excludes: a real
onboarded team, actual AWS
deployment and live GitHub verification. The later extension adds independent
local team projects, environment catalogs, backend/CI bootstrap modules and a
shared manual plan/apply workflow, plus an isolated LocalStack harness. OIDC and
deployment definitions are implemented; activation remains explicitly disabled.
`docs/verification.md` separates local evidence from AWS behavior and
publication prerequisites.

## Second pass

Onboarding a real team, enabling authorized plan/review/apply, and
real-provider acceptance are deliberately deferred — see
[docs/operations.md](docs/operations.md) and
[docs/verification.md](docs/verification.md). Nothing in this release implies
that authorization.
