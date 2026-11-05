# customers consumer

Configurations live in `environments/dev`, `environments/staging` and
`environments/prod`. Edit the JSON declaration and expectations for that environment.
`team.json` supplies the stable team ID. Each JSON explicitly names its environment.

`make check` checks every environment without AWS. `make localstack` exercises
all three against the isolated free Hobby emulator, including S3 state/DynamoDB locks.
The platform supplies every Terraform file and all pipeline implementation.

The generated `infrastructure.yml.template` becomes the CI entry point once the
platform has an actual published repository and reviewed commit SHA. Fill both
placeholders with the same release, rename it to infrastructure.yml, and follow
platform registration in `docs/environments-and-delivery.md`. It calls the shared
checks/plan/apply workflow. Optional default-branch `mode=check, localstack=true`
runs Hobby integration without AWS. No publication or AWS deployment is active.

Team configuration lives in environments/ exclusively; there are no duplicate
root declarations to accidentally edit.
