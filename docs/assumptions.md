# Assumptions and design justifications

These decisions explain the implementation, its limits, and when the design
would need to change. See [verification.md](verification.md) for evidence and
[environments and delivery](environments-and-delivery.md) for operator procedures.

## Assignment requirements are not assumptions

One IAM role and at least one bucket per team, explicit public/private choices,
separate team state, consistent naming, and support for 300+ teams are assignment
requirements. Mocked or described CI and tests are permitted without a real AWS
deployment. Tags and offboarding are bonus scope.

## Scope and execution assumptions

### A01: Demo scope

**Decision:** The demo implements the abstraction, backend bootstrap, and
checking/deployment workflows using synthetic fixtures. Real AWS enrollment and
deployment remain disabled.

**Reason:** The assignment can be tested without inventing live identities or cloud
access.

**Limitation:** A declaration check creates no resources. Real use requires an
authorized account, registered identities, protected delivery, and AWS acceptance
tests.

### A02: One account and region per run

**Decision:** Each root invocation has one explicitly configured commercial AWS
account, region, and environment.

**Reason:** Keeps provider configuration and execution context straightforward; no
provider-alias or multi-region framework is needed for the exercise.

**Limitation:** GovCloud/China/other partitions and independent regional copies are
not supported by this implementation. Region syntax validation does not prove that a
region exists or is enabled.

### A03: Stable team identity

**Decision:** Team IDs are unique within the configured environment and remain
stable.

**Reason:** The stable team ID determines resource names and backend keys. Live
deployments also require a platform-controlled repository and identity registration.

**Limitation:** Renaming a team or bucket key is a reviewed migration, not an
ordinary metadata edit. Changing account/environment also requires context and
migration review.

### A04: Team-owned configuration

**Decision:** Each team owns a separate repository holding one JSON declaration per
environment, consumed through a shared platform workflow and CLI.

**Reason:** One declaration plus centralized execution avoids copied Terraform or
provider implementations; teams may keep business expectations alongside, as
`expectations.json`.

**Limitation:** The three team repositories are published and their CI runs, but
they are demonstration teams, not production onboarding. Ownership and review
enforcement, and the process for rolling teams onto a newer platform pin, still
require organizational decisions.

### A05: Trusted platform maintainers

**Decision:** Platform code and platform configuration are controlled by trusted
maintainers; declarations are treated as untrusted data.

**Reason:** Teams can request buckets without selecting executable code, trust, or
backend state. Strict JSON/schema checks reject ambiguity and unsupported fields.

**Limitation:** Validation does not stop a maintainer from changing the validator or
workflow. Production needs protected review and a trusted execution boundary. The
owner contact tag is metadata, not authenticated ownership.

### A06: Concurrent checks and deployments

**Decision:** Ordinary declaration checks can be superseded by newer runs.

**Reason:** The current workflow performs credential-free checks, so canceling an
obsolete check is acceptable.

**Limitation:** The separate delivery workflow uses non-cancelling
per-team/environment concurrency plus DynamoDB locks. Manual dispatch authorizes a
fresh plan and apply, not a previously approved plan artifact.

## Naming and resource identity choices

Buckets use `sumup--<environment>--<team-id>--<bucket-key>`, for example
`sumup--dev--payments--reports`. Environment is at most 8 characters; team and
bucket key are at most 16 each. Components start with a lowercase letter and
allow lowercase letters, digits, and single hyphens. The maximum generated
length is 51 characters, leaving 12 below S3's 63-character limit.

### A07: Readable bucket names

**Decision:** Bucket names omit account IDs and extra uniqueness tokens.

**Reason:** Produces short, readable names and avoids embedding the account ID in
the public naming surface.

**Limitation:** Availability is not guaranteed in S3's shared global namespace. The
same environment/team/key in another account or region requests the same name. A
collision fails; there is no automatic import, takeover, random suffix, or
truncation. Revisit naming before a multi-account/region rollout or if a required
name is taken.

### A08: Naming prefix and stable bucket keys

**Decision:** The `sumup` prefix is fixed for the exercise, and logical bucket keys
are stable identities.

**Reason:** Enforces a consistent convention without exposing naming controls to
teams. Map-based for_each avoids list-index churn.

**Limitation:** Confirm an approved prefix before actual organizational deployment.
Renaming existing buckets requires data migration; spare name capacity does not make
renames safe.

### A09: Workload role names

**Decision:** Workload role names are `<environment>--<team-id>--s3`; grouping uses
`/team-platform/runtime/<environment>/<team-id>/`. State keys retain the account
component.

**Reason:** IAM names are account-scoped. Environment and team still appear in the
friendly name because a path does not provide name uniqueness; see [AWS
identifiers](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_identifiers.html).
Account ownership checks remain independent of names.

**Limitation:** Renaming a role after deployment is a replacement, not an in-place
update. Existing resources under an earlier name need migration review.

## Security and workload assumptions

### A10: What public means

**Decision:** Public means anonymous HTTPS GET of current objects; it does not
include listing, writes, deletion, or historical-version reads.

**Reason:** Gives public/private an explicit, narrow meaning that can be tested
through generated policy assertions.

**Limitation:** Public data is intentionally readable without role credentials. The
own-bucket role boundary applies to requests made using that role, not anonymous
requests. A CDN-only or authenticated delivery model would need a different
contract.

### A11: Account-level public access controls

**Decision:** An approved target can permit bucket-level public policies when a team
requests public visibility.

**Reason:** Public buckets are required by the assignment, but the module should not
change account/organization controls.

**Limitation:** Confirm higher-level public-access restrictions and public-data
approval before deployment. If those controls prohibit public access, stop and
resolve the requirement; do not weaken them from this module.

### A12: Encryption choice

**Decision:** SSE-S3 is the encryption choice; customer-managed KMS keys are outside
the assignment requirements.

**Reason:** Provides explicit default encryption without introducing key
lifecycle/policy dependencies; supports the direct anonymous-read model.

**Limitation:** This is not a fintech compliance claim or approval for sensitive
production data. Confirm classification and encryption policy. Bucket defaults alone
do not prove every object/version uses AES256; integration checks must inspect
actual uploaded objects.

### A13: Workload S3 permissions

**Decision:** Workloads need list/location and ordinary object get/put/delete
operations only.

**Reason:** Keeps the generated role small and least-privileged for the stated task.

**Limitation:** Multipart-upload administration, historical-version access/deletion,
bucket administration, and KMS permissions are not included. Add actions only for an
explicit workload requirement and test them. Object deletion is not a complete
version-history purge.

### A14: Workload trust

**Decision:** The platform supplies an existing same-account IAM role as the
workload trust principal. The live registration supplies one principal per
team/environment; emulator fixtures share a synthetic principal.

**Reason:** Avoids wildcard/account-root trust and leaves identity bootstrap outside
the resource module.

**Limitation:** A shared source principal able to assume multiple team roles is not
per-team identity isolation. Agree distinct workload identities/intake before a real
multi-team rollout. Current ARN validation also excludes role paths; it does not
support every valid IAM role ARN. Trust existence and effective authorization remain
AWS verification tasks.

### A15: Separate deployment and workload identities

**Decision:** Deployment/bootstrap operators and workload roles are different
identities.

**Reason:** Applications need data access, not IAM administration or state access.

**Limitation:** Provider/backend account allowlists check caller context, not a
complete authorization boundary. Production deployment permissions must be scoped
independently; broad administrators can cross team boundaries.

## State, scale, and lifecycle assumptions

### A16: Backend bootstrap

**Decision:** The platform operator provisions a dedicated protected backend
bucket/table per team/account before real team deployment.

**Reason:** State storage is bootstrap infrastructure and cannot depend on the
workload state it stores. The helper derives a separate account/environment/team
key.

**Limitation:** An operator must verify bucket ownership, private access,
encryption, versioning, recovery, and exact state/lock permissions.
`stacks/backends` now provides backend and CI-identity bootstrap. Emulator
contention and AWS authorization are different evidence layers.

### A17: Isolated Terraform runs

**Decision:** Real invocations use isolated Terraform data directories and DynamoDB
backend locking as requested.

**Reason:** Prevents accidental reuse of another team's initialized backend metadata
and limits each state to one team.

**Limitation:** Mock-only batching shares initialization for speed; it is not reused
by the live deployment command. Do not generalize that optimization to team backend
sessions.

### A18: Scaling to 300 teams

**Decision:** 300+ teams means dynamic declarations and repeated isolated root
executions, not 300 concurrent applies or unlimited buckets per team.

**Reason:** Each team repository runs the shared root for its own environments, so
adding a team needs no hardcoded team list or cross-team execution job.

**Limitation:** Configuration scale tests do not prove AWS quotas, API throughput,
or production run times. Verify account capacity before rollout. The inline-policy
size guard bounds a team's practical bucket count; there is no invented fixed count
limit.

### A19: Offboarding decisions

**Decision:** Retention and destruction are explicit data-owner decisions; deletion
of a declaration is not authorization to destroy data.

**Reason:** Prevents a small repository edit from becoming implicit data loss.
Removal detection stops the ordinary path.

**Limitation:** Retain/destroy are unexecuted manual procedures. Archive, transfer,
and export require separate plans. Stop writers, handle issued sessions and version
history, and review the exact team state before acting.

### A20: Data retention safeguards

**Decision:** Versioning and force_destroy=false are useful safeguards, not complete
retention or deletion protection.

**Reason:** Versioning preserves history; Terraform does not automatically empty
populated buckets.

**Limitation:** Empty buckets can still be deleted, authorized operators can delete
versions, and retention/legal holds need separate decisions. No Object Lock,
lifecycle retention, backup, logging, or compliance control is claimed by this
module.

## Verification and tooling choices

- **Native Terraform mocks are the default.** They exercise configuration,
  generated policies, validation, and root wiring without cloud credentials.
  Whole-policy and root-output assertions improve regression detection; they
  do not evaluate AWS's authorization engine or prove production idempotence.
- **Python handles the declaration/Git boundary.** The closed JSON contract
  gives early errors; Terraform repeats essential checks for direct consumers.
  Top-level nullable=false is not recursive collection validation, and typed
  Terraform objects are not a replacement for the closed JSON schema.
- **Provider lock files are authoritative for routine checks.** Make/helper
  initialization uses read-only locks, including CI paths. Dependency upgrades
  are separate reviewed changes; all committed roots/modules require compatible locks.
- **OPA is not required for this release.** Local module invariants live in
  Terraform validation/preconditions and tests. Independent organization-wide
  plan policy can be considered when multiple modules/deployment paths need it.
  Neither approach replaces AWS permission tests or a trusted enforcement point.
- **LocalStack is optional integration evidence.** The harness uses the AWS
  provider against emulated APIs; it does not establish AWS IAM enforcement.
  [Verification](verification.md) identifies the tested snapshots and remaining
  gaps; [the runbook](localstack.md) explains how to repeat the tests.
- **Live checks are not assumed green.** Publication/live GitHub CI, real AWS
  permissions, public access, backend locking, and real reapply are separate
  evidence layers. Their current status belongs in verification.md, not in an
  assumption that they will work because mocks passed.

## Questions to resolve before real deployment

1. What account, region, environment, backend bucket, and deployment identity
   are authorized? Are their quota, ownership, recovery, and locking prerequisites met?
2. Which actual principal should assume each team's workload role, and how will
   repository ownership/review prevent cross-team or platform-context changes?
3. Which bucket keys may expose public data? Do naming, classification, encryption,
   and account/organization controls permit the proposed configuration?
4. Do workloads require additional S3 operations, historical-version access,
   KMS, audit logging, retention, or backup beyond the assignment's scope?
5. Who approves plans and offboarding decisions, handles existing sessions,
   reconciles partial failures, and verifies retention/export before destruction?

These are unresolved deployment facts, not facts inferred from the role's job
description. Keep current approvals and evidence in [verification.md](verification.md)
and follow [offboarding-procedures.md](offboarding-procedures.md) for the manual
retain/destroy procedure. Revisit the affected assumptions when requirements change.

## Independent scanning and pinned deployment roots

Deployment roots constrain the Terraform minor and AWS provider major; reusable
modules allow a broader range. See [root version intent](security-scanning.md#root-version-intent)
for constraints and upgrade rules. The same guide records the Trivy/Checkov
gates and their scope exceptions. Scanner success does not establish regulatory
compliance or effective AWS authorization.
