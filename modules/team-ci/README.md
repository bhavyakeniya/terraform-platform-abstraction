# Team/environment CI identity

Creates one OIDC role and a protected workload permissions boundary for an
explicit team/environment. Requires an existing account GitHub OIDC provider and
an exact verified subject for a protected GitHub environment; no wildcard trust.
The platform administrator applies this through `stacks/backends`.

The CI role can manage its own workload bucket prefix and exact workload role,
read/write its state object, and operate only its two lock/checksum rows. It
cannot modify itself, another team/environment, or the boundary policy. Role
creation requires the platform boundary; removing it is explicitly denied.
The workload module attaches that boundary in every live pipeline invocation.

Native tests verify policy construction. Effective IAM authorization and GitHub
OIDC trust still require AWS sandbox acceptance; Hobby does not enforce IAM.
See [delivery](../../docs/environments-and-delivery.md).
