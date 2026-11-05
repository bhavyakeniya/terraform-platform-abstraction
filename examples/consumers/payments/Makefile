.PHONY: check localstack
PLATFORM_DIR ?= ../terraform_platform_abstraction

check:
	cd "$(PLATFORM_DIR)" && uv run python -m scripts.consumer_platform check --team-id payments --consumer-dir "$(CURDIR)"

localstack:
	cd "$(PLATFORM_DIR)" && uv run python -m scripts.localstack_check --team-id payments --consumer-dir "$(CURDIR)"
