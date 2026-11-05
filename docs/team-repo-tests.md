# Testing the team repositories

Three team repositories consume this platform: **payments**, **customers** and
**accounting**. Each owns only JSON. This page explains what is checked, where
each check runs, and how to run it yourself.

No team repository contains Terraform, provider configuration, backend
configuration, or pipeline implementation. Every check below executes the
platform's own module and root against the team's declaration.

## What a team repository contains

```text
payments/
  team.json                                  # {"team_id": "payments"} — stable identity
  environments/
    dev/{resources.json,expectations.json}
    staging/{resources.json,expectations.json}
    prod/{resources.json,expectations.json}
  .github/workflows/infrastructure.yml.template   # small generated caller
  Makefile                                   # check / localstack entry points
```

`customers` and `accounting` are identical in shape. The committed copies under
`examples/consumers/<team>/` in this repository mirror them so the platform
suite can run without the sibling checkouts present.

## The two layers of checking

| Layer | What it proves | Where it runs |
| --- | --- | --- |
| **Declaration + root check** | The team's JSON is valid, closed, and plans cleanly through the real module | `make test-consumers` here; `make check` in the team repo |
| **Expectations check** | The team has not dropped a required bucket or exposed one it is not allowed to expose | Same command — runs alongside the declaration check |

### Declaration and root check

For every environment directory, the platform:

1. Validates `resources.json` against the closed v2 contract — unknown keys,
   missing `visibility`, duplicate JSON keys and oversized files are rejected.
2. Confirms the folder name, the `environment` field inside the JSON, and the
   platform environment catalog all agree.
3. Renders `inputs.tfvars.json` and `backend.hcl.json`.
4. Runs the real `stacks/team` root under `mock_provider` against those inputs,
   asserting the output bucket count and keys match the declaration exactly.

Step 4 is the important one: the team's actual declaration is planned through
the same module and root that a real deployment would use. It is not compared
against a reimplementation of the rules.

### Expectations check

Each environment carries an `expectations.json` beside its declaration:

```json
{
  "required_buckets": ["receipts", "settlements"],
  "allowed_public_buckets": []
}
```

This is a **business regression test owned by the team**, not an authorization
mechanism. It catches two specific mistakes in review:

- a bucket the service depends on was deleted from the declaration
- a bucket was switched to `public` that the team never agreed to expose

The file is closed to exactly those two keys. A declaration that newly exposes
a bucket not in `allowed_public_buckets` fails the check.

## Running the checks

From a team repository (resolves the platform through `PLATFORM_DIR`, default
`../terraform_platform_abstraction`):

```bash
cd payments
make check          # all three environments, no AWS, no credentials
make localstack     # optional: real-provider lifecycle against LocalStack Hobby
```

From this platform repository, against the committed mirrors:

```bash
make test-consumers   # payments, customers, accounting — all environments
```

To check a sibling checkout instead of the committed mirror:

```bash
CONSUMERS="../payments ../customers ../accounting" make test-consumers
```

`make test-consumers` is part of `make check`, so the team contracts are
verified on every full platform run.

## Platform-side tests about team repositories

`tests/test_consumers.py` tests the consumer mechanism itself rather than any
one team's data:

- the three teams express genuinely distinct contracts (different bucket
  counts, and public exposure only where the team allows it)
- a new public exposure is rejected when it is not in `allowed_public_buckets`
- a missing required bucket is rejected
- adding a private bucket needs no platform or contract change
- duplicate or symlinked `expectations.json` files are rejected
- team workflows call the shared generated workflow rather than copying CI
- the Terraform version pinned in the shared action matches the platform's

## What these checks do not prove

- **No AWS call is made.** The provider is mocked. This proves the plan and the
  generated policy are correct in structure, not that AWS's authorization engine
  enforces them as intended.
- **No live GitHub run.** The team workflow ships as `.yml.template` and becomes
  active only after the platform repository is published and a reviewed release
  SHA is filled in. Workflow correctness is checked structurally with
  `actionlint`, not by execution.
- **LocalStack is not an authorization oracle.** The free tier reads policies
  back but does not enforce them.

See [verification.md](verification.md) for executed results and
[environments-and-delivery.md](environments-and-delivery.md) for the full
onboarding and delivery contract.
