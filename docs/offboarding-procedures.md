# Manual offboarding: retain or destroy

[team-lifecycle.md](team-lifecycle.md) explains the team's choices. This
runbook provides manual retain/destroy procedures using the existing generic
root. Archive, cross-team transfer, and export are conceptual options below,
not executable migration procedures. No additional Terraform stack is required.

**Status:** documented for a future authorized AWS deployment; not executed or
validated against AWS. Nothing in this repository automates offboarding beyond
fail-closed removal detection. Commands below are operator templates: replace placeholders,
review the actual state and plans, and stop on unexpected results.

## 1. Prepare the exact team's state (both paths)

1. Record the approved team/account/environment, data owner, retain/destroy
   decision, and retention obligations. Use a privileged operator identity with
   access to that team's backend and resources, not the workload role. Confirm
   that identity with STS before initializing any backend. Do not use fixture
   configuration, synthetic accounts, or an unreviewed current configuration.
2. Close admission for that team's deployments and drain in-flight Terraform
   operations, following [operations.md](operations.md#drain-before-revoke-emergency-and-ordinary-revocation).
   Stop workload writers separately; draining deployments does not stop object
   uploads. Keep both stopped through completion. Check Object Lock, legal holds,
   replication, and other writers before choosing destruction; unresolved
   retention or access questions stop the procedure.
3. Select the reviewed declaration revision and platform configuration matching
   the last successful deployment. Recover the declaration from that explicit
   revision, not an assumed parent of a removal commit. Compare its bucket keys,
   account, environment, principal, and backend key with deployment records.
4. From repository root, use one shell and a fresh private run directory:

   ```bash
   set -euo pipefail
   umask 077
   REPO="$PWD"
   TEAM_ID='<approved-team-id>'
   ENVIRONMENT='<approved-environment>'
   TEAM_REPOSITORY='<github-owner/repository>'
   # Check out the reviewed team revision in a separate private directory.
   CONSUMER_DIR='/absolute/path/to/reviewed-team-checkout'
   # Select the installed pinned Terraform executable.
   TF_BIN="$REPO/.local/bin/terraform"
   # If installed on PATH instead, set TF_BIN to its absolute path.
   mkdir -p "$REPO/.runs"
   RUN_DIR="$(mktemp -d "$REPO/.runs/offboard.XXXXXXXX")"
   export TF_DATA_DIR="$RUN_DIR/terraform-data"

   aws sts get-caller-identity --no-cli-pager
   uv run python -m scripts.deploy prepare \
     --consumer-dir "$CONSUMER_DIR" --team-id "$TEAM_ID" \
     --environment "$ENVIRONMENT" --repository "$TEAM_REPOSITORY" \
     --out "$RUN_DIR/rendered"
   cp "$RUN_DIR/rendered/inputs.tfvars.json" "$RUN_DIR/original-inputs.json"
   ```

   Verify the STS account/principal and rendered backend bucket/key/region against
   the approved target. Confirm the AWS CLI and Terraform use the same operator
   credential source; clear unintended profiles, endpoint overrides, or Terraform
   variable/CLI overrides. Never print credentials or reuse another team's
   initialized directory. Use the reviewed root/module revision compatible with
   the deployed state; reconcile any difference before continuing. Keep the
   catalog/identity registration available for this final rendering; close new
   admissions through repository/workflow controls and drain writers before
   disabling or removing registrations.
5. Initialize explicitly, then verify the selected state:

   ```bash
   "$TF_BIN" -chdir=stacks/team init -input=false -lockfile=readonly \
     -backend-config="$RUN_DIR/rendered/backend.hcl.json"
   "$TF_BIN" -chdir=stacks/team state list
   "$TF_BIN" -chdir=stacks/team state pull > "$RUN_DIR/state-before.json"
   ```

   Inspect resource identities privately and compare their bucket/role names to
   the approved team. Missing, empty, foreign, or unexpected state is a stop
   condition. Do not migrate/import state or disable locking to get past it.
   Rendered variables alone never select a backend. Preserve state/plan artifacts
   privately; do not commit them. Reuse this same shell and TF_DATA_DIR below.

## 2. Retain / suspend

1. Preserve `original-inputs.json`. Edit only each bucket's visibility in
   `RUN_DIR/rendered/inputs.tfvars.json` to `private`; preserve all bucket keys,
   owner, account, environment, trust and permissions boundary. This private
   operator copy intentionally bypasses consumer expectations that may require
   a public fixture. Do not edit the reviewed team checkout or backend config.
   Confirm only visibility values changed before planning.
2. Plan and review the privacy changes:

   ```bash
   "$TF_BIN" -chdir=stacks/team plan -input=false \
     -var-file="$RUN_DIR/rendered/inputs.tfvars.json" -out="$RUN_DIR/retain.tfplan"
   "$TF_BIN" -chdir=stacks/team show "$RUN_DIR/retain.tfplan"
   # After review: only expected public-access controls/policies may change.
   "$TF_BIN" -chdir=stacks/team apply -input=false "$RUN_DIR/retain.tfplan"
   ```

   Reject bucket/role creation, deletion, replacement, or unrelated drift. Verify
   all four public-access-block flags are true and anonymous-read grants are
   absent for each bucket. Inventory the retained data without modifying it.
3. **After the Terraform changes**, block new workload sessions by replacing the
   workload role's trust policy with an explicit deny for sts:AssumeRole, using
   the IAM console under the authorized operator identity. Save the old trust
   policy privately, verify the role ARN and deny policy, and record the change.
   Keep the role and its inline policy; no targeted Terraform destroy is needed.
4. Revoke or wait out already-issued workload sessions using the organization's
   approved procedure. Stopping workloads or changing trust alone does not
   invalidate existing sessions.
   When using AWS session revocation, follow the [IAM procedure](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_revoke-sessions.html)
   and record any extra revocation policy. Verify workloads can no longer access
   retained data; failure or inconclusive evidence means suspension is incomplete.
5. Record retained bucket/role identities, private-access readback, session handling,
   owner, and retention/review date. Keep the team's state and data.

The trust change (and any session-revocation policy) is a deliberate manual
exception to Terraform's declared configuration. Keep deployment admission
closed and record it: a normal apply would restore the configured trust. Do not
claim a no-change plan after this manual exception or add ignore_changes to hide
it. If revocation is needed before the privacy apply, coordinate an equivalent
reviewed access block; the apply must not accidentally restore access.

**Resume:** obtain authorization, review/remove temporary revocation controls,
restore the declaration, and produce a fresh reviewed plan for the retained
state. Restore only approved visibility/trust, verify access, then reopen
admission. Current CI only checks declarations; re-adding a file does not apply
anything automatically.

## 3. Destroy

1. Obtain explicit approval to permanently delete **all versions and delete
   markers**, including required backup/export acceptance and absence of legal
   holds. Complete the retain procedure first so buckets are private and new
   workload access is blocked; confirm existing sessions and other writers have
   been stopped. Do not remove retention controls to bypass a failure.
2. Empty only the inventoried team buckets with the authorized operator tooling
   or S3 console. Include every current/noncurrent version and delete marker;
   aws s3 rm --recursive is insufficient. For CLI tooling, list bounded pages
   with ListObjectVersions, include key/version IDs, and delete at most 1,000
   entries per DeleteObjects request. Inspect each response's per-object Errors
   even when the command succeeds. Stop on any failed deletion or non-progress;
   do not use an unbounded retry loop. Repeat until a fresh complete listing is
   empty. Abort any remaining multipart uploads and keep writers stopped.
3. Capture the cleanup results and verify every bucket is empty before planning
   destruction. Stop if authorization, retention, or inventory is uncertain.
4. Review and apply a saved destruction plan using the same initialized state:

   ```bash
   "$TF_BIN" -chdir=stacks/team plan -destroy -input=false \
     -var-file="$RUN_DIR/rendered/inputs.tfvars.json" -out="$RUN_DIR/destroy.tfplan"
   "$TF_BIN" -chdir=stacks/team show "$RUN_DIR/destroy.tfplan"
   # After review: deletes exactly the inventoried team's managed resources.
   "$TF_BIN" -chdir=stacks/team apply -input=false "$RUN_DIR/destroy.tfplan"
   ```

   Any changed input, source, context, or state requires a new reviewed plan.
   Never use auto-approve, force-unlock, or force_destroy to bypass a failure.
5. Verify the selected state has no managed resources and check the known role
   and each known bucket are absent using the authorized operator identity.
   An access-denied/network response is not evidence of deletion. Preserve the
   backend state history, private plan/state backups, decision, and verification
   record. If an apply partially fails, preserve evidence and reconcile observed
   resources against state before another attempt; do not assume rollback.

## 4. Other options: design a separate procedure first

- **Archive:** agree retention, retrieval time, cost, and current/noncurrent-version
  handling. Review and preserve existing lifecycle rules before any change:
  PutBucketLifecycleConfiguration replaces the entire configuration. The module
  does not manage archival transitions. No archive execution recipe is supplied.
- **Transfer:** a same-team owner-contact edit is an ordinary declaration change.
  A new team ID requires a migration plan: destination resources, stopped writes
  or an explicit cutover boundary, full key/version inventory, metadata and
  checksum verification, and a decision on historical versions/delete markers.
  Counts or sampled ETags alone are insufficient. Do not destroy the source
  until the owner accepts the verified result. No copy/delete recipe is supplied.
- **Export, then destroy:** first define recipient, scope (including history),
  secure destination/access, cutover, integrity verification, and acceptance.
  After a separately reviewed export completes, follow the destroy procedure.
  A successful sync command alone is not acceptance evidence.

## References

- [Terraform backend initialization](https://developer.hashicorp.com/terraform/language/backend)
- [Terraform saved plans and destroy mode](https://developer.hashicorp.com/terraform/cli/commands/plan)
- [S3 version inventory](https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListObjectVersions.html)
- [S3 batch deletion limits and per-object errors](https://docs.aws.amazon.com/AmazonS3/latest/API/API_DeleteObjects.html)
