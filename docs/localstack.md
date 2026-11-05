# LocalStack consumer integration runbook

The platform now implements local consumer checks and a repeatable emulator
lifecycle runner. This supersedes the earlier documentation-only smoke-a/smoke-b
plan. Three synthetic consumers exercise the actual module/root; no AWS
infrastructure or GitHub repositories are created by this runbook.

## Requirements

- Free LocalStack Hobby entitlement and LOCALSTACK_AUTH_TOKEN supplied through
  the local environment. Do not purchase/activate a trial or commit the token.
- Docker running, AWS CLI v2, pinned Terraform, and locked platform dependencies.
- Loopback port 4567 available; existing services on 4566 remain untouched.
- Account-prefixed S3 Control hostname
  `000000000000.localhost.localstack.cloud` resolves to 127.0.0.1.
  If local DNS cannot resolve it, arrange an explicit local DNS/hosts entry;
  the runner diagnoses this but does not edit system configuration.

The user confirmed Hobby access. The installed image distribution is labeled
pro; that label is not proof of a paid entitlement. The runner uses only
free-supported S3/S3 Control/IAM/STS/DynamoDB operations. The pinned multi-architecture
image reference lives in `.localstack-image`. No Docker socket or persistent
volume is mounted into the test container.

## Run from the platform

```bash
make test-consumers
make test-localstack
```

The first command is credential-free and uses native mocks. The second starts
its own labeled ephemeral container, performs real provider operations against
that emulator, and cleans its synthetic resources and container in finally.
No separate up/down commands are necessary.

To test the actual sibling consumers together, the directory names must match
the team identities. A default `git clone` produces `team-payments`, so clone
with an explicit alias:

```bash
git clone https://github.com/bhavyakeniya/terraform-platform-abstraction.git terraform_platform_abstraction
git clone https://github.com/bhavyakeniya/team-payments.git   payments
git clone https://github.com/bhavyakeniya/team-customers.git  customers
git clone https://github.com/bhavyakeniya/team-accounting.git accounting

cd terraform_platform_abstraction
uv run python -m scripts.localstack_check \
  --consumer-dir ../payments \
  --consumer-dir ../customers \
  --consumer-dir ../accounting
```

From an individual sibling folder, use `make check` and `make localstack`.
For a consumer checked out under a different directory name, supply its stable
identity explicitly with `--team-id payments --consumer-dir /path/to/consumer`.
That override requires exactly one consumer directory.

## What happens

The runner validates each declaration and consumer expectations before starting
Docker. It sanitizes AWS/Terraform child environments, verifies the synthetic
account, copies the real root/module with the committed locks, and bootstraps dedicated per-team S3 state buckets and DynamoDB lock tables.
Workloads use real S3 backends, separate environment keys and separate data
directories. Only disposable provider/backend endpoint settings change;
production source is not edited.

All nine team/environment declarations are exercised. Backend checks read
versioning, encryption and access controls, inspect state-object versions and
encryption, hold a synthetic DynamoDB lock to reject a real Terraform plan, and
prove other environment/team states remain usable.

Baseline checks compare exact names, counts, tags, bucket controls, trust and
permissions policies with API responses. Lifecycle checks cover synthetic object
roundtrips, reordering, owner edits, additions, the approved public bucket's
visibility transitions, nonempty-bucket deletion failure, recovery, and final
no-change plans. Cleanup includes object versions and delete markers, inspects
per-object deletion errors, destroys resources through Terraform, and checks
absence before deleting the run-owned container.

See [consumers.md](consumers.md) for architecture and CI setup. Evidence is kept
under `.runs/localstack/<run-id>/evidence.json`; [verification.md](verification.md)
records completed runs. Raw plans/state remain private and ignored.

## Failure handling

- A failed assertion is failure, not a reason to disable a module control.
- A missing prerequisite is not a passing integration result.
- Preserve primary and cleanup errors. An expected BucketNotEmpty test must
  specifically observe that error and reconcile successfully afterward.
- A leftover tfp-consumer-localstack container must be inspected for its run
  label before an operator removes it. Never delete arbitrary existing services.
- Container reset is not proof of successful Terraform destroy.
- Concurrent local invocations fail instead of sharing fixture names or state.
- Do not print container environments or resolved Compose configuration; tokens
  belong only in the local secret environment.

## Evidence limits

The free tier does not establish effective IAM policy enforcement, anonymous
public/private denial, or TLS enforcement. Policy readback is configuration
verification, and object operations use emulator bootstrap credentials. Real
AWS authorization remains UNVERIFIED. S3/DynamoDB backend isolation and locking
are exercised in the emulator; see the latest recorded results in verification.md.
This does not prove real AWS permissions or 300 real AWS deployments.

Official references: [Hobby capabilities](https://docs.localstack.cloud/aws/licensing/),
[auth tokens](https://docs.localstack.cloud/aws/getting-started/auth-token/),
[Terraform integration](https://docs.localstack.cloud/aws/connecting/infrastructure-as-code/terraform/).

The ephemeral backend root keeps local bootstrap state inside the run directory;
team workload states reside in emulated S3. Workload destruction is verified
before backend fixture cleanup. Production `prevent_destroy` protections remain
in source; only the run-owned emulator's backend versions/tables are removed via
API before its container is discarded. No production backend destroy is implied.

## Shorter backend feedback loop

For bootstrap, baseline apply, policy/control readback, S3 state encryption/versioning,
DynamoDB contention, no-change reapply and cleanup, skip extended mutations:

```bash
uv run python -m scripts.localstack_check \
  --consumer-dir ../payments --team-id payments --baseline-only
```

This checks all of that team's environments. Evidence explicitly labels the mode
`baseline-only` and lifecycle `NOT_RUN`; use the default full suite before a
release. The recorded three-team/nine-environment full run took about 20 minutes
on this machine; that is an observation, not a timeout or performance guarantee.
