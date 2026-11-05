# Verification

Honest status: **the current source is verified by local checks and by live
credential-free GitHub Actions runs across all four repositories. Emulator
integration passed, but against a 2026-11-04 source snapshot that the tree has
since moved past. Real AWS verification remains blocked.** Results below
distinguish credential-free Python/native mocks, executed GitHub Actions runs,
and real-provider LocalStack lifecycle tests, and say which source each was run
against. None of them is a real AWS deployment.

The later user-requested consumer extension implements a repeatable Python
runner with an owned ephemeral Docker container (no separate Compose service).
See the [runbook](localstack.md) and [consumer usage](consumers.md). Free-tier policy readback still does not establish
IAM enforcement. Historical manual evidence is retained separately below.

## Root version and independent scanner hardening — 5 November 2026

Both deployed roots now constrain Terraform to 1.17.x (`~> 1.17.0`) and AWS to
6.x (`~> 6.0`). Runtime remains exactly 1.17.1, provider locks remain 6.71.0,
and existing lock-file hashes are unchanged. Module compatibility ranges remain
broad. No AWS/state operation or provider upgrade was performed.

- Full local suite: **PASS**, 205 Python tests, native Terraform suites and all
  nine consumer declarations. Scanner canaries run separately as a required
  `make check` prerequisite: **7/7 PASS**, including two real CLI negative cases.
- Latest security scope: every production module/root plus the concrete
  public/private fixture, in a source-only temporary workspace with synthetic
  inputs for the actual roots. **Trivy 0.73.0: 161 successful evaluations, no
  unexcepted failures. Checkov 3.3.10: 141 passed, 0 failed, 27 resource-scoped
  exception instances, 0 parsing errors.** See
  [security-scan-results.json](security-scan-results.json).
- A private-access regression fails both scanners; an administrator IAM policy
  inserted directly into the real workload-root source fails Checkov and the
  CLI gate. Trivy's embedded rules do not flag that standalone IAM policy.
- Homebrew Checkov with the same package version omitted graph checks. The
  dedicated `tools/security/uv.lock` now locks its full dependency stack;
  `.venv/bin/checkov` from that environment is always used. Trivy uses a fresh
  cache and pinned embedded rules. CI verifies the pinned Linux binary checksum.
- Equivalent keyed bucket references allow Checkov to link the existing
  versioning/private-access controls without suppressing those checks. Resource
  keys/addresses and values are preserved; native regression checks pass.
- Both deployment roots and the scanner composition passed backendless read-only
  initialization and `terraform validate`; formatting and workflow actionlint pass.
- Security is blocking on both platform and reusable consumer CI paths, and has
  now executed on GitHub-hosted runners as well as locally. It is not an AWS
  authorization proof. Accepted scope exceptions and upgrade steps are documented in
  [security-scanning.md](security-scanning.md).

The prior LocalStack snapshots below predate metadata/scanner/key-reference
hardening. They remain historical emulator evidence; this change does not claim
to repeat an AWS deployment or an emulator lifecycle. Application dependencies
and existing provider selections were not upgraded.

## Environment and shared-delivery extension — 5 November 2026

This section supersedes the historical results below for the current consumer,
backend and delivery path. GitHub workflows have since executed on real
runners (see "Live GitHub Actions runs" below). No real AWS deployment is
claimed: AWS catalogs still contain fixture accounts with deployment disabled.

| Check | Current evidence |
| --- | --- |
| Full Python suite | PASS — 205 tests, including 44 environment/onboarding/delivery contracts |
| Workload native contract/security | PASS — 18 contract + 17 security runs, including positive boundary attachment and rejecting another team's boundary |
| Workload root generic | PASS — 2 runs |
| Backend module native | PASS — 3 runs: private/versioned/encrypted/locked contract, reserved-name rejection, maximum 46-character name |
| CI identity native | PASS — 5 runs: exact OIDC trust, scoped state/locks, protected boundary, private recovery upload and whole-policy equality |
| Bootstrap root native | PASS — 2 runs, plus validate: team/backend cardinality and rejection of duplicate team/environment CI bindings |
| Declaration/root checks | PASS — both committed examples, fixture smoke and all nine consumer environment declarations |
| Workflow syntax | PASS — official actionlint 1.7.12 against platform workflows and a generated pinned caller; the workflows have additionally been executed on GitHub (below) |
| 300-team configuration scale | PASS — 300 distinct backend names and 900 unique CI bindings generated from one registry; AWS capacity remains unverified |
| Full free-Hobby integration (same 2026-11-04 snapshot) | PASS **at that snapshot** — all nine team/environment configurations, 27 workload buckets, actual S3/DynamoDB backends, extended lifecycle, lock contention and cleanup. Its recorded source hashes have also diverged from the current tree (17 of 27 files); re-run `make test-localstack` to re-establish it against current source. |
| Backend repeat against snapshot `db330b55` (2026-11-04) | PASS **at that snapshot** — payments/dev, staging and prod; actual state versions/encryption, contention, reapply and cleanup. Source hashes matched the tree as it stood then; **14 of the 27 recorded files have since changed** (workload naming, bucket configuration, backend source), so this is historical evidence. Only a fresh run would establish current-source integration. |
| AWS/OIDC acceptance | NOT RUN — the repositories are published and their CI runs, but no real AWS account, registered identity, OIDC trust or protected environment exists |

The full emulator run is recorded in
[environment-test-results.json](environment-test-results.json), run
`15d94dbd81fd40daa1786b8bacfa4e06`, started 2026-11-04 22:39 UTC, about 20 minutes.
All states coexist before lifecycle tests; holding the first state's DynamoDB
lock blocks Terraform for that state while other teams/environments can plan.
Workload resources, state versions, backend fixture tables/buckets and the
run-owned container are cleaned. The pre-existing emulator is preserved.

The final-source backend repeat is
[environment-backend-repeat.json](environment-backend-repeat.json), run
`db330b55e93347c0b5f42ba2b2ec0795`. It explicitly records `mode=baseline-only`
and `lifecycle=NOT_RUN`; it supplements the full run without claiming to repeat
its extended mutations. This repeat covers the final backend precondition and
source snapshot after CI-policy/region hardening. A subsequent CI-only action-name
audit added the four non-GetBucket read permissions, scoped role update/tag reads,
and removed nonexistent delete action names; those permissions are covered by the final native whole-policy test.
CI-role effective authorization
is **not** exercised by Hobby; native tests verify its policy construction.

Plans, provider diagnostics, state, credentials and tokens are not published as
GitHub artifacts. Emergency state recovery has simulated success/failure tests;
its real AWS upload authorization and failure recovery still require sandbox
acceptance. Hobby policy readback/object operations do not establish IAM,
anonymous-public/private or TLS enforcement. The shared manual apply creates a
fresh plan; it does not provide a human approval pause after that exact plan.
See [delivery](environments-and-delivery.md) for activation, migration and quotas.

## Live GitHub Actions runs — 5 November 2026

All four repositories are public under `bhavyakeniya` and their workflows have
executed on GitHub-hosted runners. These are real runs, not structural checks.

| Repository | Workflow | Result |
| --- | --- | --- |
| [terraform-platform-abstraction](https://github.com/bhavyakeniya/terraform-platform-abstraction) | `terraform.yml` | **PASS** — `security`, `checks`, `fixture-smoke` |
| [team-payments](https://github.com/bhavyakeniya/team-payments) | `infrastructure.yml` | **PASS** — `check`; `deploy`/`localstack` skipped |
| [team-customers](https://github.com/bhavyakeniya/team-customers) | `infrastructure.yml` | **PASS** — `check`; `deploy`/`localstack` skipped |
| [team-accounting](https://github.com/bhavyakeniya/team-accounting) | `infrastructure.yml` | **PASS** — `check`; `deploy`/`localstack` skipped |

Each team run checks out the platform at its pinned SHA, renders that team's
declarations and validates all three environments through the real module under
`mock_provider`. Logged output per environment, for example in team-payments:

```
payments/dev: declaration, expectations and mocked root PASS
payments/prod: declaration, expectations and mocked root PASS
payments/staging: declaration, expectations and mocked root PASS
```

This is the strongest evidence in this document for the abstraction working
across repository boundaries: a team repository containing only JSON produces a
validated plan using Terraform it does not own.

**A real defect was found only by running on GitHub.** The first platform run
failed. Every `.terraform.lock.hcl` carried a single `h1:` hash for
`darwin_arm64`, generated on the development workstation. On `linux_amd64`
runners, provider verification failed under `-lockfile=readonly`. `make check`
passed locally on every attempt and always would have; no amount of local
testing on one architecture could surface it. Fixed by recording both platforms
in all six tracked lock files:

```bash
terraform providers lock -platform=linux_amd64 -platform=darwin_arm64
```

Subsequent runs pass. This is the concrete reason "it passes locally" is
reported separately from "it passes in CI" throughout this document.

### What these runs do not establish

- **No AWS authorization.** No job holds cloud credentials. `deploy` is skipped
  on automatic runs and, when dispatched manually, stops at the platform
  registration guard because every environment catalog has
  `deployment_enabled: false` with a fixture account.
- **No deployment protections.** Branch protection, required reviewers,
  protected environments and OIDC trust are not configured (G-GH).
- **Default-branch pushes only so far.** Pull-request runs use the same
  credential-free path but have not been exercised with a real PR.

## Historical first-pass and earlier consumer results

## Exact revisions (at last local run)

| Tool | Version | Source |
| --- | --- | --- |
| Python | 3.13.15 | `.python-version`, pinned via `uv` |
| uv | 0.12.3 | Homebrew |
| Terraform | 1.17.1 | `.terraform-version`; fetched directly from `releases.hashicorp.com` (not a third-party action) |
| AWS provider | 6.71.0 | Resolved from `>= 5.0, < 7.0` by `terraform init`; recorded in both `.terraform.lock.hcl` files |
| pytest | 8.4.2 | `uv.lock` |
| jsonschema | 4.26.0 | `uv.lock` |
| pyyaml | 6.0.3 | `uv.lock` (test-only: workflow YAML structural checks) |

Results below are reproducible by running the commands shown. Every commit on
`main` is additionally verified by the GitHub Actions run for that exact SHA —
see [the repository's Actions history](https://github.com/bhavyakeniya/terraform-platform-abstraction/actions),
which is the authoritative per-commit record rather than a SHA copied into this
file by hand.

## Local results

| Suite | Command | Result |
| --- | --- | --- |
| Python contracts/consumers | `uv run pytest tests/ -q` | **PASS** — 205/205 (54 contract, 75 context, 44 environments, 11 pipeline, 16 consumer/runner, 5 security) |
| `team-resources` native mocks (contract) | `make test-module` | **PASS** — 18/18 (resource counts, stable identities, input-validation failures, permissions boundary) |
| `team-resources` native mocks (security) | `make test-module` | **PASS** — 17/17 (controls, public/private matrix, exact policies, oversized-policy, reserved-suffix sweep) |
| `team-backend` native mocks | `make test-backend` | **PASS** — 3/3 (private/versioned/encrypted/locked contract, reserved-name rejection, maximum name length) |
| `team-ci` native mocks | `make test-backend` | **PASS** — 5/5 (exact OIDC trust, scoped state/lock access, protected boundary, whole-policy equality) |
| Root native mocks (generic) | `make test-root-generic` | **PASS** — 2/2, executed once (team-independent) |
| Root native mocks (per declaration) | `make check-examples` | **PASS** — 1 run per committed example (2 executions) |
| Fixture smoke | `make fixture-smoke` | **PASS** — ephemeral fixtures, never committed |
| Portable consumer checks | `make test-consumers` | **PASS** — payments, customers, accounting through the shared mocked-root path |
| `terraform fmt -check -recursive` | `make fmt-check` | **PASS** |
| Full aggregate | `make check`, AWS credentials unset | **PASS**, roughly 90-110s (varies by machine) |

Final consumer-extension regression: `make check` passed with 205 Python tests. Includes an occupied-port regression:
a created-but-not-running container never authorizes cleanup API calls against
an unrelated service. Consumer workflows and the shared action are both
structurally checked and executed on GitHub.

Earlier naming-change verification: `make check` passed in approximately 97
seconds after adopting `sumup--<environment>--<team-id>--<bucket-key>`.
Tests cover exact names, the 51-character generated maximum, reserved suffixes,
and account-independent names with account-separated backend keys/guards.
IAM role names and state-key format are unchanged. No AWS or LocalStack apply
was performed at that stage; current-naming emulator evidence is recorded below.

Contract-hardening verification: the full `make check` also passed after adding
the whole attached-policy comparison, declaration output-count/key assertions,
input descriptions/non-nullability, and read-only initialization (approximately
97 seconds; case counts unchanged). Separate checks in disposable mocked copies
confirmed that an extra IAM allow statement and wrong output keys with the same
bucket count are rejected. Null module owner/root region inputs were rejected
at the input boundary. Both provider lock files and bucket tags were unchanged.

## Requirement coverage

| ID | Requirement | Evidence | Status |
| --- | --- | --- | --- |
| R01 | One IAM role, ≥1 bucket per team | T01 | PASS (mocked) |
| R02 | Team controls bucket count/visibility, no defaults | C02, T03 | PASS |
| R03 | 1→300+ teams, zero platform code changes | 300-team registry case in `tests/test_environments.py` | PASS (configuration scale; see caveat below) |
| R04 | Self-contained team-owned declaration | C01-C03, `docs/environments-and-delivery.md` | PASS (contract); real ownership deferred |
| R05 | Separate state per team | C04, C05 | PASS (keys/derivation); real backend behavior deferred |
| R06 | Declaration change triggers CI/CD | P01-P07 + executed runs in all three team repositories | PASS — a declaration change in a team repository triggers its workflow, which selects the changed environments and validates them through the real module |
| R07 | Role scoped to its own buckets | T04 | PASS (policy structure); real AWS authorization deferred |
| R08 | Enforced consistent naming | C04, C06, T08 | PASS |
| R09 | Idempotent, safe to reapply | T05 | PASS (mocked identity stability); real reapply deferred |
| R10 | Tests without necessarily deploying AWS | this whole table | PASS |
| B01 | Cost/ownership tags | T02 | PASS |
| B02 | Offboarding | `consumer_matrix`'s fail-closed removal detection (retirement receipt required) + `docs/team-lifecycle.md` (options) + `docs/offboarding-procedures.md` (manual retain/destroy) | PASS (detection); retain/destroy documented but unexecuted against AWS; archive/cross-team transfer/export are conceptual and need separate procedures |

## Verification layers

| Layer | Status | Why |
| --- | --- | --- |
| Python contracts/consumers | **Implemented and executed** | Pure, credential-free |
| Terraform native mocks | **Implemented and executed** | `mock_provider`, no network beyond provider download |
| Live GitHub CI (credential-free) | **PASS** | Executed on GitHub-hosted runners in all four repositories; no job holds cloud credentials |
| Live GitHub deployment | **NOT_RUN** | Definitions now exist; activation needs real AWS/GitHub configuration |
| LocalStack | **PASS (provider integration)** | Current naming contract: payments/customers/accounting baseline, lifecycle, recovery, and cleanup passed in an isolated free-supported runtime; IAM enforcement remains UNVERIFIED |
| AWS sandbox | **NOT_RUN** | No account exists (G-AWS, G-IDENTITY, relevant G-PUBLIC) |

## What the scale proof does and does not show

`tests/test_environments.py` generates 300 teams from a single registry and
proves every one yields a distinct backend bucket and lock table, with 900
unique CI bindings across three environments each, without changing any
platform code. `scripts/consumer_matrix.py`'s own tests prove per-environment
selection mechanics: a targeted edit selects one environment, a shared-file
edit selects all, and a removed environment fails closed.

It does **not** run 300 real Terraform applies, initialize 300 real provider
sessions, or prove AWS can actually sustain 300+ concurrent teams' IAM/S3
resource counts — that requires real account quota headroom, which is
unverified and explicitly out of scope until a real AWS account is
available.

## What "fixture-smoke passing" does and does not mean

A green fixture-smoke run means the render→mocked-root-test pipeline
executes correctly in the current environment, right now. It is a
readiness judgment, not a correctness-at-scale or AWS-authorization proof
— the distinction is carried into the code itself (`smoke_check`'s
docstring in `scripts/team_platform.py`) so it survives independent of
this document.

## Repeatable LocalStack consumer verification

The current module/root were exercised through three independent sibling
consumers: payments (2 private buckets), customers (3 buckets including public
help-assets), and accounting (4 private buckets). All coexist in the owned
ephemeral runtime during the test, with distinct local state/data directories.

Run `a95f3a61ef6e48d6a8c233727dbbf24e`: **PASS**, Terraform cleanup **PASS**.
LocalStack 2026.10.5, AWS provider 6.71.0, Terraform 1.17.1. The multi-architecture
image digest and original source hashes are preserved in
[sanitized results](consumer-test-results.json). The user confirmed Hobby access;
only free-supported APIs were exercised. The distribution image's pro label
does not imply IAM enforcement or a paid entitlement.

All three passed baseline saved-plan/apply, exact control/tag/policy readback,
no-change replans, object roundtrip/encryption metadata, key reorder, owner edits,
bucket addition, populated-bucket deletion failure, recovery, return to their
original declarations, and destroy. Customers additionally passed configuration
readback for public/private/public transitions on its approved public bucket.
Known buckets and workload/bootstrap roles were verified removed before the
owned container was removed. Existing user containers were not changed.

The result's backend_key is the derived S3 key, **not an exercised S3 backend**:
the harness uses isolated local state files. Actual IAM/public/TLS enforcement,
AWS authorization, and S3 backend permissions/locking remain UNVERIFIED/NOT_RUN.
LocalStack success does not activate any AWS deployment gate.

Repeatability run `09d8006e9a4a4957b731a3ac16c2b216`, invoked from the actual
payments sibling folder with `make localstack`: **PASS**, cleanup **PASS**, in
a second fresh owned container. [Repeatability evidence](consumer-repeatability.json)
records the UTC start, Python/Terraform/AWS CLI versions, declaration hash, and
source/image identities. No test container remained, and the original five
user containers retained their original IDs. No real AWS resources were changed.

During implementation, a DNS preflight incorrectly required the base S3 Control
hostname and a generated local-backend block had invalid one-line nested HCL.
Both were corrected before this passing run. Failed evidence remains under
ignored .runs; the earlier created container/bootstrap resources were cleaned.

## Historical LocalStack smoke test (manual, ad-hoc)

Historical result: this smoke test used the previous account-prefixed bucket
names. Current-naming verification is supplied by the repeatable consumer run
above; this older run is not additional proof of the current naming contract.

With a real `LOCALSTACK_AUTH_TOKEN` supplied, a one-off manual test ran the
real module through a real `terraform apply` (not `mock_provider`) against
a live LocalStack instance, using a disposable provider/backend copy
(never the real `stacks/team/providers.tf`/`backend.tf`) and a real
rendered fixture from the actual CLI pipeline. This was exploratory and
one-shot — not the repeatable, scripted harness described in
[localstack.md](localstack.md), and not re-run on every `make check`.

What it established:

- The real AWS provider can apply this module against LocalStack: 14
  resources created cleanly.
- Public-access-block flags, bucket policies (TLS-deny; public gets
  exactly anonymous `GetObject`, private gets only the TLS-deny), and the
  IAM role's four-statement inline policy all read back via the real API
  **exactly** matching the design — not approximated, not just "present."
- Idempotence: a refreshed `plan -detailed-exitcode` returned 0 after
  apply.
- Clean `destroy` with nothing left behind.

**One real bug found and fixed in the process**, now handled by
the repeatable runner: the AWS provider's S3 Control
`ListTagsForResource` call (triggered by setting `tags` on `aws_s3_bucket`)
constructs a hostname with the AWS account ID prepended
(`<account-id>.<host>`) — this is how S3 Control addressing works, not a
path-style-vs-virtual-style choice, so `s3_use_path_style = true` does not
fix it. Against a bare-IP endpoint (`127.0.0.1`) that hostname can't
resolve. Fix: point the `s3control` endpoint at `localhost.localstack.cloud`
(a hostname, not an IP) and map the specific account-prefixed subdomain
(`000000000000.localhost.localstack.cloud`, for the fixed test account) in
`/etc/hosts`, since the wildcard `*.localhost.localstack.cloud` DNS
LocalStack normally relies on didn't resolve on the network this was
tested from.

What it did **not** establish: IAM policy enforcement (this LocalStack
license tier doesn't enforce authorization — see
[localstack.md](localstack.md)'s evidence contract), the full LS01–LS12
lifecycle sweep, or anything
repeatable/automated. Still **UNVERIFIED**/**NOT_RUN** respectively.

## External blockers, named precisely

| Gate | Blocks | What's needed |
| --- | --- | --- |
| **G-PUBLISH** (met) | Previously blocked sharing this repository and any live GitHub Actions run | Met: the four repositories are public under `bhavyakeniya` and their workflows have run. This opens no AWS authorization |
| **G-AWS** | Real IAM/S3 behavior, idempotence against a real backend, actual lock contention | A dedicated AWS account/region, authenticated profile, explicit deployment/cleanup authorization |
| **G-IDENTITY** | Trust-policy correctness against a real principal | The actual intended workload trust principal |
| **G-LS** (met for local emulator use) | Repeating optional emulator integration | User confirmed free Hobby access; Docker/token/DNS prerequisites must be available on each workstation. This opens no AWS deployment or authorization claim |
| **G-PUBLIC** | Testing real anonymous public-object access | Named human approval of the exact public bucket keys in the selected sandbox |
| **G-GH** (pass two) | Restricted deployment identity/OIDC, branch protections, protected environments | A separate authorization; explicitly not implied by the repositories now being public and running CI |

None of these are silently treated as passed. Where a gate blocks a
specific evidence row above, that row says so explicitly rather than
reporting an aggregate pass.
