# Teams, environments, state and delivery

Teams manage environment-specific JSON. The platform manages Terraform,
backends, identities, and the shared deployment workflow. This guide covers
platform enrollment and operations; start with [the team guide](consumers.md)
for everyday configuration changes.

The repositories are public and their credential-free CI runs on GitHub.
Checked-in AWS accounts are fixtures with `deployment_enabled=false`; no real
AWS infrastructure has been provisioned. See [verification](verification.md)
for evidence and activation prerequisites.

## What lives where

| Platform path | Purpose |
| --- | --- |
| [config/environments/](../config/environments/) | Account, region, and deployment enablement per environment |
| [config/teams/](../config/teams/) | Approved repositories and workload/OIDC identities |
| [stacks/backends/](../stacks/backends/) | Operator-run backend and CI-identity bootstrap |
| [stacks/team/](../stacks/team/) | Workload root, run separately per team/environment |
| [Shared workflow](../.github/workflows/team-infrastructure.yml) | Checks, plan, and apply |

Teams keep their ID in `team.json` and declarations and expectations under
`environments/<env>/`. The directory, JSON environment, and platform catalog must
agree. Visibility is required for every bucket. Consumer JSON cannot select
accounts, backends, trust, endpoints, or executable Terraform; expectations are
business tests, not deployment authorization.

## State belongs to a team

Each team/account has one private state bucket and one DynamoDB lock table.
Its environments use separate state objects and lock keys:

| Item | Convention |
| --- | --- |
| State bucket and lock table | `sumup--tfstate--<account-id>--<team-id>` |
| State key | `workloads/<account-id>/<environment>/teams/<team-id>/terraform.tfstate` |
| CI role | `sumup-ci--<environment>--<team-id>` |

The account ID makes backend names deterministic across accounts. These names
remain globally visible; account IDs are identifiers, not secrets. Workload
bucket names omit the account ID.

- **Bucket:** versioning, SSE-S3/AES256 encryption, ownership enforcement, all
  public access blocked, TLS required, `force_destroy=false`, and Terraform
  deletion prevention. State versions do not expire automatically.
- **Lock table:** on-demand billing, `LockID` string key, encryption,
  point-in-time recovery, and AWS/Terraform deletion prevention.
- **Execution:** a fresh `TF_DATA_DIR` per job and the `default` workspace.
  A payments/dev lock does not block payments/prod or customers/dev.

See the [backend module](../modules/team-backend/README.md) for implementation
and [A12](assumptions.md#a12-encryption-choice) for the encryption decision.

DynamoDB locking is retained as requested, despite its upstream deprecation.
Before upgrading Terraform, review release notes and rerun contention tests.
A future S3-lockfile migration must drain writers, use dual locking during
transition, and move every writer before retiring DynamoDB. Never mix independent
S3-only and DynamoDB-only writers. See [Terraform's S3 backend documentation](https://developer.hashicorp.com/terraform/language/backend/s3).

## Onboard a team locally

Use [the scaffold and local-check instructions](consumers.md#onboard-a-new-team).
The generator creates dev/staging/prod declarations, expectations, a Makefile,
and a workflow template. It creates no GitHub repositories or AWS resources and
refuses to overwrite an existing project. Its private `data` bucket is an example
to edit alongside the expectations file.

To generate an active GitHub caller, also supply
`--platform-repository bhavyakeniya/terraform-platform-abstraction` and
`--platform-ref '<reviewed-40-character-SHA>'`. For an existing template, replace
`PLATFORM_REPOSITORY` and `PLATFORM_REF`, then rename
`infrastructure.yml.template` to `infrastructure.yml`. The workflow reference and
platform checkout must use the same immutable SHA; branches and tags are rejected.

### Register the account and team

Before AWS enrollment, confirm the authorized account/region, repository/default
branch, public-data policy, and existing workload role for each environment.
Verify the actual GitHub OIDC subject, including any subject customization;
do not infer it from the repository name. All identities below are examples.

Set `config/environments/dev.json`, keeping deployment disabled during bootstrap:

```json
{
  "account_id": "123456789012",
  "region": "eu-central-1",
  "deployment_enabled": false
}
```

Add `config/teams/payments.json`:

```json
{
  "repository": "YOUR-ACCOUNT/team-payments",
  "environments": {
    "dev": {
      "oidc_subject": "repo:YOUR-ACCOUNT/team-payments:environment:dev",
      "trusted_principal_arn": "arn:aws:iam::123456789012:role/payments-dev-app"
    }
  }
}
```

Register each environment the team will use. Workload principals must already
exist, be distinct per team/environment, and be same-account role ARNs without
role paths. Deployment validates the caller repository and registration before
authentication; CI role ARNs are derived rather than supplied by teams.

### Bootstrap backends and CI identities

An operator must configure the account's GitHub OIDC provider first. Use the
pinned Terraform version and verify the authenticated account before initializing.
In a restricted, encrypted platform checkout dedicated to that account, render
inputs from the registrations and prepare a saved bootstrap plan:

```bash
uv run python -m scripts.bootstrap_inputs --account-id '<actual-account-id>' \
  --out .runs/bootstrap/inputs.tfvars.json

BOOTSTRAP_INPUTS="$PWD/.runs/bootstrap/inputs.tfvars.json"
BOOTSTRAP_PLAN="$PWD/.runs/bootstrap/bootstrap.tfplan"
terraform -chdir=stacks/backends init -lockfile=readonly
terraform -chdir=stacks/backends plan \
  -var-file="$BOOTSTRAP_INPUTS" -out="$BOOTSTRAP_PLAN"
terraform -chdir=stacks/backends show "$BOOTSTRAP_PLAN"
```

Review the generated inputs and plan privately. After explicit approval, apply
that saved plan:

```bash
terraform -chdir=stacks/backends apply "$BOOTSTRAP_PLAN"
```

This creates the team bucket/table and each environment's CI role and workload
boundary. Rendering makes no AWS calls; team workflows never run this bootstrap.

Bootstrap state starts locally to avoid a circular dependency. Back it up and
migrate it to an independently managed private platform backend before shared
operation. Never commit it or store it in a team's backend.

### Enable AWS delivery

Protect the consumer default branch and each GitHub environment. Restrict
environment access to that branch and configure required reviewers where
available. Then enable the catalog entry, release a reviewed platform SHA, and
update the consumer's matching workflow and checkout pins.

In an authorized sandbox, dispatch plan, then apply, then a no-change plan.
Verify effective permissions, public/private access, TLS, locking, and recovery
before production use; see [verification boundaries](#verification-boundaries).

## CI/CD: what actually happens

Teams maintain JSON and a small caller pinned to the shared platform workflow.
Checkout, authentication, and Terraform execution are implemented centrally;
teams adopt workflow updates by reviewing and changing that pin.

| Trigger | Behavior |
| --- | --- |
| Pull request or push to the default branch | Validate every environment and its expectations, then run mocked Terraform tests. No AWS credentials. |
| Manual `mode=check` | Run the same checks; optionally add `localstack=true` for [emulator integration](localstack.md#run-from-github-actions). |
| Manual `mode=plan` | Create an AWS plan for the selected environment. |
| Manual `mode=apply` | Create a fresh saved plan and apply it in the same job. |

### Environment selection

Automatic checks validate **all** configured environments. Manual plan/apply runs
use the environment chosen in the dispatch. Environments are discovered from
the team's directories; there is no fixed dev/staging/prod matrix. Removing one
requires an approved [retirement receipt](#add-or-retire-an-environment).

### Deployment safeguards

AWS jobs require platform enrollment and the consumer's default branch. The
generated caller assumes `main`; change its push trigger for another default
branch. Configure GitHub environment branch restrictions before enabling OIDC.
Short-lived credentials are scoped per team/environment; see
[CI identity permissions](../modules/team-ci/README.md).

DynamoDB locks protect state. GitHub serializes deployments per repository,
team, and environment with `cancel-in-progress=false`; pending runs can still
be superseded. Deletion or replacement also requires `allow-destroy=true`.
With `force_destroy=false`, populated buckets cannot be silently emptied.

**Plan approval:** apply creates a fresh plan and immediately applies it.
An earlier plan-only run is advisory. Dispatch authorizes the current reviewed
default-branch configuration; there is no pause to approve the new plan.

Public summaries contain resource addresses and actions only. Plans, state, and
provider diagnostics remain private. See [state recovery](operations.md#private-state-recovery)
for failed writes and emergency-state handling.

**Advanced: automatic plans.** Custom callers can request `mode=plan` on push;
the published callers request `check`. For automatic plans, the change selector
chooses edited environments, all environments for `team.json`, `Makefile`, or
`.github/` changes, and none for documentation-only edits. Apply remains manual.

## Add or retire an environment

### Add

1. Add `config/environments/qa.json` with the catalog's three fields.
2. Add `environments/qa/resources.json` with `"environment":"qa"` and its
   expectations to the team repository.
3. Register its workload/OIDC identities, configure the protected GitHub
   environment, and bootstrap the CI binding before enabling AWS delivery.

Teams may use any nonempty subset of catalog environments. Names use the
lowercase identifier rules and are at most eight characters. All catalogs for
one account must share its backend region; another account gets separate backend
resources. Changing a live account or backend region requires migration.
Workload names must also remain globally unique across accounts.

### Retire

1. Close deployment admission, drain applies and workload writers, and follow
   [offboarding](offboarding-procedures.md) for the exact team/environment.
   Preserve inventory, the owner's decision, state, and backend version history.
2. Before removing the team's last binding in an account, add this field to its
   registration so bootstrap retains the bucket and table:

   ```json
   {
     "retained_backends": [
       {"account_id": "123456789012", "region": "eu-central-1"}
     ]
   }
   ```

   An empty `environments` map is allowed only with retained backends.
3. Remove/revoke the CI binding after sessions and recovery have been handled.
   Review the bootstrap removal plan, including retained-role boundary
   dependencies, before applying it.
4. Remove the consumer directory and add `retired-environments/qa.json` in the
   same reviewed change:

   ```json
   {
     "team_id": "payments",
     "environment": "qa",
     "completed": true,
     "ticket": "CHG-123",
     "approved_by": "platform-owner"
   }
   ```

   The receipt records manual approval; it does not prove AWS resources are gone.
   Missing receipts stop change discovery. Deleting JSON never triggers destroy.
5. Remove a platform catalog only after every team has retired that environment
   and all registrations and writers are reconciled. Preserve backends while
   any environment or required recovery history remains.

## Moving existing state

Live backend migration is a separate operator change:

1. Freeze and drain writers; back up the old state and inspect its inventory
   and lineage.
2. Create the team backend and initialize the **old** backend in a fresh private
   directory.
3. Switch to the rendered destination with `terraform init -migrate-state`.
   `-reconfigure` does not copy state.
4. Inspect the copied state and require a no-change plan before enabling the new
   workflow. Update permissions and retire old writers together.

Never apply from an empty new backend to adopt existing assets. Onboarding does
not migrate state automatically; current demo state is disposable emulator state.

## Shared resources and scale

Teams share platform code, workflows, tests, and operator-managed identity/backend
modules. They do not gain access to another team's data or state. Future shared
VPC/KMS resources should expose approved read-only identifiers rather than entire
state files.

Each workflow runs at most three environment jobs concurrently. In one account,
300 teams × three environments × two roles (CI and workload) requires **1,800
roles**, plus existing roles. Check [IAM quotas](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_iam-quotas.html),
S3 capacity, runner concurrency, and AWS API throttling before rollout.

The 300-team/900-binding test proves configuration scale; it does not establish
AWS capacity or production run times.

## Verification boundaries

[Testing](team-repo-tests.md) covers credential-free checks; [LocalStack](localstack.md)
covers emulator integration. [Verification](verification.md) records the source
snapshots tested and outstanding AWS acceptance.

AWS acceptance must cover OIDC and environment protection, backend and lock
permissions, cross-team/environment denials, workload boundaries, public/private
and TLS behavior, wrong-account rejection, no-change reapply, and state recovery.

## CI permission mapping audit

The [CI identity reference](../modules/team-ci/README.md#policy-checks) owns the
action inventory, whole-policy checks, and provider/API source references.
