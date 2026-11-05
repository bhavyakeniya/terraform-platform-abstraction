> Current delivery entry point: [environments-and-delivery.md](environments-and-delivery.md).
> The operator recovery procedures below also apply to each separate environment.

# Operations

Everything in this document describes **operator procedure that has never been
executed against AWS**, except the two sections marked otherwise. Parts of it
are now implemented — the delivery workflow and `scripts/deploy.py` perform the
plan/apply steps — but no run has touched a real account, and nothing here
should be read as evidence that a deployment has happened. Real execution needs
a real AWS account (G-AWS), the intended workload trust principal (G-IDENTITY),
and named public-access approval, none of which exist yet. See
[verification.md](verification.md) for those gates.

## Real plan/apply procedure (documented now, activated pass two)

1. Validate the declaration and context, and obtain authorization. Reject
   synthetic/fixture targets (`000000000000`, the fixture ARN, etc. are
   test-only and must never reach a real backend). Verify the actual
   authenticated account/principal with a read-only STS call *before*
   backend initialization — zero AWS calls cannot detect wrong credentials.
2. Initialize that exact team's state in a fresh directory with explicit
   variables and backend configuration. Team data can never select
   executable code, a backend key, or provider options — those come only
   from platform configuration.
3. Produce a refreshed saved plan. Detailed exit codes: `0` no change, `2`
   changes, `1` error. Raw plans and state are private — never printed in
   full, never committed.
4. A human reviews the saved plan for public exposure changes, IAM/trust
   changes, deletion, replacement, and context changes. No automatic
   destructive apply. Destructive changes require an explicit data-owner
   retain/destroy decision. Human review is sufficient for this release —
   no approval database or workflow is built.
5. Apply the reviewed saved plan only while its source/context are still
   current. Any change to input, source, or state invalidates the plan and
   requires a fresh one. A missed or superseded CI event is retried with a
   fresh plan, not replayed — nothing here promises automatic
   reconciliation.
6. Rely on Terraform's own state locking, plus non-cancelling concurrency
   per team (GitHub's `concurrency:` group is not a durable event queue —
   it only prevents two runs for the same ref from overlapping). An
   already-admitted writer is allowed to finish persisting state before any
   ordinary credential revocation or maintenance begins.
7. Reapply and require a refreshed no-change plan (`exit 0`) as the
   idempotence check. If state persistence fails after a real mutation,
   preserve whatever recovery state exists privately and stop for reviewed
   recovery — never blindly retry, and never force-push state.

## Backend provisioning and delivery

The platform operator uses `stacks/backends` to provision one private, versioned,
AES256-encrypted state bucket and protected DynamoDB lock table per team/account.
Both use `sumup--tfstate--<account-id>--<team-id>`. Each environment has its own
state key and exact lock/checksum rows. CI identities are scoped per environment;
workload roles get no backend access. Bootstrap state is separate privileged
platform state, not a team's workload state.

The deployment path uses `encrypt=true` and `dynamodb_table`, with fresh
initialization per job. Never mix locking mechanisms on one state without a
coordinated migration: if S3 native lock files (`use_lockfile`) are adopted
later, every writer of that state must switch at the same time.

See [the environment/delivery guide](environments-and-delivery.md) for bootstrap,
OIDC enrollment, shared plan/apply, backend migration, DynamoDB deprecation and
AWS acceptance. The code is implemented; live activation remains disabled until
real account/repository identities and protected environments are configured.

## Public-control prerequisites

Before approving any team's first public bucket, inspect — with
read-only, non-mutating calls — the account/organization-level S3 Block
Public Access configuration and any Service Control Policies that might
override a bucket-level setting. This module never changes account-wide
public-access settings; it can only configure the bucket-level controls
described in the module README. If a higher-level control already blocks
public access, that is an **unmet prerequisite**, not a failing
implementation — do not work around it from inside the module. If the
read-only identity available can't actually see that configuration, ask
for the specific evidence needed rather than assuming either permission
or exposure.

## Drain-before-revoke (emergency and ordinary revocation)

Not implemented in this release — documented so a real second-pass
implementation has a specified target, and so the adversarial finding it
answers is traceable: revocation prevents state persistence.

The failure this guards against: an operator revokes a deployer's
credentials or trust mid-apply, and the in-flight `terraform apply` is
killed before it can persist state — leaving real AWS resources that exist
but that Terraform's own state file doesn't know about.

The rule: **never revoke access to an identity that might be mid-apply
without first confirming it has finished.** Concretely, before revoking:

1. Close new admission (stop any new plan/apply from starting for that
   context).
2. Check for an active writer. If one exists, wait for it to finish
   persisting state and its receipt, or confirm — through the recovery
   procedure below — that it has genuinely crashed rather than merely
   being slow.
3. Only then revoke trust/credentials.

An emergency (compromised credentials, must revoke *now*) skips the wait
but must still run state-recovery/reconciliation immediately afterward,
treating any resources the dead apply might have created as unknown until
inventoried.

## Removal, retention, and versioned cleanup

Removal is **detected, never acted on**. `scripts/consumer_matrix.py`
fails closed when an `environments/<env>/` directory disappears from a team
repository: the change is rejected unless a matching
`retired-environments/<env>.json` receipt exists carrying the team ID,
environment, completion flag, ticket and approver
(`tests/test_environments.py`). Detection does **not** destroy anything —
detection and destruction are deliberately separate operations, so a
directory deletion in a PR can never trigger data loss by itself.

After removal detection, an authorized operator drains the team's deployer
and separately stops workload writers, then follows one of two reviewed manual
procedures. This requires the existing root, not a new Terraform stack or an
implemented `retire` command —

- **Retain**: convert all of the team's buckets to private (if not
  already), revoke the workload role's trust, but leave the buckets and
  their data in place.
- **Destroy**: after an explicit data-owner decision, run reviewed
  destruction. `force_destroy = false` is set on every bucket
  unconditionally (`modules/team-resources/buckets.tf`) — it only blocks
  deletion of a *nonempty* bucket, so it is not itself a safety mechanism,
  only a guard against an accidental one-line Terraform change silently
  deleting populated data. Emptying a versioned bucket requires explicitly
  paginating and deleting every noncurrent version and delete marker —
  `aws s3 rm --recursive` does not do this.

## Private state recovery

Every real invocation gets a fresh `.runs/<run-id>/<team-id>/` working
directory and its own `TF_DATA_DIR` — never reused across teams, never
reused across runs, and locking is never disabled to work around a stuck
process. If a real apply is interrupted after mutating AWS resources but
before state persistence completes, the documented recovery path
(Section 3.6 step 7) is: preserve whatever local recovery artifacts exist,
do not retry blindly, and do not push a guessed state file — an operator
reconciles the real resource inventory against state by hand (or via
`terraform import`) before any further plan is trusted.

## Offboarding runbook (bonus, manual)

This is the operator's sequence for what "removing a team" means in this
release — a manual runbook, not automation, consistent with B02's scope
("offboarding — bonus"). For the full set of data-fate options (retain,
archive, transfer, export-then-destroy, destroy) and when to pick each,
see [team-lifecycle.md](team-lifecycle.md) — this runbook assumes that
decision has already been made. [offboarding-procedures.md](offboarding-procedures.md)
provides retain/destroy procedures and treats archive, cross-team transfer,
and export as conceptual options requiring separate plans.

1. **Detect.** A PR removing an `environments/<env>/` directory (or the
   whole team repository) is opened. `consumer_matrix` fails the run unless
   an approved retirement receipt accompanies it, rather than silently
   treating the deletion as a normal change.
2. **Decide.** The data owner picks one of the options in
   `team-lifecycle.md` — never inferred from the PR, never defaulted to
   destroy. Record which one before proceeding.
3. **Drain and select state.** Close new deployments, drain in-flight applies,
   and stop workload writers separately. Verify operator identity, initialize a
   fresh TF_DATA_DIR with the exact team's backend, and verify its inventory.
4. **Suspend access.** Apply reviewed privacy changes first, then block new
   workload role sessions and revoke or wait out existing ones. Record the
   manual trust exception and keep ordinary applies blocked: they would restore
   configured trust. Follow the detailed runbook's ordering and checks.
5. **Act on the decision.** Retain leaves buckets, role, data, and state in place.
   Destroy requires explicit approval, complete version/delete-marker cleanup,
   error inspection, a reviewed saved destruction plan, and verified absence.
   Archive, cross-team transfer, and export first require their own reviewed
   procedures; this runbook does not execute those migrations. Preserve private
   state/plan history and the decision record.
6. **Record.** Keep the manifest/CI run that detected the removal and the
   final action taken as the audit trail — this release has no dedicated
   receipt/evidence store, which is explicitly out of scope for this
   release.

Every step above after step 1 is a manual operator action in this release.
Nothing in this repository currently automates steps 2–6.
