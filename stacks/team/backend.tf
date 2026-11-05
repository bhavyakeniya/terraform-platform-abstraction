# Partial backend configuration: bucket/key/region/encrypt/dynamodb_table are
# supplied at init time via -backend-config=backend.hcl.json, rendered per
# team/environment by scripts/team_platform.py (Section 3.5, Task 2). Never
# hardcode a real bucket/key here -- that would make every team share state.

terraform {
  backend "s3" {}
}
