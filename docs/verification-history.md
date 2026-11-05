# Verification history

Dated run records and narrative evidence superseded by
[verification.md](verification.md)'s current tables. Kept for the run IDs,
the exact debugging detail, and the LocalStack narrative — not as current
evidence.

## Root version and independent scanner hardening — 5 November 2026

Both deployed roots were constrained to Terraform `~> 1.17.0` and AWS
`~> 6.0`. Runtime remained exactly 1.17.1, provider locks remained 6.71.0,
and existing lock-file hashes were unchanged.

- Security scope: every production module/root plus the concrete
  public/private fixture, in a source-only temporary workspace with
  synthetic inputs for the actual roots. Trivy 0.73.0: 161 successful
  evaluations, no unexcepted failures. Checkov 3.3.10: 141 passed, 0
  failed, 27 resource-scoped exception instances, 0 parsing errors. See
  [security-scan-results.json](security-scan-results.json).
- A private-access regression failed both scanners; an administrator IAM
  policy inserted directly into the real workload-root source failed
  Checkov and the CLI gate. Trivy's embedded rules did not flag that
  standalone IAM policy.
- Homebrew Checkov at the same reported package version produced a
  different graph-check result than the locked `tools/security/uv.lock`
  environment — the isolated environment is what CI and `make security`
  use; the globally installed Checkov is ignored.

Scanning reusable modules without concrete inputs left visibility and
`for_each` branches unresolved. The source snapshot and fixture supply those
inputs; keyed bucket references let Checkov associate versioning and access
controls with the correct buckets. This avoided adding exceptions for unresolved
private-access or versioning checks.

## Environment and shared-delivery extension — 5 November 2026

The full emulator run is recorded in
[environment-test-results.json](environment-test-results.json), run
`15d94dbd81fd40daa1786b8bacfa4e06`, started 2026-11-04 22:39 UTC, about 20
minutes. All states coexisted before lifecycle tests; holding one state's
DynamoDB lock blocked Terraform for that state while other teams/environments
could still plan. Workload resources, state versions, backend fixture
tables/buckets, and the run-owned container were all cleaned up; the
pre-existing emulator was preserved.

The final-source backend repeat is
[environment-backend-repeat.json](environment-backend-repeat.json), run
`db330b55e93347c0b5f42ba2b2ec0795`. It records `mode=baseline-only` and
`lifecycle=NOT_RUN`; it supplements the full run without claiming to repeat
its extended mutations. A subsequent CI-only action-name audit added four
non-GetBucket read permissions, scoped role update/tag reads, and removed
nonexistent delete action names — covered by the final native whole-policy
test. CI-role effective authorization is not exercised by Hobby; native tests
verify its policy construction.

Plans, provider diagnostics, state, credentials and tokens are not published
as GitHub artifacts.

## Earlier local-suite milestones

Final consumer-extension regression: `make check` passed with 205 Python
tests, including an occupied-port regression — a created-but-not-running
container never authorizes cleanup API calls against an unrelated service.

Earlier naming-change verification: `make check` passed after adopting
`sumup--<environment>--<team-id>--<bucket-key>`. Tests covered exact names,
the 51-character generated maximum, reserved suffixes, and
account-independent names with account-separated backend keys/guards. No
AWS or LocalStack apply was performed at that stage.

Contract-hardening verification: `make check` passed after adding the whole
attached-policy comparison, declaration output-count/key assertions, input
descriptions/non-nullability, and read-only initialization. Separate checks
in disposable mocked copies confirmed that an extra IAM allow statement and
wrong output keys with the same bucket count are rejected, and that null
module owner/root region inputs are rejected at the input boundary.

## Repeatable LocalStack consumer verification

The current module/root at the time were exercised through three
independent sibling consumers: payments (2 private buckets), customers (3
buckets including public help-assets), and accounting (4 private buckets).
All coexisted in one owned ephemeral runtime, with distinct local
state/data directories.

Run `a95f3a61ef6e48d6a8c233727dbbf24e`: PASS, Terraform cleanup PASS.
LocalStack 2026.10.5, AWS provider 6.71.0, Terraform 1.17.1. The
multi-architecture image digest and source hashes are preserved in
[consumer-test-results.json](consumer-test-results.json). Free Hobby access
was used; only free-supported APIs were exercised.

All three passed baseline saved-plan/apply, exact control/tag/policy
readback, no-change replans, object roundtrip/encryption metadata, key
reorder, owner edits, bucket addition, populated-bucket deletion failure,
recovery, return to their original declarations, and destroy. Customers
additionally passed configuration readback for public/private/public
transitions on its approved public bucket. Known buckets and
workload/bootstrap roles were verified removed before the owned container
was removed.

The result's `backend_key` is the derived S3 key, not an exercised S3
backend: the harness uses isolated local state files. Real IAM/public/TLS
enforcement, AWS authorization, and S3 backend permissions/locking were
UNVERIFIED/NOT_RUN.

Repeatability run `09d8006e9a4a4957b731a3ac16c2b216`, from the payments
sibling folder with `make localstack`: PASS, cleanup PASS, in a second fresh
owned container. [consumer-repeatability.json](consumer-repeatability.json)
records the UTC start, tool versions, declaration hash, and source/image
identities. No test container remained; the original five user containers
retained their original IDs.

During implementation, a DNS preflight incorrectly required the base S3
Control hostname, and a generated local-backend block had invalid one-line
nested HCL. Both were corrected before this passing run.

## Historical LocalStack smoke test (manual, ad-hoc)

This smoke test used the previous account-prefixed bucket names, before the
naming change. It is not proof of the current naming contract — the
repeatable consumer run above supplies that.

With a real `LOCALSTACK_AUTH_TOKEN`, a one-off manual test ran the real
module through a real `terraform apply` (not `mock_provider`) against a live
LocalStack instance, using a disposable provider/backend copy and a real
rendered fixture from the actual CLI pipeline. This was exploratory and
one-shot, not the repeatable harness above.

What it established:

- The real AWS provider can apply this module against LocalStack: 14
  resources created cleanly.
- Public-access-block flags, bucket policies (TLS-deny; public gets exactly
  anonymous `GetObject`, private gets only the TLS-deny), and the IAM role's
  four-statement inline policy all read back via the real API **exactly**
  matching the design.
- Idempotence: a refreshed `plan -detailed-exitcode` returned 0 after apply.
- Clean `destroy` with nothing left behind.

**One real bug was found and fixed in the process**, now handled by the
repeatable runner: the AWS provider's S3 Control `ListTagsForResource` call
(triggered by setting `tags` on `aws_s3_bucket`) constructs a hostname with
the AWS account ID prepended (`<account-id>.<host>`) — this is how S3
Control addressing works, not a path-style-vs-virtual-style choice, so
`s3_use_path_style = true` does not fix it. Against a bare-IP endpoint
(`127.0.0.1`) that hostname can't resolve. Fix: point the `s3control`
endpoint at `localhost.localstack.cloud` (a hostname, not an IP) and map the
specific account-prefixed subdomain
(`000000000000.localhost.localstack.cloud`, for the fixed test account) in
`/etc/hosts`, since the wildcard `*.localhost.localstack.cloud` DNS
LocalStack normally relies on didn't resolve on the network this was tested
from.

What it did not establish: IAM policy enforcement, the full LS01–LS12
lifecycle sweep, or anything repeatable/automated.
