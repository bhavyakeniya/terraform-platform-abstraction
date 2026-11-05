# Teams, environments, state and delivery

Teams own JSON. The platform owns Terraform, backend provisioning, AWS identity
rules, validation, and the plan/apply implementation. A team does not fork
Terraform or write its own deployment scripts.

The checked-in AWS accounts are **fixtures**, and `deployment_enabled` is false.
The platform and the three team repositories are published and their
credential-free checks run on GitHub. No real AWS infrastructure has been
provisioned: OIDC/AWS acceptance still requires a real account, registered
identities and protected environments.

## What lives where

```text
terraform_platform_abstraction/
  config/environments/{dev,staging,prod}.json  # account/region, deployment enablement
  config/teams/<team>.json                   # platform-approved repo and identities
  modules/team-resources/                    # workload S3 buckets and S3-only role
  modules/team-backend/                      # private state bucket and DynamoDB table
  modules/team-ci/                           # scoped OIDC CI role and workload boundary
  stacks/team/                              # one team/environment per invocation
  stacks/backends/                          # privileged platform-operated bootstrap
  .github/workflows/team-infrastructure.yml # shared workflow, maintained once
  scripts/onboard.py                         # creates a team project, not cloud resources

payments/                                   # separate team project/repository
  team.json                                 # {"team_id":"payments"}
  environments/
    dev/{resources.json,expectations.json}
    staging/{resources.json,expectations.json}
    prod/{resources.json,expectations.json}
  .github/workflows/infrastructure.yml       # small generated workflow caller
  Makefile                                  # generated check/localstack entry points
```

`customers` and `accounting` have the same structure. Environment configurations
are independent: teams can declare different buckets or visibility in each one.
`examples/minimal` and `examples/mixed` remain as low-level declaration
fixtures for the fixture-smoke and security-scan paths; all consumers use the
v2 structure.

A consumer declaration is explicit and closed:

```json
{
  "schema_version": 2,
  "environment": "dev",
  "owner": "payments@example.invalid",
  "buckets": {
    "receipts": {"visibility": "private"},
    "settlements": {"visibility": "private"}
  }
}
```

Put it in `environments/dev/resources.json`. The folder, JSON environment and
platform catalog must agree. No account, region, backend, role trust, endpoint or
Terraform source can be supplied in this file. Bucket visibility has no default.
The adjacent expectations file contains `required_buckets` and
`allowed_public_buckets`: business regression tests, not an authorization system.

Workload names remain `sumup--dev--payments--receipts`. They contain no account
number. Names still share S3's global namespace: a collision fails; there is no
silent import, takeover, suffix or truncation.

## State belongs to a team

One bucket and one lock table per **team/account**, shared only across that team's
environments in that account:

| Item | Convention / example |
| --- | --- |
| State bucket | `sumup--tfstate--<account-id>--<team-id>` |
| DynamoDB table | Same name as the team's state bucket |
| State key | `workloads/<account-id>/<environment>/teams/<team-id>/terraform.tfstate` |
| Example dev key | `workloads/123456789012/dev/teams/payments/terraform.tfstate` |
| Example prod key | `workloads/123456789012/prod/teams/payments/terraform.tfstate` |
| CI role | `sumup-ci--<environment>--<team-id>` |

The state-bucket name is at most 46 characters. The account component makes the
private backend destination deterministic across accounts. Account IDs are
identifiers, not secrets; their inclusion in these globally visible backend names
is deliberate and is separate from the account-free public workload names.

The bucket has versioning, default SSE-S3/AES256 encryption, ownership enforcement,
all four public-access blocks, a TLS-deny policy, `force_destroy=false`, and
Terraform deletion prevention. The lock table uses on-demand billing, string
partition key `LockID`, encryption, point-in-time recovery, deletion protection
and Terraform deletion prevention. Version history is retained; there is no
automatic state-version expiry that might remove a recovery point.

Different environments use different S3 objects and DynamoDB lock keys. A held
payments/dev lock must block payments/dev while allowing payments/prod and
customers/dev to proceed. CI uses one fresh `TF_DATA_DIR` per job. Terraform
workspaces do not define isolation here; live commands always use `default`.

SSE-S3 satisfies the requested at-rest encryption with no key administration.
A policy requiring customer-managed KMS keys would need a separate key policy,
backend/workload permission design and recovery tests; this implementation does
not claim KMS customer-managed encryption.

**DynamoDB is a deliberate requested compatibility choice.** HashiCorp deprecates
DynamoDB backend locking and may remove it in a future minor release. Terraform
is pinned to 1.17.1. Do not upgrade the CLI without running backend contention
checks and reviewing release notes. A future migration should drain writers,
enable dual locking during a coordinated rollout, then move every writer to S3
lockfiles before retiring the table. Never mix independent S3-only and
DynamoDB-only writers on the same state. See [Terraform's S3 backend documentation](https://developer.hashicorp.com/terraform/language/backend/s3).

## Onboard a team locally

From the platform checkout:

```bash
uv run python -m scripts.onboard \
  --team-id logistics --owner logistics@example.invalid \
  --destination ../logistics
```

This generates dev/staging/prod configs, regression expectations, Makefile and
workflow template. It refuses to overwrite an existing project. It makes no Git,
GitHub or AWS changes. The default `data` bucket is an editable private example,
not an assumption about the team's actual requirements.

```bash
cd ../logistics
make check
make localstack  # Docker, AWS CLI and the user's free Hobby token required
```

Once a real platform repository and release exist, supply both
`--platform-repository <owner/repository>` and `--platform-ref <40-character-SHA>`
when generating a new project. That produces a runnable workflow caller with
matching immutable pins. For existing local demos, replace the two placeholders
in `infrastructure.yml.template`, then rename it to `infrastructure.yml`. Keep the caller's workflow reference and checkout
reference identical. A branch or tag is rejected as a platform checkout pin.
Nothing in this task performs that publication or activation.

The platform administrator performs the privileged AWS enrollment once:

1. Confirm the real account, region, public-bucket policy, existing workload
   principal, repository owner/name, default branch and actual GitHub OIDC subject.
   Do not guess a subject: GitHub subject customization can change its format.
2. Configure one existing GitHub OIDC provider per AWS account. Protect each
   GitHub environment to allow the consumer default branch only; protect that
   branch with review rules. Configure required reviewers where available.
3. Add the platform-owned team registration below and set its catalog's real
   account/region, keeping `deployment_enabled=false` during bootstrap.
4. Render bootstrap inputs from that registration and apply `stacks/backends`
   as an operator. This provisions each team's bucket/table plus one CI role and
   protected workload boundary per environment. Then explicitly enable AWS
   deployment, review/release a platform SHA, and update the generated caller pin.
5. Run a plan-only default-branch dispatch, then an explicitly authorized apply
   dispatch and no-change plan in an AWS sandbox. Verify IAM denials in AWS.

Register the team first using the registration shape below. Then render all
registered teams in the selected account into one bootstrap var file:

```bash
uv run python -m scripts.bootstrap_inputs --account-id '<actual-account-id>' \
  --out .runs/bootstrap/inputs.tfvars.json
```

Review the generated file. In a protected operator workspace, use pinned
Terraform with `init -lockfile=readonly`, `plan -var-file=<absolute-generated-file>
-out=<private-saved-plan>`, review, then `apply <private-saved-plan>` against
`stacks/backends`. Rendering itself makes no AWS calls. Bootstrap is a privileged
operator action, not an ordinary team workflow. No parallel hand-maintained list
of teams/CI identities is required.

Example generated bootstrap input, **replace all example identities before use**:

```json
{
  "account_id": "123456789012",
  "region": "eu-central-1",
  "team_ids": ["payments"],
  "ci_bindings": {
    "payments--dev": {
      "team_id": "payments",
      "environment": "dev",
      "oidc_subject": "repo:YOUR-ACCOUNT/payments:environment:dev"
    }
  }
}
```

Add a binding for each environment. The OIDC provider must already exist.
`stacks/backends` uses local state initially to avoid a circular dependency.
Bootstrap state contains privileged IAM configuration: operate in a restricted,
encrypted workspace, back it up, and migrate it to an independently managed,
private platform backend before shared operation. Never store bootstrap state
inside a team's backend or check it into Git. Normal team CI never runs this root.

A platform registration at `config/teams/payments.json` has this shape:

```json
{
  "repository": "YOUR-ACCOUNT/payments",
  "environments": {
    "dev": {
      "oidc_subject": "repo:YOUR-ACCOUNT/payments:environment:dev",
      "trusted_principal_arn": "arn:aws:iam::123456789012:role/payments-dev-app"
    }
  }
}
```

The runtime principal must already exist. Keep it distinct per team/environment.
The existing module accepts exact same-account role ARNs without role paths.
Deployment checks bind the GitHub caller repository to this registration before
requesting credentials. Unknown teams/environments, fixture accounts, disabled
catalog entries and mismatched OIDC repository/environment subjects fail closed. Execution-role
ARNs are derived; teams cannot select a deployment identity. Enrollment
changes registry data and bootstrap inputs, never the shared workload module.

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

To add `qa`, the platform adds `config/environments/qa.json` with the same three
catalog fields. A team adds `environments/qa/resources.json` with
`"environment":"qa"` plus expectations. Configure its protected GitHub environment,
bootstrap CI binding and platform team registration before enabling AWS. A team
may use any nonempty subset of registered environments; dev/staging/prod are the
scaffold defaults, not a fixed enum. Names follow the existing lowercase
identifier rule and maximum eight characters.

For one account, keep backend region consistent across its catalog entries: a
team has one account-level bucket/table pair. Separate accounts get separate
pairs. Changing a live account or backend region is a migration, not a JSON
metadata edit. Workload bucket names still require distinct environment/team/key
identities across accounts because S3's global namespace is shared.

Removal is deliberate:

1. Stop new deployments and drain all writers for that team/environment.
2. Follow [offboarding-procedures.md](offboarding-procedures.md) for retained or
   destroyed resources, selecting the exact environment/backend. Retain the
   bucket/table and version history. Preserve a recoverable copy of the state.
3. Confirm inventory/state and record the owner's decision and operator approval.
   Remove/revoke that environment's CI binding through the platform operator,
   after in-flight sessions and recovery have been handled.
4. If this retires the team's last environment in an account, preserve its
   backend inventory in the platform registration before removing that binding:
   `"retained_backends":[{"account_id":"123456789012","region":"eu-central-1"}]`.
   The bootstrap renderer retains those bucket/table instances while removing
   the retired CI role/boundary. This avoids a later unrelated onboarding plan
   trying to delete retained state infrastructure. An empty environments map is
   allowed only with explicitly retained backends.
5. Remove the consumer environment directory and add
   `retired-environments/<environment>.json` in the same reviewed change:

   ```json
   {"team_id":"payments","environment":"qa","completed":true,
    "ticket":"CHG-123","approved_by":"platform-owner"}
   ```

   This is an auditable manual receipt, not automated proof that AWS is empty.
   Discovery rejects a removed environment without it; deleting JSON never
   triggers an automatic destroy. Retain decisions can leave resources/state.
6. Remove a platform catalog only after every team has retired that environment
   and all registrations/writers have been reconciled. Do not remove team backend
   resources while any environment or required recovery history remains.

## Moving existing state

Current demo state is disposable emulator state. For an existing live deployment,
backend migration must be an explicit operator change before adopting this path:
freeze and drain writers; back up and inspect the old state/lineage; create the
team backend; initialize the **old** backend in a fresh private directory; switch
to the rendered new bucket/key/table with `terraform init -migrate-state`; inspect
the copied state and run a no-change plan; then enable the new workflow. Update
permissions and retire old writers together. `-reconfigure` does not copy state.
Do not apply from an empty new backend and accidentally recreate existing assets.
Migration is a manual procedure here, not something onboarding silently performs.

## Shared resources and scale

The shared resources in this release are the platform module/root, workflow,
validation/tests, account-level OIDC provider, and platform-managed backend/CI
modules. Teams supply no Terraform implementation. This does not introduce
cross-team access to workload data or permit reading another team's entire state.
If a future team needs a shared VPC/KMS key, expose a small platform-owned,
read-only identifier contract after requirements are known; do not use access to
another team's state as a general discovery mechanism.

Three hundred teams consume the same versioned workflow and module. Each workflow
runs at most three environment jobs concurrently, with state/lock isolation per
team/environment. Account IAM-role/S3 quotas, GitHub runner concurrency and AWS
API throttling need capacity checks before a real 300-team rollout. In one
account, 300 teams × 3 environments × (one CI role + one workload role) requires
1,800 roles, plus existing roles. AWS's default is 1,000 roles/account, adjustable
to 10,000: request enough quota and headroom, or use separate environment accounts
before rollout. See [AWS IAM quotas](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_iam-quotas.html).
The new bootstrap-rendering test covers 300 teams / 900 CI bindings; the existing
The 300-team registry case proves configuration scale and per-environment
selection mechanics. Neither proves AWS capacity.

## Verification boundaries

`make check` runs the [Trivy/Checkov security gate](security-scanning.md) and
its tests that confirm unsafe configurations are rejected, alongside the
environment/onboarding/deployment and native backend/CI-module contracts. `make test-consumers` runs
all nine example declarations through the root without cloud credentials.
`make test-localstack` uses actual Terraform/provider code and an isolated free
Hobby container for S3/DynamoDB-backed state, contention and workload lifecycle.
It does not activate paid features or touch the pre-existing emulator.

Real AWS acceptance is still required: verify OIDC trust, backend prefix and lock
row permissions, cross-team/cross-environment denials, mandatory workload boundary,
public/private access and TLS enforcement, idempotent reapply, wrong-account
rejection and state-version recovery. Live GitHub environment approval behavior
also remains unverified until activation. See [verification.md](verification.md)
for recorded local results; no claim of numerical “99% certainty” substitutes
for these missing AWS/GitHub checks.

## CI permission mapping audit

The scoped policy is checked against an independent whole-policy fixture. A
separate regression inventory covers the pinned provider's bucket-read actions:
`GetBucket*` does **not** cover `GetEncryptionConfiguration`,
`GetAccelerateConfiguration`, `GetLifecycleConfiguration` or
`GetReplicationConfiguration`, so all four are explicitly granted for the team's
workload bucket prefix. Ownership-control and tagging deletion use their `Put`
permissions; there are no invented `DeleteBucketOwnershipControls` or
`DeleteBucketTagging` IAM actions. Role updates/tags remain scoped to the exact
workload role. Valid action names were checked against AWS's public machine-readable
S3/IAM/DynamoDB service authorization metadata; this is structural validation,
not an IAM authorization-engine test.

Sources: [pinned provider bucket reader](https://github.com/hashicorp/terraform-provider-aws/blob/v6.71.0/internal/service/s3/bucket.go),
[AWS encryption read permission](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetBucketEncryption.html),
[AWS ownership-control deletion permission](https://docs.aws.amazon.com/AmazonS3/latest/API/API_DeleteBucketOwnershipControls.html),
[AWS tagging deletion permission](https://docs.aws.amazon.com/AmazonS3/latest/API/API_DeleteBucketTagging.html).
