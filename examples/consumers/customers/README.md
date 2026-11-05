# customers consumer

Configurations live in `environments/dev`, `environments/staging` and
`environments/prod`. Edit the JSON declaration and expectations for that environment.
`team.json` supplies the stable team ID. Each JSON explicitly names its environment.

`make check` checks every environment without AWS; pass
`PLATFORM_DIR=/path/to/terraform-platform-abstraction` if the platform is
not a sibling directory. `make localstack` exercises
all three against the isolated free Hobby emulator, including S3 state/DynamoDB locks.
The platform supplies every Terraform file and all pipeline implementation.

This directory is a committed mirror of
<https://github.com/bhavyakeniya/team-customers>, kept here so the platform's
`make check` can validate a real consumer without the sibling repository
checked out. It deliberately keeps `infrastructure.yml.template` un-activated:
the live repository supplies the platform repository and reviewed SHA, this
copy does not. Edit the live repository first; this mirror follows it.

Team configuration lives in environments/ exclusively; there are no duplicate
root declarations to accidentally edit.
