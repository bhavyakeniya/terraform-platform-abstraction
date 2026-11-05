# Using the platform as a team

A team owns one JSON declaration per environment. The platform owns everything
else: Terraform, CI, state, and identity.

## Onboard a new team

```bash
uv run python -m scripts.onboard --team-id logistics \
  --owner logistics@example.invalid --destination ../logistics
```

This generates a project with `team.json`, `environments/{dev,staging,prod}`,
a Makefile, and a thin workflow caller — no Terraform, no CI logic. A platform
operator still has to enroll the repository and its workload identities before
anything can deploy; see [environments and delivery](environments-and-delivery.md).

## Make an everyday change

Edit the relevant `environments/<env>/resources.json` and its
`expectations.json`, then run `make check`. Every bucket must explicitly
choose public or private — there is no default.

| Change | Behavior |
| --- | --- |
| Add a bucket | Add its JSON key; existing addresses remain stable. |
| Remove a bucket | Plan shows deletion; manual apply also requires `allow-destroy`. A populated bucket cannot be silently emptied. |
| Change visibility | Review the public-data implications; bucket policy and access flags update. |
| Change owner | Tags update without changing resource identity. |
| Reorder JSON | No resource change. |
| Add an environment | Add catalog enrollment and a matching directory/JSON; the next run selects it. |
| Retire an environment or team | See [offboarding-procedures.md](offboarding-procedures.md) — deletion is not the only option. |

Stable team and bucket keys determine resource identity; changing a key is a
migration, not a rename.

## CI

Pull requests and pushes run credential-free checks on every environment.
Plan and apply happen only through a manual workflow dispatch. See
[environments and delivery](environments-and-delivery.md#cicd-what-actually-happens)
for the complete trigger table.

## Three example teams

Published repositories — [team-payments](https://github.com/bhavyakeniya/team-payments),
[team-customers](https://github.com/bhavyakeniya/team-customers) and
[team-accounting](https://github.com/bhavyakeniya/team-accounting) —
demonstrate this in practice. Mirrors live under `examples/consumers` so this
platform's own test suite can run without those checkouts.

| Team | Buckets per environment | Approved public bucket |
| --- | --- | --- |
| payments | receipts, settlements | None |
| customers | profiles, exports, help-assets | help-assets |
| accounting | ledger, invoices, reports, audit-history | None |

```bash
# From this repository: check all three example teams.
make test-consumers
make test-localstack

# From a team's own checkout:
cd ../payments
make check
make localstack
```

See [team repository tests](team-repo-tests.md) for what each check verifies,
and [LocalStack](localstack.md) for the emulator's prerequisites and limits.
