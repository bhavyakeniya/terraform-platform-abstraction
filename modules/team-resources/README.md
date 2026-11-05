# team-resources

Provisions exactly one team's S3 buckets and one workload IAM role. No
defaults anywhere — every input is required. Invoked once per team by
`stacks/team` (never `for_each` across teams at this layer); scaling to
300+ teams means running the root repeatedly, never changing this module.

## Inputs

| Input | Type | Supplied by |
| --- | --- | --- |
| `team_id` | `string` | Validated selected directory or explicit fixture ID |
| `environment` | `string` | Platform configuration |
| `account_id` | `string`, exactly 12 digits | Platform configuration |
| `owner` | `string` | Validated declaration |
| `buckets` | `map(object({ visibility = string }))` | Validated declaration |
| `trusted_principal_arn` | `string` | Platform configuration; exact same-account IAM role ARN, no wildcard/account-root trust |

Every input has a description, no default, and `nullable = false`: callers must
supply a non-null value. Nulls inside the bucket map still depend on the nested
type/value contract; top-level nullability is not recursive.

Every input is re-validated here with `variable { validation {...} }` blocks
— blocking, not a warning-only `check` block — even though Python already
enforces the same rules, because this module must behave correctly for any
direct consumer, not only the one Python helper that happens to exist today.

## Outputs

`role_arn` (string), `bucket_names` (map), `bucket_arns` (map), `visibility`
(map).

## Naming

```
bucket:    sumup--<environment>--<team-id>--<bucket-key>
role:      <environment>--<team-id>--s3
role path: /team-platform/runtime/<environment>/<team-id>/
```

The bucket prefix exists because S3 names are globally unique; the role has no
prefix because IAM names are account-scoped and the path already groups them.
Environment and team stay in the role name regardless: AWS requires friendly
names to be unique per account, and the path does not supply that uniqueness.

Completed names are validated — length and the AWS reserved
prefix/suffix list (`-s3alias`, `--ol-s3`, `--x-s3`, `--table-s3`, `-an`,
`xn--`, `sthree-`, `amzn-s3-demo-`, `.mrap`, IP-address form) — in a
blocking `variable "buckets" { validation {...} }` block, before any
resource is planned. Generated names reach at most 51 characters, leaving 12
below S3's 63-character limit. Account IDs stay in execution/security context
and state keys, not bucket names. The same environment/team/key in another
account or region produces the same name; unrelated owners can also occupy
it. This single-target design fails on collision without automatic takeover or
renaming. See the top-level README.

`for_each = var.buckets` with stable addresses (`aws_s3_bucket.this["reports"]`):
reordering declared keys, editing `owner`, or adding a bucket preserves
every existing resource's identity. Renaming a team or a bucket key is a
migration, never an ordinary edit — see `tests/contract.tftest.hcl`'s
`reorder_keys_no_change`/`owner_change_no_replacement`/
`add_bucket_preserves_existing` runs, which prove this by checking that a
bucket's ARN doesn't change across a non-replacing apply (a mock-provider
computed attribute only changes on actual replacement).

S3 bucket ARNs have no account/region component
(`arn:aws:s3:::<name>`), so every ARN used in policy construction is
derived from the deterministic `local.bucket_names` map, never from the
`aws_s3_bucket` resources' own computed `.arn` attribute. This keeps the
whole policy — and the oversized-policy precondition below — evaluable at
plan time, before any bucket exists, rather than deferred to apply.

## Security

**Buckets** (`buckets.tf`): BucketOwnerEnforced ownership, SSE-S3/AES256
default encryption, versioning enabled, `force_destroy = false`, platform
tags (`Team`, `Environment`, `Owner`, `ManagedBy`). One composed bucket
policy per bucket, created only after ownership/public-access controls
(`depends_on`), no ACL resources anywhere.

| | Private | Public |
| --- | --- | --- |
| `block_public_acls` / `ignore_public_acls` | both `true` | both `true` |
| `block_public_policy` / `restrict_public_buckets` | both `true` | both `false` |
| Anonymous access | none | `s3:GetObject` on current objects only |

The bucket policy always denies insecure transport
(`aws:SecureTransport = false`). A public bucket's anonymous grant targets
`<bucket-arn>/*` only — never the bucket ARN itself, so there is no
anonymous listing, and never any action besides `GetObject`, so there is
no anonymous write/delete/historical-version access.

**IAM role** (`iam.tf`): exactly one role, trusting only
`trusted_principal_arn` (no account-root, no wildcard). One inline policy,
built with `jsonencode` from the deterministic ARNs above — never a mocked
`aws_iam_policy_document` data source, so the generated JSON is directly
inspectable in both tests and real plans:

1. `Allow` — `s3:ListBucket`, `s3:GetBucketLocation` on the team's bucket ARNs.
2. `Allow` — `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` on the team's object ARNs.
3. `Deny` — `s3:*` on `NotResource` = everything outside the owned set (including another team's public bucket, even via a legitimately signed request).
4. `Deny` — the same allowed actions, if the resource's AWS account ever differs from this team's `account_id` (`s3:ResourceAccount` condition). Bucket names are not ownership proof; keep the account check independently of naming. Per-action condition-key support should be re-checked against the pinned provider/AWS release before a real deployment.

No IAM administration, no bucket-policy administration, no backend access,
no deployment role, no permissions-boundary infrastructure — those are
privileged platform/bootstrap concerns outside this module's scope.

**Oversized-policy guard**: AWS's IAM role inline-policy aggregate quota is
10,240 characters, whitespace excluded (verified against the live AWS IAM
quotas page, not assumed). A `lifecycle { precondition {...} }` on the
role-policy resource checks the generated policy's length before apply and
fails with a clear message rather than an opaque AWS API error — exercised
by `tests/security.tftest.hcl`'s `rejects_oversized_inline_policy` with 35
maximum-length bucket keys.

## Testing

```bash
terraform init -backend=false -lockfile=readonly
terraform validate
terraform test -filter=tests/contract.tftest.hcl   # T01, T05, essential input-validation failures
terraform test -filter=tests/security.tftest.hcl   # T02-T04, T06 (oversized), T08 (full reserved-suffix sweep)
```

Both suites use `mock_provider "aws" {}` — no AWS credentials, no network
calls beyond the provider plugin download. They assert against the actual
generated resource attributes and `jsonencode()` policy JSON, never a
Python reconstruction of what the policy "should" look like. This proves
policy *structure* is correct; it does not prove AWS will enforce that
policy the way its evaluation engine does in practice — that requires the
AWS-sandbox acceptance suite described in `docs/verification.md`, which
remains blocked pending account access (a separate gate from LocalStack).

The security suite also compares the entire attached workload policy against
an independent four-statement fixture contract, rejecting extra statements or
fields. The per-declaration root test verifies both bucket count and exact
output keys against the supplied declaration. All routine Make/helper/CI
initialization uses read-only provider lock files. Deliberate dependency updates
must be performed separately and both changed lock files reviewed.

A manual LocalStack smoke test using the previous account-prefixed bucket
names — a real `apply`, not `mock_provider` — previously confirmed policy
structure round-trips through the real AWS provider against emulated APIs: see `docs/verification.md`,
"LocalStack smoke test." That's stronger than a mock, but it's still not
the real AWS authorization engine, and it was a one-off manual run, not a
suite exercised by `make check`. That historical run does not verify the current
bucket naming contract; current integration evidence is recorded below.

The later repeatable consumer extension now tests the current naming contract
against LocalStack with payments, customers, and accounting. Baseline/lifecycle/
recovery/cleanup results and limits are recorded in `docs/verification.md`;
team usage is in `docs/consumers.md`. The module implementation is shared across
all three; no Purpose tag or consumer-specific Terraform was added.

## Live CI permissions boundary

`permissions_boundary_arn` is optional only for legacy/direct local consumption.
The live platform renderer always supplies the exact platform-managed
`sumup-boundary--<environment>--<team-id>` policy ARN. CI cannot create an
unbounded workload role or remove/change that boundary. Backend and CI identities
are separate modules; see [delivery](../../docs/environments-and-delivery.md).
