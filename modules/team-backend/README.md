# Team backend

One private, versioned AES256-encrypted S3 bucket and encrypted DynamoDB lock table
per team/account. Both use `sumup--tfstate--<account-id>--<team-id>`; each environment
has its own state object and lock rows. Both have Terraform deletion prevention;
the table also has AWS deletion protection and point-in-time recovery.

Platform operators use `stacks/backends`; consumer CI never creates its backend.
See [delivery and state](../../docs/environments-and-delivery.md) for bootstrap,
permissions, migration, recovery, and DynamoDB deprecation. Do not remove
`prevent_destroy` to make an ordinary team removal succeed.
