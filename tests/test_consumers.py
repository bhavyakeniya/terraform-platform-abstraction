"""Consumer contracts and emulator-runner safety, without Docker or credentials."""

import json
from pathlib import Path
import subprocess

import pytest
import yaml

from scripts import localstack_check, team_platform
from scripts.consumer_platform import PLATFORM_ROOT, load_consumer


@pytest.mark.parametrize("team,count,public", [("payments", 2, set()),
                                              ("customers", 3, {"help-assets"}),
                                              ("accounting", 4, set())])
def test_three_distinct_consumer_contracts(team, count, public):
    declaration, context = load_consumer(PLATFORM_ROOT / "examples/consumers" / team / "environments/dev", team)
    assert len(declaration["buckets"]) == count
    assert {k for k, v in declaration["buckets"].items() if v["visibility"] == "public"} == public
    assert f"/teams/{team}/" in context["state_key"]


@pytest.fixture
def payments(tmp_path):
    source = PLATFORM_ROOT / "examples/consumers/payments/environments/dev"
    tmp_path = tmp_path / "environments/dev"
    tmp_path.mkdir(parents=True)
    for name in ("resources.json", "expectations.json"):
        (tmp_path / name).write_bytes((source / name).read_bytes())
    return tmp_path


def test_consumer_rejects_new_public_exposure(payments):
    path = payments / "resources.json"
    declaration = json.loads(path.read_text())
    declaration["buckets"]["receipts"]["visibility"] = "public"
    path.write_text(json.dumps(declaration))
    with pytest.raises(ValueError, match="does not allow public"):
        load_consumer(payments, "payments")


def test_consumer_rejects_missing_required_bucket(payments):
    path = payments / "resources.json"
    declaration = json.loads(path.read_text())
    del declaration["buckets"]["receipts"]
    path.write_text(json.dumps(declaration))
    with pytest.raises(ValueError, match="requires missing"):
        load_consumer(payments, "payments")


def test_private_growth_requires_no_platform_or_contract_change(payments):
    path = payments / "resources.json"
    declaration = json.loads(path.read_text())
    declaration["buckets"]["new-private"] = {"visibility": "private"}
    path.write_text(json.dumps(declaration))
    load_consumer(payments, "payments")


def test_ci_checkout_alias_uses_explicit_team_identity(payments, monkeypatch):
    # GitHub checks every consumer out to a folder literally named consumer.
    # Identity must come from the workflow, not that checkout folder's name.
    monkeypatch.delenv("LOCALSTACK_AUTH_TOKEN", raising=False)
    with pytest.raises(ValueError, match="LOCALSTACK_AUTH_TOKEN is missing"):
        localstack_check.run_consumers([payments], team_id="payments")


def test_duplicate_expectations_rejected(payments):
    (payments / "expectations.json").write_text('{"required_buckets": [], "required_buckets": [], "allowed_public_buckets": []}')
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_consumer(payments, "payments")


def test_symlink_expectations_rejected(payments):
    path = payments / "expectations.json"
    other = payments / "other.json"
    path.rename(other)
    path.symlink_to(other)
    with pytest.raises(ValueError, match="regular file"):
        load_consumer(payments, "payments")


def test_cli_prefers_pinned_local_terraform_and_explicit_override(tmp_path, monkeypatch):
    monkeypatch.delenv("TEAM_PLATFORM_TERRAFORM", raising=False)
    monkeypatch.setattr(team_platform, "__file__", str(tmp_path / "scripts/team_platform.py"))
    assert team_platform._terraform_bin() == "terraform"
    binary = tmp_path / ".local/bin/terraform"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    assert team_platform._terraform_bin() == str(binary)
    monkeypatch.setenv("TEAM_PLATFORM_TERRAFORM", "/explicit/terraform")
    assert team_platform._terraform_bin() == "/explicit/terraform"


def test_localstack_child_environment_excludes_real_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_SESSION_TOKEN", "synthetic-unwanted-session")
    monkeypatch.setenv("AWS_PROFILE", "synthetic-unwanted-profile")
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://example.invalid")
    monkeypatch.setenv("TF_CLI_ARGS", "-lock=false")
    monkeypatch.setenv("HTTPS_PROXY", "https://example.invalid")
    env = localstack_check.isolated_environment(tmp_path)
    assert env["AWS_ACCESS_KEY_ID"] == env["AWS_SECRET_ACCESS_KEY"] == "test"
    assert not {"AWS_SESSION_TOKEN", "AWS_PROFILE", "AWS_ENDPOINT_URL", "TF_CLI_ARGS", "HTTPS_PROXY"} & env.keys()
    assert Path(env["AWS_SHARED_CREDENTIALS_FILE"]).read_text() == ""


def test_cleanup_stops_on_per_object_errors(monkeypatch):
    calls = []
    def fake_aws(env, *args):
        calls.append(args[1])
        if args[1] == "list-object-versions":
            return {"Versions": [{"Key": "fixture.txt", "VersionId": "v1"}]}
        return {"Errors": [{"Code": "AccessDenied"}]}
    monkeypatch.setattr(localstack_check, "aws", fake_aws)
    with pytest.raises(ValueError, match="cleanup errors"):
        localstack_check.empty_bucket({}, "synthetic")
    assert calls == ["list-object-versions", "delete-objects"]


def test_cleanup_checks_combined_version_and_marker_batch_limit(monkeypatch):
    def fake_aws(env, *args):
        assert args[1] == "list-object-versions"
        return {"Versions": [{"Key": "v", "VersionId": str(i)} for i in range(600)],
                "DeleteMarkers": [{"Key": "d", "VersionId": str(i)} for i in range(600)]}
    monkeypatch.setattr(localstack_check, "aws", fake_aws)
    with pytest.raises(ValueError, match="batch limit"):
        localstack_check.empty_bucket({}, "synthetic")


def test_consumer_workflows_share_the_generated_caller_instead_of_copied_ci():
    template = (PLATFORM_ROOT / "templates/consumer/infrastructure.yml").read_text()
    for directory in (PLATFORM_ROOT / "examples/consumers").iterdir():
        assert (directory / ".github/workflows/infrastructure.yml.template").read_text() == template
        assert not (directory / ".github/workflows/infrastructure.yml").exists()
        workflow = yaml.load(template, Loader=yaml.BaseLoader)
        assert set(workflow["jobs"]) == {"infrastructure"}
        assert workflow["jobs"]["infrastructure"]["uses"] == "PLATFORM_REPOSITORY/.github/workflows/team-infrastructure.yml@PLATFORM_REF"
        assert "pull_request_target" not in workflow["on"]


def test_action_terraform_pin_matches_platform():
    action = yaml.safe_load((PLATFORM_ROOT / ".github/actions/consumer-check/action.yml").read_text())
    step = next(s for s in action["runs"]["steps"] if s.get("uses", "").startswith("hashicorp/setup-terraform@"))
    assert step["with"]["terraform_version"] == (PLATFORM_ROOT / ".terraform-version").read_text().strip()


def test_failed_container_start_never_cleans_an_unrelated_api(tmp_path, monkeypatch):
    # Docker can create the named container but fail to bind an occupied port.
    # Its ownership label permits removing that container, not calling whatever
    # unrelated service owns the port to delete fixture-source or buckets.
    monkeypatch.setattr(localstack_check, "PLATFORM_ROOT", tmp_path)
    (tmp_path / ".localstack-image").write_text("localstack/localstack@sha256:" + "a" * 64)
    (tmp_path / ".terraform-version").write_text("1.17.1")
    monkeypatch.setenv("LOCALSTACK_AUTH_TOKEN", "synthetic-test-token")
    monkeypatch.setattr(localstack_check, "load_consumer", lambda *_: ({"buckets": {}}, {}))
    monkeypatch.setattr(localstack_check, "source_hashes", lambda: {})
    monkeypatch.setattr(localstack_check.shutil, "which", lambda _: "/synthetic/tool")
    monkeypatch.setattr(localstack_check.socket, "getaddrinfo", lambda *a, **kw: [(None, None, None, None, ("127.0.0.1", 4567))])
    state = {}
    calls = []
    def fake_execute(args, **kwargs):
        calls.append(args)
        if args[:2] == ["aws", "--version"]:
            output = "aws-cli/2.synthetic"
        elif args[1] == "run":
            state["label"] = args[args.index("--label") + 1].split("=", 1)[1]
            raise ValueError("synthetic port allocation failed")
        elif args[1] == "inspect":
            output = state["label"]
        else:
            output = ""
        return subprocess.CompletedProcess(args, 0, output, "")
    monkeypatch.setattr(localstack_check, "execute", fake_execute)
    def forbidden_api(*args, **kwargs):
        raise AssertionError("a failed container start must never call AWS APIs")
    monkeypatch.setattr(localstack_check, "aws", forbidden_api)
    with pytest.raises(ValueError, match="port allocation failed"):
        localstack_check.run_consumers([tmp_path / "payments"])
    assert any(args[:2] == ["docker", "rm"] for args in calls)
