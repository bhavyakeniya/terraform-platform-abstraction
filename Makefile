.PHONY: check fmt-check test-python test-module test-root-generic check-examples fixture-smoke test-consumers test-localstack

# Prefer a locally fetched pinned binary (.local/bin/terraform, gitignored --
# see Task 3's note on the installed system Terraform being below the floor);
# fall back to whatever "terraform" is on PATH, which is how CI installs the
# pinned version (workflow's "Install pinned Terraform" step).
TERRAFORM := $(shell test -x .local/bin/terraform && echo .local/bin/terraform || echo terraform)
EXAMPLES  := minimal mixed
CONSUMERS ?= examples/consumers/payments examples/consumers/customers examples/consumers/accounting

# All local, credential-free checks: Python contracts, Terraform native
# mocks, and every example/consumer through the real pipeline.
check: security test-security fmt-check test-python test-module test-root-generic test-backend check-examples fixture-smoke test-consumers

fmt-check:
	$(TERRAFORM) fmt -check -recursive

test-python:
	uv run pytest tests/ -q

test-module:
	$(TERRAFORM) -chdir=modules/team-resources init -backend=false -lockfile=readonly > /dev/null
	$(TERRAFORM) -chdir=modules/team-resources test -filter=tests/contract.tftest.hcl
	$(TERRAFORM) -chdir=modules/team-resources test -filter=tests/security.tftest.hcl

# T07's team-independent generic checks (output projection, wrong-caller-
# account rejection): run once here, not per team/example. declaration.tftest.hcl
# (below) stays limited to the one declaration-specific check so a
# multi-environment consumer run doesn't redundantly repeat these.
test-root-generic:
	$(TERRAFORM) -chdir=stacks/team init -backend=false -lockfile=readonly > /dev/null
	$(TERRAFORM) -chdir=stacks/team test -filter=tests/generic.tftest.hcl

# declaration.tftest.hcl's "check_example" run has no variables of its own
# by design (Terraform test precedence makes a file/run-level block always
# shadow -var-file, so it must stay empty to be externally drivable); it
# only passes when given a real var-file. check-examples below and
# consumer_platform's per-environment check are what drive it.

# Renders each committed example through the real CLI, then runs the real
# module/root under terraform test's mock_provider against that exact
# rendered data -- proving the committed declarations survive the full
# pipeline (naming, reserved suffixes, visibility, policy construction)
# credential-free. Each example gets its own TF_DATA_DIR so they never share
# .terraform/ state.
check-examples:
	@set -e; \
	for example in $(EXAMPLES); do \
		echo "--- check-examples: $$example ---"; \
		out_dir="$(CURDIR)/.runs/check-examples/$$example"; \
		rm -rf "$$out_dir"; \
		uv run python scripts/team_platform.py render \
			--file examples/$$example/resources.json \
			--team-id $$example \
			--config config/fixture.json \
			--out "$$out_dir"; \
		TF_DATA_DIR="$$out_dir/.terraform-data" $(TERRAFORM) -chdir=stacks/team init -backend=false -lockfile=readonly > /dev/null; \
		TF_DATA_DIR="$$out_dir/.terraform-data" $(TERRAFORM) -chdir=stacks/team test \
			-filter=tests/declaration.tftest.hcl \
			-var-file="$$out_dir/inputs.tfvars.json"; \
	done

# Local mirror of the CI fixture-smoke job: ephemeral fixtures only, never
# committed. Proves the temp-fixture-generation-plus-shared-init path that
# smoke_check drives.
fixture-smoke:
	@rm -rf .runs/fixture-smoke
	@mkdir -p .runs/fixture-smoke/smoke-a .runs/fixture-smoke/smoke-b
	@cp examples/minimal/resources.json .runs/fixture-smoke/smoke-a/resources.json
	@cp examples/mixed/resources.json .runs/fixture-smoke/smoke-b/resources.json
	TEAM_PLATFORM_TERRAFORM="$(TERRAFORM)" uv run python scripts/team_platform.py smoke-check \
		--fixtures-dir .runs/fixture-smoke --config config/fixture.json

# Consumer declaration checks stay token/Docker independent; emulator tests are opt-in.
test-consumers:
	@set -e; for consumer in $(CONSUMERS); do \
		uv run python -m scripts.consumer_platform check --team-id "$$(basename "$$consumer")" --consumer-dir "$$consumer"; \
	done

test-localstack:
	uv run python -m scripts.localstack_check $(foreach consumer,$(CONSUMERS),--consumer-dir "$(consumer)")

.PHONY: test-backend
test-backend:
	$(TERRAFORM) -chdir=modules/team-backend init -backend=false -lockfile=readonly > /dev/null
	$(TERRAFORM) -chdir=modules/team-backend test
	$(TERRAFORM) -chdir=modules/team-ci init -backend=false -lockfile=readonly > /dev/null
	$(TERRAFORM) -chdir=modules/team-ci test
	$(TERRAFORM) -chdir=stacks/backends init -backend=false -lockfile=readonly > /dev/null
	$(TERRAFORM) -chdir=stacks/backends validate
	$(TERRAFORM) -chdir=stacks/backends test
	$(TERRAFORM) -chdir=examples/security init -backend=false -lockfile=readonly > /dev/null
	$(TERRAFORM) -chdir=examples/security validate

.PHONY: security security-tools
security-tools:
	uv sync --project tools/security --locked --python "$$(cat .python-version)"

security: security-tools
	uv run python -m scripts.security_check

.PHONY: test-security
test-security: security-tools
	uv run pytest tests/test_security.py tests/security_canaries.py -q
