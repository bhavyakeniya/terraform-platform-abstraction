# team-resources

Creates S3 buckets and one workload IAM role for a single team/environment.
The shared [team root](../../stacks/team/main.tf) calls this module separately
for each configuration. Backend storage and CI identities are provisioned by
other modules.

## Inputs

| Input | Type and requirements |
| --- | --- |
| `team_id` | `string`; stable team ID, at most 16 characters |
| `environment` | `string`; platform-selected environment, at most 8 characters |
| `account_id` | `string`; target commercial AWS account, exactly 12 digits |
| `owner` | `string`; tag-safe contact metadata, at most 128 characters |
| `buckets` | `map(object({ visibility = string }))`; at least one entry, each explicitly `public` or `private` |
| `trusted_principal_arn` | `string`; exact existing role in the same account, without a role path, wildcard, or account-root principal |
| `permissions_boundary_arn` | `string`, default `null`; when supplied, must match this account/team/environment's platform boundary |

All inputs except `permissions_boundary_arn` are required and reject null.
The module validates inputs independently of the Python helper; see
[variables.tf](variables.tf) for the full constraints.

## Outputs

| Output | Value |
| --- | --- |
| `role_arn` | Workload role ARN |
| `bucket_names` | Bucket names keyed by declaration key |
| `bucket_arns` | Bucket ARNs keyed by declaration key |
| `visibility` | Declared visibility keyed by declaration key |

## Naming

```text
bucket:    sumup--<environment>--<team-id>--<bucket-key>
role:      <environment>--<team-id>--s3
role path: /team-platform/runtime/<environment>/<team-id>/
```

Environment, team ID, and bucket keys start with a lowercase letter and allow
lowercase letters, digits, and single hyphens. Bucket keys are at most 16
characters; generated bucket names reach at most 51. Completed names are checked
against S3 length and reserved-name restrictions.

Bucket names contain no account ID. The same environment/team/key in another
account or region requests the same globally unique name; a collision fails
without automatic import, renaming, or takeover. See
[naming decisions A07–A09](../../docs/assumptions.md#naming-and-resource-identity-choices)
for the reasoning.

Bucket keys are stable Terraform resource addresses. Reordering keys, changing
the owner, or adding a bucket preserves existing identities. Changing team,
environment, or bucket identifiers requires migration review.

## Security

Every bucket has ownership enforcement (`BucketOwnerEnforced`), SSE-S3/AES256
encryption, versioning, and a policy denying insecure transport. Tags are
`Team`, `Environment`, `Owner`, and `ManagedBy`. With `force_destroy=false`,
Terraform cannot automatically empty a populated bucket for deletion.

| Setting | Private | Public |
| --- | --- | --- |
| `block_public_acls` / `ignore_public_acls` | Both `true` | Both `true` |
| `block_public_policy` / `restrict_public_buckets` | Both `true` | Both `false` |
| Anonymous access | None | `s3:GetObject` on current objects only |

Public access grants no listing, writes, deletion, or historical-version reads.
Account and organization controls must also permit public policies; see
[public-control prerequisites](../../docs/operations.md#public-control-prerequisites).

The workload role trusts only `trusted_principal_arn`. Its inline policy has four
statements:

1. Allow `s3:ListBucket` and `s3:GetBucketLocation` on its declared buckets.
2. Allow `s3:GetObject`, `s3:PutObject`, and `s3:DeleteObject` on their objects.
3. Deny `s3:*` outside those bucket/object ARNs using `NotResource`.
4. Deny the allowed actions when `s3:ResourceAccount` differs from `account_id`.

The policy grants no IAM administration, bucket-policy administration, or backend
access. ARNs are derived from bucket names so the inline-policy size guard can
run during planning. Policies over 10,240 characters are rejected; see
[iam.tf](iam.tf) for policy construction and the precondition.

### Live CI permissions boundary

Direct consumers may omit `permissions_boundary_arn`. Live CI always supplies
`arn:aws:iam::<account-id>:policy/sumup-boundary--<environment>--<team-id>`.
The CI role cannot create an unbounded workload role or remove/change its
boundary. Boundary provisioning and deployment permissions belong to the
[CI identity module](../team-ci/README.md).

## Testing

From this directory, using the pinned Terraform version:

```bash
terraform init -backend=false -lockfile=readonly
terraform validate
terraform test -filter=tests/contract.tftest.hcl
terraform test -filter=tests/security.tftest.hcl
```

Both suites mock AWS and need no credentials. They check resource counts, stable
identities, input validation, bucket controls, exact trust and permissions
policies, reserved names, and the policy-size guard. The whole-policy assertion
rejects unexpected statements or fields.

Mocks verify configuration and policy construction; effective AWS authorization
still requires sandbox acceptance. See [verification](../../docs/verification.md)
for results and tested snapshots, and the [LocalStack runbook](../../docs/localstack.md)
for optional provider integration. Deliberate provider upgrades are separate
reviewed changes to the affected lock files.
