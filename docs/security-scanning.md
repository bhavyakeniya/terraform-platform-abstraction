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

All production Terraform under `modules/` and `stacks/` is scanned, together
with `examples/security/main.tf`. The wrapper makes a temporary source-only
snapshot, supplies synthetic inputs to the actual workload/bootstrap roots via
the existing contract/renderer, and never writes auto.tfvars into the working
roots. This avoids unresolved bootstrap OIDC subjects becoming false positives.
The real workload root receives private-only inputs; the dedicated public fixture
exercises public behavior without waiving private checks on that real root.

`examples/security/main.tf` calls all three modules with concrete inputs, using
separate private and public callers so branch-specific exceptions remain scoped.
Its synthetic account guard makes the composition unsuitable for real AWS apply.
Running scanners only against input-free reusable modules left visibility/for_each
branches unresolved; this composition supplies those values without deployment.

The module's `for_each = var.buckets` resources let Checkov associate
versioning and access controls with their specific bucket, rather than losing
that link when scanning modules without concrete inputs.

The main platform workflow has a required `security` job, and its checks job
requires that job. The reusable team workflow runs the same security composite
inside its credential-free `check` job. Deployment requires `check`, so both plan
and apply paths are gated. Bootstrap operators also run these commands before
reviewing their bootstrap plan. Both scanners now execute on GitHub-hosted runners as well as locally; what
remains unverified is AWS authorization, not the scanners running.

The canaries run the actual scanner CLI in temporary source copies. They prove:

- Setting private `restrict_public_buckets=false` fails both tools, despite the
  public example's narrow exceptions.
- Adding an Allow `Action="*", Resource="*"` IAM policy directly to the real
  workload-root source fails Checkov and the CLI
  gate. Trivy 0.73's embedded rules did not flag that standalone IAM canary;
  the tools provide complementary coverage, not identical guarantees.

Native tests still verify complete policies, explicit visibility, exact output
keys and module invariants. Scanner source-graph evaluation and a concrete fixture
cannot prove every possible input or replace real AWS denial/public/TLS tests.
TFLint is useful structural linting, but is not a substitute for these security
rules and is not required by this gate.

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
