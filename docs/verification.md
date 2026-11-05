# Verification

**Current source is verified by local checks and by live, credential-free
GitHub Actions runs across all four repositories. Real AWS verification
remains blocked** — no account is enrolled. The LocalStack emulator run below
passed against an earlier source snapshot, not the current tree.

Dated run records, run IDs, and full narrative evidence (including a real bug
found and fixed during the LocalStack run) are in
[verification-history.md](verification-history.md).

## Tool versions

| Tool | Version | Source |
| --- | --- | --- |
| Python | 3.13.15 | `.python-version`, pinned via `uv` |
| uv | 0.12.3 | Homebrew |
| Terraform | 1.17.1 | `.terraform-version`; fetched directly from `releases.hashicorp.com`, not a third-party action |
| AWS provider | 6.71.0 | Resolved from `>= 5.0, < 7.0`; recorded in all six committed `.terraform.lock.hcl` files |
| pytest | 8.4.2 | `uv.lock` |
| jsonschema | 4.26.0 | `uv.lock` |

Every commit on `main` is verified by the GitHub Actions run for that exact
SHA — see [the repository's Actions history](https://github.com/bhavyakeniya/terraform-platform-abstraction/actions),
the authoritative per-commit record.

## Local results

| Suite | Command | Result |
| --- | --- | --- |
| Python contracts/consumers | `uv run pytest tests/ -q` | **PASS** — 205/205 (54 contract, 75 context, 44 environments, 11 pipeline, 16 consumer/runner, 5 security) |
| `team-resources` native mocks (contract) | `make test-module` | **PASS** — 18/18 |
| `team-resources` native mocks (security) | `make test-module` | **PASS** — 17/17 |
| `team-backend` native mocks | `make test-backend` | **PASS** — 3/3 |
| `team-ci` native mocks | `make test-backend` | **PASS** — 5/5 |
| Root native mocks (generic) | `make test-root-generic` | **PASS** — 2/2, executed once |
| Root native mocks (per declaration) | `make check-examples` | **PASS** — 1 run per committed example |
| Fixture smoke | `make fixture-smoke` | **PASS** |
| Portable consumer checks | `make test-consumers` | **PASS** — payments, customers, accounting |
| `terraform fmt -check -recursive` | `make fmt-check` | **PASS** |
| Workflow syntax | `actionlint` | **PASS** — platform workflows and a generated pinned caller |
| 300-team configuration scale | `tests/test_environments.py` | **PASS** — 300 distinct backend names, 900 unique CI bindings, no platform code change; AWS capacity itself is unverified |
| Full aggregate | `make check`, AWS credentials unset | **PASS**, roughly 90-110s |
| AWS/OIDC acceptance | — | **NOT RUN** — no real AWS account, registered identity, OIDC trust, or protected environment exists |

Security scan counts (Trivy, Checkov) are in [security-scanning.md](security-scanning.md)
rather than duplicated here.

## Live GitHub Actions runs

| Repository | Workflow | Result |
| --- | --- | --- |
| [terraform-platform-abstraction](https://github.com/bhavyakeniya/terraform-platform-abstraction) | `terraform.yml` | **PASS** — `security`, `checks`, `fixture-smoke` |
| [team-payments](https://github.com/bhavyakeniya/team-payments) | `infrastructure.yml` | **PASS** — `check`; `deploy`/`localstack` skipped |
| [team-customers](https://github.com/bhavyakeniya/team-customers) | `infrastructure.yml` | **PASS** — `check`; `deploy`/`localstack` skipped |
| [team-accounting](https://github.com/bhavyakeniya/team-accounting) | `infrastructure.yml` | **PASS** — `check`; `deploy`/`localstack` skipped |

Each team run checks out the platform at its pinned SHA, renders that team's
declarations, and validates all three environments through the real module
under `mock_provider`. This is the strongest evidence here for the
abstraction working across repository boundaries: a team repository
containing only JSON produces a validated plan using Terraform it does not
own.

### What these runs do not establish

- **No AWS authorization.** No job holds cloud credentials. `deploy` is
  skipped on automatic runs and, when dispatched manually, stops at the
  platform registration guard because every environment catalog has
  `deployment_enabled: false` with a fixture account.
- **No deployment protections.** Branch protection, required reviewers,
  protected environments, and OIDC trust are not configured.
- **Default-branch pushes only so far.** Pull-request runs use the same
  credential-free path but have not been exercised with a real PR.

## Requirement coverage

| ID | Requirement | Evidence | Status |
| --- | --- | --- | --- |
| R01 | One IAM role, ≥1 bucket per team | T01 | PASS (mocked) |
| R02 | Team controls bucket count/visibility, no defaults | C02, T03 | PASS |
| R03 | 1→300+ teams, zero platform code changes | 300-team registry case, above | PASS (configuration scale — see below) |
| R04 | Self-contained team-owned declaration | C01-C03, `docs/environments-and-delivery.md` | PASS (contract); real ownership deferred |
| R05 | Separate state per team | C04, C05 | PASS (keys/derivation); real backend behavior deferred |
| R06 | Declaration change triggers CI/CD | Executed runs in all three team repositories, above | PASS |
| R07 | Role scoped to its own buckets | T04 | PASS (policy structure); real AWS authorization deferred |
| R08 | Enforced consistent naming | C04, C06, T08 | PASS |
| R09 | Idempotent, safe to reapply | T05 | PASS (mocked identity stability); real reapply deferred |
| R10 | Tests without necessarily deploying AWS | this whole table | PASS |
| B01 | Cost/ownership tags | T02 | PASS |
| B02 | Offboarding | `consumer_matrix`'s fail-closed removal detection + [consumers.md](consumers.md) (options) + [offboarding-procedures.md](offboarding-procedures.md) (manual retain/destroy) | PASS (detection); retain/destroy documented but unexecuted against AWS |

## Verification layers

| Layer | Status | Why |
| --- | --- | --- |
| Python contracts/consumers | **Implemented and executed** | Pure, credential-free |
| Terraform native mocks | **Implemented and executed** | `mock_provider`, no network beyond provider download |
| Live GitHub CI (credential-free) | **PASS** | Executed on GitHub-hosted runners in all four repositories |
| Live GitHub deployment | **NOT_RUN** | Definitions exist; activation needs real AWS/GitHub configuration |
| LocalStack | **PASS, dated** | See below — passed against an earlier source snapshot |
| AWS sandbox | **NOT_RUN** | No account exists |

## LocalStack evidence

The current module and root were exercised through three independent
consumers (payments, customers, accounting) against a real LocalStack
provider: saved-plan apply, exact control/tag/policy readback, no-change
replan, object roundtrip, key reorder, owner edit, bucket addition, a
populated-bucket deletion that correctly fails, recovery, and destroy all
passed. Run details, versions, and the full narrative are in
[verification-history.md](verification-history.md).

This ran against a **2026-11-04 source snapshot**; 17 of the 27 recorded
source files have since changed (including the IAM role naming in this
document's own history), so it is historical evidence, not proof against
current source. Re-run `make test-localstack` to re-establish it.

It did **not** establish IAM policy enforcement (this LocalStack tier doesn't
enforce authorization), real S3 backend locking, or AWS authorization. See
[localstack.md](localstack.md) for the harness and its evidence contract.

## Limits of these results

- A green fixture-smoke run is a readiness signal — the pipeline executes
  correctly right now — not a correctness-at-scale or AWS-authorization proof.
- The 300-team case proves configuration scale, not 300 real applies or AWS
  quota headroom.
- The manual apply workflow creates and applies a fresh plan in one job; see
  [operations.md](operations.md) for exactly what a dispatch approves.

## External blockers

| Gate | Blocks | What's needed |
| --- | --- | --- |
| **G-PUBLISH** (met) | — | The four repositories are public and their workflows run. This opens no AWS authorization. |
| **G-AWS** | Real IAM/S3 behavior, idempotence against a real backend, actual lock contention | A dedicated AWS account/region, authenticated profile, explicit deployment/cleanup authorization |
| **G-IDENTITY** | Trust-policy correctness against a real principal | The actual intended workload trust principal |
| **G-LS** (met for local emulator use) | Repeating optional emulator integration | Docker/token/DNS prerequisites must be available on each workstation |
| **G-PUBLIC** | Testing real anonymous public-object access | Named human approval of the exact public bucket keys in the selected sandbox |
| **G-GH** (pass two) | Restricted deployment identity/OIDC, branch protections, protected environments | A separate authorization; not implied by the repositories being public and running CI |
