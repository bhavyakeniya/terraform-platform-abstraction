# Scanner-only composition — never apply

Concrete inputs exercise private and explicitly public workload buckets, the
team backend and the CI identity in Trivy and Checkov. Scanning modules alone
leaves for_each/visibility inputs unresolved and can miss a branch.

Account 000000000000 is a fixture. The provider account allowlist deliberately
prevents applying this example to a real AWS account. No Terraform init, plan or
AWS credentials are required to scan it.

Only the public module caller waives Trivy's two private-only policy-block rules.
The private caller remains checked; a real CLI regression canary verifies that
an unsafe private control still fails. Resource-level KMS/logging/retention/etc.
exceptions are explained in [security-scanning.md](../../docs/security-scanning.md).

Run `make security test-security` from the repository root.
