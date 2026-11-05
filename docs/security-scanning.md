# Independent Terraform security checks

CI runs Trivy and Checkov before anything else in `make check`, alongside
tests that confirm unsafe configurations are rejected. This is not a
compliance certification or proof of effective AWS IAM authorization.

## Run locally

Use the existing pinned Python/uv setup and install Trivy **0.73.0** (the version
in `config/security-tools.json`). Then:

```bash
make security         # Trivy + Checkov, fails on an unexcepted finding
make test-security    # unsafe private access and administrator IAM must fail
make check            # security gates plus the existing full local suite
```

`make security-tools` installs Checkov **3.3.10** automatically into its isolated
`tools/security/.venv`, using `tools/security/uv.lock` and the pinned Python
3.13.15. The globally installed Checkov is ignored. During verification, a global
Homebrew Checkov with the same version omitted graph checks that the isolated
installation ran. Locking just the top-level version was insufficient.

For a local Trivy binary, use the official release for your OS/architecture and
verify its published checksum; the CI Linux/x86_64 checksum is committed in the
manifest. CI downloads that exact artifact and verifies SHA-256 before execution.
It uses the same locked Checkov environment and commands as local checks.

Both scanners run locally against source, without AWS/GitHub/Prisma credentials.
AWS SDK config/credential paths point to empty temporary files, and instance
metadata discovery is disabled. Trivy telemetry, policy downloads and version
checks are disabled. A new empty
cache forces the pinned binary's embedded policy bundle, avoiding machine-specific
cached checks. Checkov downloads/uploads and external-module downloads are
disabled; local module sources are still evaluated. Reports stay under ignored
`.runs/security/`; no cloud state, private plans, app data or tokens are scanned
or published. Scanner errors, missing tools, version mismatches, empty results
and parsing errors fail the gate. There is no soft-fail or severity-only filter.

## Coverage and CI wiring

The scanners check `modules/`, `stacks/`, and `examples/security/main.tf` in a
source-only temporary copy. Synthetic inputs make the workload and bootstrap
roots scannable without deployment or changes to the working Terraform files.

The workload root uses private-bucket inputs. A separate fixture calls all three
modules and exercises both public and private buckets; public-access exceptions
apply only to its public caller. Its synthetic-account guard prevents AWS use.

| Where | Enforcement |
| --- | --- |
| Platform CI | The `security` job must pass before `checks` runs. |
| Team CI | The shared `check` job runs the same security gate; plan and apply depend on it. |
| Backend bootstrap | The operator runs `make security test-security` before reviewing the bootstrap plan. |

Regression tests run the actual scanner CLIs against deliberately unsafe source
copies:

- Disabling `restrict_public_buckets` for a private bucket must fail both tools.
- Adding an administrator IAM policy must fail Checkov. Trivy's pinned rules do
  not detect this case, so the tools provide complementary coverage.

Native Terraform tests also check complete policies, visibility, and output
contracts. These checks do not prove effective AWS authorization or cover every
possible input. Scanner implementation history is in
[verification-history.md](verification-history.md).

## Explicit scope exceptions

These are accepted take-home scope choices already documented in
[assumptions.md](assumptions.md), not claims that the controls are unnecessary
for production. No rule ID or severity is globally disabled. Generated caches, states and tool
virtual environments are omitted from the source snapshot; production Terraform
roots/modules are included.
Inline annotations name each rule at the specific resource; the public-access
annotations exist only at the public fixture caller.

| Location | Rule IDs | Reason and remaining control |
| --- | --- | --- |
| Public fixture caller only | Trivy AWS-0087, AWS-0093 | Direct public current-object reads are required. Only public-policy blocking/restriction are relaxed; ACL blocking remains required. Private caller receives no exception. |
| Workload and backend bucket resources | Trivy AWS-0089; Checkov CKV_AWS_18 | No access-log destination/audit-retention contract exists in this assignment. Production must choose one; this gate does not claim access logging. |
| S3 encryption/bucket resources | Trivy AWS-0132; Checkov CKV_AWS_145 | Explicit SSE-S3/AES256 is the chosen contract. Customer-managed KMS is not required and is incompatible with the current direct anonymous-read public-object model. Encryption/versioning are still tested independently. |
| DynamoDB lock table only | Trivy AWS-0025; Checkov CKV_AWS_119 | Encryption uses the AWS-managed key; a customer-managed key/policy is outside scope. Encryption, PITR and deletion protection remain enabled. |
| Workload and backend buckets | Checkov CKV_AWS_144 | Cross-region replication needs a second region, destination, role and retention policy; none is specified. |
| Workload and backend buckets | Checkov CKV2_AWS_61 | No automatic object/state expiry is selected; retention/destruction is an explicit operator decision. Adding lifecycle deletion merely to silence a scanner would risk data loss. |
| Workload and backend buckets | Checkov CKV2_AWS_62 | No notification destination or event consumer is specified. |

Review these exceptions before real AWS activation and whenever public access,
KMS, logging, replication, notifications or retention requirements change.
Scanner upgrades are reviewed changes: update pins/locks/checksum together and
rerun the positive fixture and both canaries. Do not suppress newly appearing
findings automatically.

## Root version intent

Both deployed roots (`stacks/team`, `stacks/backends`) now require Terraform
`~> 1.17.0` (1.17.x) and AWS provider `~> 6.0` (6.x). The executable remains exactly
1.17.1 and provider selections remain exactly 6.71.0 in their existing lock files.
The reusable modules retain their wider compatibility ranges.

`~> 1.17` would allow later Terraform 1.x minors; it does not pin the 1.17 minor.
The provider constraint intentionally pins the major, while read-only lockfile
initialization preserves the selected patch. `init -upgrade` can intentionally
move the provider within 6.x; treat that as a separate reviewed lockfile upgrade.
No provider upgrade, backend migration, state mutation or AWS apply accompanies
this change.

Sources: [Terraform constraints](https://developer.hashicorp.com/terraform/language/expressions/version-constraints),
[Trivy configuration and inline exceptions](https://www.trivy.dev/docs/latest/scanner/misconfiguration/config/config/),
[Checkov CLI](https://www.checkov.io/2.Basics/CLI%20Command%20Reference.html).
