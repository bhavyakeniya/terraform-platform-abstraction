"""Platform workflow and smoke_check wiring.

Workflow assertions are structural/contract checks against the committed
YAML (permissions, pinned actions, helper wiring, absence of
credentials/apply/privileged triggers) -- not a live GitHub run. Actual
execution requires the repository to be published.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from scripts.team_platform import smoke_check

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "terraform.yml"
_LOCAL_TERRAFORM = REPO_ROOT / ".local" / "bin" / "terraform"


def fixture_config() -> dict:
    return json.loads((REPO_ROOT / "config" / "fixture.json").read_text())


@pytest.fixture(autouse=True)
def _use_pinned_terraform(monkeypatch):
    # Prefer a locally fetched pinned binary if present (dev machines below
    # the version floor); otherwise leave TEAM_PLATFORM_TERRAFORM unset so
    # _terraform_bin()'s own default ("terraform" on PATH) applies -- which
    # is how CI installs it. Hardcoding the local path unconditionally here
    # broke every terraform-invoking test in CI with FileNotFoundError.
    if _LOCAL_TERRAFORM.is_file():
        monkeypatch.setenv("TEAM_PLATFORM_TERRAFORM", str(_LOCAL_TERRAFORM))


# --- YAML loading that preserves GitHub's "on" key --------------------------
#
# Default PyYAML (even SafeLoader) resolves the bare scalar "on" to the
# Python boolean True -- a YAML 1.1 implicit-boolean quirk that would turn
# workflow["on"] into workflow[True]. Strip the bool resolver so "on"/"off"/
# "yes"/"no" stay literal strings; this workflow has no other scalar
# booleans that assertions below depend on being real Python bools.


class _PreserveOnKeyLoader(yaml.SafeLoader):
    pass


_PreserveOnKeyLoader.yaml_implicit_resolvers = {
    first_char: [r for r in resolvers if r[0] != "tag:yaml.org,2002:bool"]
    for first_char, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def load_workflow() -> dict:
    with WORKFLOW_PATH.open(encoding="utf-8") as handle:
        return yaml.load(handle, Loader=_PreserveOnKeyLoader)


def all_steps(workflow: dict):
    for job in workflow["jobs"].values():
        yield from job.get("steps", [])


# --- P05: permissions, pinned actions, explicit head checkout, wiring ------


def test_workflow_on_key_preserved_and_no_privileged_trigger():
    workflow = load_workflow()
    assert "on" in workflow, "the 'on' key must survive parsing, not become True"
    assert set(workflow["on"].keys()) == {"pull_request", "push", "workflow_dispatch"}
    assert "pull_request_target" not in workflow["on"]


def test_workflow_has_read_only_permissions():
    workflow = load_workflow()
    assert workflow["permissions"] == {"contents": "read"}


def test_external_actions_are_sha_pinned_and_local_actions_use_this_checkout():
    workflow = load_workflow()
    sha_pin_re = re.compile(r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$")
    uses_refs = [step["uses"] for step in all_steps(workflow) if "uses" in step]
    assert uses_refs, "expected at least one action reference"
    for ref in uses_refs:
        if ref.startswith("./"):
            # Local code is supplied by this checked-out revision, not a
            # mutable external action tag. Keep the allowed entry point explicit.
            assert ref == "./.github/actions/security-checks"
            action_path = REPO_ROOT / ref / "action.yml"
            assert action_path.is_file()
            action = yaml.load(action_path.read_text(), Loader=_PreserveOnKeyLoader)
            for step in action["runs"]["steps"]:
                if "uses" in step:
                    assert sha_pin_re.match(step["uses"])
        else:
            assert sha_pin_re.match(ref), f"not pinned to a full 40-char SHA: {ref}"


def test_no_credentials_or_apply_anywhere_in_workflow():
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "secrets." not in text
    assert "AWS_ACCESS_KEY" not in text
    assert "AWS_SECRET" not in text
    # Scoped to actual run: command text, not the whole file: a YAML comment
    # mentioning "apply" (e.g. documenting that there is none) would
    # otherwise fail this test for saying the right thing.
    workflow = load_workflow()
    run_text = "\n".join(step.get("run", "") for step in all_steps(workflow))
    assert not re.search(r"\bapply\b", run_text), "no terraform apply step is permitted"


def test_helper_wiring_uses_expected_subcommands():
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "team_platform.py smoke-check --fixtures-dir" in text
    # Per-team change selection belongs to the consumer repositories and is
    # handled by scripts/consumer_matrix.py in team-infrastructure.yml; this
    # platform workflow must not reintroduce a teams/ discovery pass.
    assert "team_platform.py discover" not in text
    assert "team_platform.py check-batch" not in text
    # fixture-smoke is intentionally excluded from the checks job's make
    # invocation (it has its own job, see test_fixture_smoke_job_*), so this
    # checks the specific local-check targets rather than aggregate `make check`.
    assert "make fmt-check test-python test-module test-root-generic test-backend check-examples test-consumers" in text


# --- P06: empty-selection guard; batch failures surfaced -------------------


def test_fixture_smoke_job_has_no_condition_and_no_dependency():
    workflow = load_workflow()
    job = workflow["jobs"]["fixture-smoke"]
    assert "if" not in job
    assert "needs" not in job


def test_fixture_smoke_job_never_touches_teams_directory():
    workflow = load_workflow()
    job = workflow["jobs"]["fixture-smoke"]
    run_text = "\n".join(step.get("run", "") for step in job["steps"])
    assert "teams/" not in run_text
    assert ".runs/fixture-smoke" in run_text


def test_smoke_check_passes_on_valid_fixtures(tmp_path):
    fixtures_dir = tmp_path / "fixtures"
    for name, example in [("smoke-a", "minimal"), ("smoke-b", "mixed")]:
        target = fixtures_dir / name
        target.mkdir(parents=True)
        content = (REPO_ROOT / "examples" / example / "resources.json").read_text()
        (target / "resources.json").write_text(content)

    smoke_check(fixtures_dir, fixture_config())  # must not raise


def test_smoke_check_fails_on_defect_caught_before_terraform(tmp_path):
    # This defect (a reserved bucket-name suffix) is caught by Python's own
    # validate_bucket_name inside render_inputs, before _run_mocked_root_test
    # ever invokes `terraform test` -- it proves smoke_check's failure
    # aggregation works, not that the Terraform layer itself caught anything.
    # See test_smoke_check_fails_on_defect_only_terraform_catches below for
    # that.
    fixtures_dir = tmp_path / "fixtures"
    broken = fixtures_dir / "broken"
    broken.mkdir(parents=True)
    (broken / "resources.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "owner": "team@example.invalid",
                "buckets": {"x-s3": {"visibility": "private"}},  # reserved suffix: an injected defect
            }
        )
    )

    with pytest.raises(ValueError, match="x-s3"):
        smoke_check(fixtures_dir, fixture_config())


def test_smoke_check_fails_on_defect_only_terraform_catches(tmp_path):
    # The oversized-inline-policy limit (AWS IAM: 10,240 characters,
    # whitespace excluded) has no Python-side check at all -- only the
    # module's own lifecycle precondition (modules/team-resources/iam.tf)
    # enforces it. A fixture that passes every Python validation but still
    # fails must reach the real `terraform test` invocation to fail at all,
    # which is what P07 ("fails the workflow on an injected mocked-root
    # defect") actually asks to be demonstrated.
    fixtures_dir = tmp_path / "fixtures"
    broken = fixtures_dir / "smokebrokenteam1"  # long ID keeps generated policy resources large
    broken.mkdir(parents=True)
    buckets = {f"bkt000000000{i:04d}": {"visibility": "private"} for i in range(1, 36)}
    (broken / "resources.json").write_text(
        json.dumps({"schema_version": 1, "owner": "team@example.invalid", "buckets": buckets})
    )

    with pytest.raises(ValueError, match="mocked root check failed"):
        smoke_check(fixtures_dir, fixture_config())


def test_smoke_check_empty_fixtures_dir_is_a_safe_no_op(tmp_path):
    fixtures_dir = tmp_path / "empty-fixtures"
    fixtures_dir.mkdir()

    smoke_check(fixtures_dir, fixture_config())  # must not raise
