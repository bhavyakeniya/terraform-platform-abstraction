# Team/environment CI identity

Creates one OIDC role and a protected workload permissions boundary per
team/environment. It requires an existing account GitHub OIDC provider and an
exact verified subject for a protected GitHub environment. The platform
administrator applies it through `stacks/backends`.

The CI role can manage its own workload bucket prefix and exact workload role,
read/write its exact state object, operate its two DynamoDB lock/checksum rows,
and upload emergency state to its environment's private recovery prefix. It
cannot access another team's backend, modify its own identity, pass roles,
attach arbitrary managed policies, or edit the platform boundary.

Workload role creation requires that boundary, and removing it is explicitly
denied. The workload module attaches it in every live pipeline invocation,
limiting the role to same-account S3 data operations for its team/environment.
CI can still alter its own bucket policies: review workflow/module changes and
approve public data before deployment.

Native tests verify policy construction. Effective IAM authorization and GitHub
OIDC trust still require AWS sandbox acceptance; Hobby does not enforce IAM.
See [delivery](../../docs/environments-and-delivery.md) and
[private state recovery](../../docs/operations.md#private-state-recovery).
