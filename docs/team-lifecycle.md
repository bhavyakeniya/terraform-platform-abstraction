# Team lifecycle

New teams use a separate consumer repository with environment-specific JSON.
The platform generates the scaffold and thin shared-workflow caller:

```bash
uv run python -m scripts.onboard --team-id logistics \
  --owner logistics@example.invalid --destination ../logistics
```

Edit `environments/dev/resources.json` and its expectations, then run `make check`
from the generated project. Repeat for staging/prod or another registered
environment. Every bucket must explicitly choose public/private. Stable team and
bucket keys determine identities; changing a key is a migration, not a rename.

Platform operators enroll the repository and existing workload principals, create
its backend/CI bindings and approve activation. The workflow checks PRs, plans
post-merge changes and applies only through a manual default-branch dispatch.
Real deployments remain disabled in the checked-in fixture catalogs.

| Change | Behavior |
| --- | --- |
| Add a bucket | Add its JSON key; existing addresses remain stable. |
| Remove a bucket | Plan shows deletion; manual apply also requires allow-destroy. Populated buckets cannot be silently emptied. |
| Change visibility | Review the public-data implications; bucket policy/access flags update. |
| Change owner | Tags update without changing resource identity. |
| Reorder JSON | No resource change. |
| Add an environment | Add catalog enrollment and a matching directory/JSON; CI discovers it. |
| Retire an environment/team | Drain writers and follow the explicit retain/destroy procedure; preserve backend history. |

See [the complete delivery guide](environments-and-delivery.md) for exact enrollment,
state isolation, migration, retirement receipts and scale considerations. See
[offboarding-procedures.md](offboarding-procedures.md) for the complete manual
retain/destroy paths. Archive/transfer/export remain conceptual options requiring
separate decisions, not additional Terraform infrastructure.
