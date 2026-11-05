> The environment/backend/delivery extension is described in
> [environments-and-delivery.md](environments-and-delivery.md), including its
> explicit manual-apply semantics, SSE-S3 choice, account-bearing private backend
> names, DynamoDB deprecation, bootstrap-state ownership and AWS verification gaps.

# Assumptions and design justifications

This document explains what the solution assumes, why those assumptions keep
the take-home focused, and what must change if they do not hold. It describes
the current implementation; it does not grant permission to deploy or declare
unverified behavior correct. See [verification.md](verification.md) for executed
checks and [operations.md](operations.md) for deployment prerequisites.

## Assignment requirements are not assumptions

One IAM role and at least one bucket per team, explicit public/private choices,
separate team state, consistent naming, and support for 300+ teams are assignment
requirements. The assignment permits mocked/described CI and tests without a
real AWS deployment. Tags and offboarding are bonus scope. The choices below
explain how this implementation interprets and delivers those requirements.

## Scope and execution assumptions

| ID | Assumption or deliberate choice | Justification | Limit or action if it does not hold |
| --- | --- | --- | --- |
| A01 | Release one delivers the abstraction and checking pipeline, using examples and synthetic fixtures; real onboarding/deployment is deferred. | Proves the module, declaration contract, and selection logic without inventing real identities or cloud access. | A declaration check does not create buckets. Real intake, deployment identity, and plan/review/apply require a separate implementation decision. |
| A02 | Each root invocation has one explicitly configured commercial AWS account, region, and environment. | Keeps provider configuration and execution context straightforward; no provider-alias or multi-region framework is needed for the exercise. | GovCloud/China/other partitions and independent regional copies are not supported by this implementation. Region syntax validation does not prove that a region exists or is enabled. |
| A03 | Team IDs are unique within the configured environment and remain stable. | The directory ID determines resource identities and the backend key; live deployments also require a platform-controlled repository/identity registration. | Renaming a team or bucket key is a reviewed migration, not an ordinary metadata edit. Changing account/environment also requires context and migration review. |
| A04 | Each team owns a separate repository holding one JSON declaration per environment, consumed through a shared platform workflow and CLI. | One declaration plus centralized execution avoids copied Terraform or provider implementations; teams may keep business expectations alongside, as `expectations.json`. | The three team repositories are published and their CI runs, but they are demonstration teams, not production onboarding. Ownership and review enforcement, and the process for rolling teams onto a newer platform pin, still require organizational decisions. |
| A05 | Platform code and platform configuration are controlled by trusted maintainers; declarations are treated as untrusted data. | Teams can request buckets without selecting executable code, trust, or backend state. Strict JSON/schema checks reject ambiguity and unsupported fields. | Validation does not stop a maintainer from changing the validator or workflow. Production needs protected review and a trusted execution boundary. The owner contact tag is metadata, not authenticated ownership. |
| A06 | Ordinary declaration checks can be superseded by newer runs. | The current workflow performs credential-free checks, so canceling an obsolete check is acceptable. | The separate delivery workflow uses non-cancelling per-team/environment concurrency plus DynamoDB locks. Manual dispatch authorizes a fresh plan and apply, not a previously approved plan artifact. |

## Naming and resource identity choices

Buckets use `sumup--<environment>--<team-id>--<bucket-key>`, for example
`sumup--dev--payments--reports`. Environment is at most 8 characters; team and
bucket key are at most 16 each. Components start with a lowercase letter and
allow lowercase letters, digits, and single hyphens. The maximum generated
length is 51 characters, leaving 12 below S3's 63-character limit.

| ID | Choice | Justification | Limit or action if it does not hold |
| --- | --- | --- | --- |
| A07 | Bucket names omit account IDs and extra uniqueness tokens. | Produces short, readable names and avoids embedding the account ID in the public naming surface. | Availability is not guaranteed in S3's shared global namespace. The same environment/team/key in another account or region requests the same name. A collision fails; there is no automatic import, takeover, random suffix, or truncation. Revisit naming before a multi-account/region rollout or if a required name is taken. |
| A08 | The `sumup` prefix is fixed for the exercise, and logical bucket keys are stable identities. | Enforces a consistent convention without exposing naming controls to teams. Map-based for_each avoids list-index churn. | Confirm an approved prefix before actual organizational deployment. Renaming existing buckets requires data migration; spare name capacity does not make renames safe. |
| A09 | IAM role names are `<environment>--<team-id>--s3`, with no company or tool prefix; state keys retain the account component. | S3 is a global namespace, so bucket names carry the `sumup--` prefix to reduce collisions. IAM is account-scoped, so a role needs no such prefix; grouping is done by the IAM path `/team-platform/runtime/<environment>/<team-id>/`. Environment and team still appear in the role name because [AWS requires friendly names to be unique within an account](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_identifiers.html) and the path does not provide that uniqueness. Account checks remain independent of readable names. | Renaming a role after deployment is a replacement, not an in-place update. Existing resources under an earlier name need migration review. |

## Security and workload assumptions

| ID | Assumption or deliberate choice | Justification | Limit or action if it does not hold |
| --- | --- | --- | --- |
| A10 | Public means anonymous HTTPS GET of current objects; it does not include listing, writes, deletion, or historical-version reads. | Gives public/private an explicit, narrow meaning that can be tested through generated policy assertions. | Public data is intentionally readable without role credentials. The own-bucket role boundary applies to requests made using that role, not anonymous requests. A CDN-only or authenticated delivery model would need a different contract. |
| A11 | An approved target can permit bucket-level public policies when a team requests public visibility. | Public buckets are required by the assignment, but the module should not change account/organization controls. | Confirm higher-level public-access restrictions and public-data approval before deployment. If those controls prohibit public access, stop and resolve the requirement; do not weaken them from this module. |
| A12 | SSE-S3 is the v1 default; customer-managed KMS keys are not an assignment requirement. | Provides explicit default encryption without introducing key lifecycle/policy dependencies; supports the direct anonymous-read model. | This is not a fintech compliance claim or approval for sensitive production data. Confirm classification and encryption policy. Bucket defaults alone do not prove every object/version uses AES256; integration checks must inspect actual uploaded objects. |
| A13 | Workloads need list/location and ordinary object get/put/delete operations only. | Keeps the generated role small and least-privileged for the stated task. | Multipart-upload administration, historical-version access/deletion, bucket administration, and KMS permissions are not included. Add actions only for an explicit workload requirement and test them. Object deletion is not a complete version-history purge. |
| A14 | The platform supplies an existing same-account IAM role as the workload trust principal. The live registration supplies one principal per team/environment; emulator fixtures share a synthetic principal. | Avoids wildcard/account-root trust and leaves identity bootstrap outside the resource module. | A shared source principal able to assume multiple team roles is not per-team identity isolation. Agree distinct workload identities/intake before a real multi-team rollout. Current ARN validation also excludes role paths; it does not support every valid IAM role ARN. Trust existence and effective authorization remain AWS verification tasks. |
| A15 | Deployment/bootstrap operators and workload roles are different identities. | Applications need data access, not IAM administration or state access. | Provider/backend account allowlists check caller context, not a complete authorization boundary. Production deployment permissions must be scoped independently; broad administrators can cross team boundaries. |

## State, scale, and lifecycle assumptions

| ID | Assumption or deliberate choice | Justification | Limit or action if it does not hold |
| --- | --- | --- | --- |
| A16 | The platform operator provisions a dedicated protected backend bucket/table per team/account before real team deployment. | State storage is bootstrap infrastructure and cannot depend on the workload state it stores. The helper derives a separate account/environment/team key. | An operator must verify bucket ownership, private access, encryption, versioning, recovery, and exact state/lock permissions. `stacks/backends` now provides backend and CI-identity bootstrap. Emulator contention and AWS authorization are different evidence layers. |
| A17 | Real invocations use isolated Terraform data directories and DynamoDB backend locking as requested. | Prevents accidental reuse of another team's initialized backend metadata and limits each state to one team. | Mock-only batching shares initialization for speed; it is not reused by the live deployment command. Do not generalize that optimization to team backend sessions. |
| A18 | 300+ teams means dynamic declarations and repeated isolated root executions, not 300 concurrent applies or unlimited buckets per team. | Each team repository selects only its own changed environments, so no hardcoded team list is needed and no single job fans out across teams. | Configuration scale tests do not prove AWS quotas, API throughput, or production run times. Verify account capacity before rollout. The inline-policy size guard bounds a team's practical bucket count; there is no invented fixed count limit. |
| A19 | Retention and destruction are explicit data-owner decisions; deletion of a declaration is not authorization to destroy data. | Prevents a small repository edit from becoming implicit data loss. Removal detection stops the ordinary path. | Retain/destroy are unexecuted manual procedures. Archive, transfer, and export require separate plans. Stop writers, handle issued sessions and version history, and review the exact team state before acting. |
| A20 | Versioning and force_destroy=false are useful safeguards, not complete retention or deletion protection. | Versioning preserves history; Terraform does not automatically empty populated buckets. | Empty buckets can still be deleted, authorized operators can delete versions, and retention/legal holds need separate decisions. No Object Lock, lifecycle retention, backup, logging, or compliance control is claimed by this module. |

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
- **LocalStack is optional integration evidence.** The older manual smoke
  run predates the current bucket naming contract. A later user-requested
  consumer harness now exercises the current module; that tier still does not
  establish IAM enforcement. See
  [verification.md](verification.md) and [localstack.md](localstack.md).
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

The deployed roots now restrict Terraform to 1.17.x and AWS provider to 6.x;
exact runtime/provider versions remain 1.17.1/6.71.0. Reusable modules keep their
broader compatibility ranges. Trivy and a dependency-locked Checkov environment
provide blocking independent rules on both CI paths. Scope exceptions and the
limits of source-graph evaluation are explicit in
[security-scanning.md](security-scanning.md). Scanner success is not regulatory
compliance or an AWS authorization test.
