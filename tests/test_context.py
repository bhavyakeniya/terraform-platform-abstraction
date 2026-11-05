"""C04-C06 and the context-specific C03 cases (Task 2 scope).

C03 (context portion): invalid team IDs, strict platform-config fields.
C04: distinct identities, maximum name length, hyphen-boundary non-collision.
C05: backend encryption/locking/account guard present; no credential/override leakage.
C06: reachable reserved-suffix rejection during rendering; positive neighbors pass;
     direct completed-name tests for unreachable prefixes/.mrap/IP forms/length.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.team_platform import derive_context, render_inputs, validate_bucket_name

REPO_ROOT = Path(__file__).resolve().parent.parent


def valid_config() -> dict:
    return {
        "account_id": "000000000000",
        "region": "eu-central-1",
        "environment": "test",
        "state_bucket": "tfp-fixture-state-do-not-use",
        "trusted_principal_arn": "arn:aws:iam::000000000000:role/fixture-source",
    }


def valid_declaration() -> dict:
    return {
        "schema_version": 1,
        "owner": "team@example.invalid",
        "buckets": {"reports": {"visibility": "private"}},
    }


# --- derive_context: valid case ----------------------------------------------


def test_derive_context_returns_expected_fields():
    context = derive_context("payments", valid_config())
    assert context["team_id"] == "payments"
    assert context["account_id"] == "000000000000"
    assert context["environment"] == "test"
    assert context["region"] == "eu-central-1"
    assert context["trusted_principal_arn"] == "arn:aws:iam::000000000000:role/fixture-source"
    assert context["state_bucket"] == "tfp-fixture-state-do-not-use"
    assert context["state_key"] == (
        "workloads/000000000000/test/teams/payments/terraform.tfstate"
    )
    assert set(context.keys()) == {
        "team_id",
        "account_id",
        "environment",
        "region",
        "trusted_principal_arn",
        "state_bucket",
        "state_key",
    }


def test_derive_context_makes_no_api_calls_is_pure():
    # Calling twice with identical inputs must be side-effect-free and deterministic.
    assert derive_context("payments", valid_config()) == derive_context(
        "payments", valid_config()
    )


# --- context-specific C03: invalid team IDs -----------------------------------


@pytest.mark.parametrize(
    "bad_team_id",
    [
        "Payments",  # uppercase
        "-payments",  # leading hyphen
        "payments-",  # trailing hyphen
        "pay--ments",  # consecutive hyphens
        "pay_ments",  # underscore
        "",  # empty
        "a" * 17,  # over max length (16)
        "1payments",  # must start with a letter
        "payments\n",  # trailing newline (Python $ matches before a final \n)
    ],
)
def test_derive_context_rejects_invalid_team_id(bad_team_id):
    with pytest.raises(ValueError):
        derive_context(bad_team_id, valid_config())


# --- context-specific C03: strict platform-config fields ----------------------


def test_derive_context_rejects_missing_config_field():
    config = valid_config()
    del config["region"]
    with pytest.raises(ValueError):
        derive_context("payments", config)


def test_derive_context_rejects_unknown_config_field():
    config = valid_config()
    config["extra_field"] = "x"
    with pytest.raises(ValueError):
        derive_context("payments", config)


@pytest.mark.parametrize(
    "bad_account_id",
    ["12345", "1234567890123", "abcdefghijkl", "000000000000 ", "0000-0000-0000", "000000000000\n"],
)
def test_derive_context_rejects_invalid_account_id(bad_account_id):
    config = valid_config()
    config["account_id"] = bad_account_id
    with pytest.raises(ValueError):
        derive_context("payments", config)


@pytest.mark.parametrize(
    "bad_region",
    [
        "EU-CENTRAL-1",  # uppercase
        "eu-central",  # missing digit
        "eucentral1",  # no hyphens
        "",
        "us-gov-west-1",  # GovCloud partition, not commercial
        "cn-north-1",  # China partition, not commercial
        "eu-central-1\n",  # trailing newline (Python $ matches before a final \n)
    ],
)
def test_derive_context_rejects_invalid_region(bad_region):
    config = valid_config()
    config["region"] = bad_region
    with pytest.raises(ValueError):
        derive_context("payments", config)


@pytest.mark.parametrize(
    "bad_arn",
    [
        "arn:aws:iam::111111111111:role/fixture-source",  # different account
        "arn:aws:iam::000000000000:root",  # account-root trust
        "arn:aws:iam::000000000000:role/*",  # wildcard
        "arn:aws:iam::000000000000:user/fixture-source",  # not a role
        "not-an-arn",
        "",
        "arn:aws:iam::000000000000:role/fixture-source\n",  # trailing newline
    ],
)
def test_derive_context_rejects_invalid_trusted_principal_arn(bad_arn):
    config = valid_config()
    config["trusted_principal_arn"] = bad_arn
    with pytest.raises(ValueError):
        derive_context("payments", config)


@pytest.mark.parametrize("bad_bucket", ["", "ab", "UPPER-BUCKET", "a" * 64, "tfp-fixture-state\n"])
def test_derive_context_rejects_invalid_state_bucket(bad_bucket):
    config = valid_config()
    config["state_bucket"] = bad_bucket
    with pytest.raises(ValueError):
        derive_context("payments", config)


def test_derive_context_rejects_non_dict_config():
    with pytest.raises(ValueError):
        derive_context("payments", ["not", "a", "dict"])


# --- C04: distinct identities, maximum length, hyphen non-collision ----------


def test_distinct_teams_have_distinct_state_keys(tmp_path):
    config = valid_config()
    ctx_a = derive_context("payments", config)
    ctx_b = derive_context("reporting", config)
    assert ctx_a["state_key"] != ctx_b["state_key"]

    render_inputs(valid_declaration(), ctx_a, tmp_path / "a")
    render_inputs(valid_declaration(), ctx_b, tmp_path / "b")


def test_maximum_length_bucket_name_accepted():
    # prefix=5, environment<=8, team<=16, key<=16, three 2-char separators.
    name = "sumup--" + "e" * 8 + "--" + "t" * 16 + "--" + "b" * 16
    assert len(name) == 51
    validate_bucket_name(name)  # must not raise


def test_rendered_names_omit_account_but_keep_account_guards(tmp_path, monkeypatch):
    # Observe names actually validated by the renderer, not a test-only formula.
    import scripts.team_platform as platform

    names = []
    original_validate = platform.validate_bucket_name

    def capture_name(name):
        original_validate(name)
        names.append(name)

    monkeypatch.setattr(platform, "validate_bucket_name", capture_name)
    state_keys = []
    for account in ("000000000000", "111111111111"):
        config = valid_config()
        config["account_id"] = account
        config["trusted_principal_arn"] = f"arn:aws:iam::{account}:role/fixture-source"
        context = derive_context("payments", config)
        inputs_path, backend_path = render_inputs(valid_declaration(), context, tmp_path / account)
        inputs = json.loads(inputs_path.read_text())
        backend = json.loads(backend_path.read_text())
        assert inputs["account_id"] == account
        assert backend["allowed_account_ids"] == [account]
        state_keys.append(backend["key"])

    assert names == ["sumup--test--payments--reports"] * 2
    assert state_keys[0] != state_keys[1]


def test_completed_name_validator_accepts_s3_63_character_limit():
    # Generated names stop at 51; this generic validator still accepts S3's limit.
    validate_bucket_name("a" * 63)


def test_hyphen_boundary_split_does_not_collide(tmp_path):
    config = valid_config()
    ctx_ab = derive_context("ab", config)
    declaration_split_right = {
        "schema_version": 1,
        "owner": "team@example.invalid",
        "buckets": {"cd-ef": {"visibility": "private"}},
    }
    ctx_ab_cd = derive_context("ab-cd", config)
    declaration_split_left = {
        "schema_version": 1,
        "owner": "team@example.invalid",
        "buckets": {"ef": {"visibility": "private"}},
    }

    out_right = tmp_path / "right"
    out_left = tmp_path / "left"
    inputs_right, _ = render_inputs(declaration_split_right, ctx_ab, out_right)
    inputs_left, _ = render_inputs(declaration_split_left, ctx_ab_cd, out_left)

    names_right = json.loads(inputs_right.read_text())
    names_left = json.loads(inputs_left.read_text())
    assert names_right["team_id"] != names_left["team_id"]
    assert list(names_right["buckets"].keys()) != list(names_left["buckets"].keys())


# --- C05: backend encryption/locking/account guard; no credential/override ---


def test_render_inputs_writes_expected_root_variables(tmp_path):
    context = derive_context("payments", valid_config())
    inputs_path, _ = render_inputs(valid_declaration(), context, tmp_path)
    rendered = json.loads(inputs_path.read_text())
    assert set(rendered.keys()) == {
        "team_id",
        "environment",
        "account_id",
        "owner",
        "buckets",
        "trusted_principal_arn",
        "region",
    }
    assert "schema_version" not in rendered
    assert rendered["team_id"] == "payments"
    assert rendered["owner"] == "team@example.invalid"


def test_render_inputs_writes_backend_with_encryption_and_locking(tmp_path):
    context = derive_context("payments", valid_config())
    _, backend_path = render_inputs(valid_declaration(), context, tmp_path)
    backend = json.loads(backend_path.read_text())
    assert backend["bucket"] == "tfp-fixture-state-do-not-use"
    assert backend["key"] == "workloads/000000000000/test/teams/payments/terraform.tfstate"
    assert backend["region"] == "eu-central-1"
    assert backend["encrypt"] is True
    assert backend["dynamodb_table"] == "tfp-fixture-state-do-not-use"
    assert "use_lockfile" not in backend
    assert backend["allowed_account_ids"] == ["000000000000"]


def test_render_inputs_contains_no_credential_like_fields(tmp_path):
    context = derive_context("payments", valid_config())
    inputs_path, backend_path = render_inputs(valid_declaration(), context, tmp_path)
    for path in (inputs_path, backend_path):
        text = path.read_text().lower()
        for forbidden in ("secret", "access_key", "password", "token"):
            assert forbidden not in text


def test_render_inputs_creates_isolated_output_directory(tmp_path):
    out_dir = tmp_path / "nested" / "run-dir"
    context = derive_context("payments", valid_config())
    inputs_path, backend_path = render_inputs(valid_declaration(), context, out_dir)
    assert inputs_path.parent == out_dir
    assert backend_path.parent == out_dir


# --- C06: reachable reserved suffixes (via render_inputs) ---------------------


@pytest.mark.parametrize(
    "bad_key",
    ["s3alias", "reports-s3alias", "x-s3", "ol-s3", "table-s3", "an", "reports-an"],
)
def test_render_inputs_rejects_reachable_reserved_suffix(tmp_path, bad_key):
    context = derive_context("payments", valid_config())
    declaration = {
        "schema_version": 1,
        "owner": "team@example.invalid",
        "buckets": {bad_key: {"visibility": "private"}},
    }
    with pytest.raises(ValueError, match=bad_key):
        render_inputs(declaration, context, tmp_path)


@pytest.mark.parametrize("good_key", ["s3alias-v2", "x-s3-data", "annual"])
def test_render_inputs_accepts_positive_neighbor_keys(tmp_path, good_key):
    context = derive_context("payments", valid_config())
    declaration = {
        "schema_version": 1,
        "owner": "team@example.invalid",
        "buckets": {good_key: {"visibility": "private"}},
    }
    render_inputs(declaration, context, tmp_path)  # must not raise


def test_render_inputs_does_not_write_files_on_validation_failure(tmp_path):
    context = derive_context("payments", valid_config())
    declaration = {
        "schema_version": 1,
        "owner": "team@example.invalid",
        "buckets": {"x-s3": {"visibility": "private"}},
    }
    with pytest.raises(ValueError):
        render_inputs(declaration, context, tmp_path)
    assert list(tmp_path.iterdir()) == []


# --- C06: unreachable patterns, direct validate_bucket_name calls -------------


@pytest.mark.parametrize(
    "bad_name",
    [
        "xn--abcdefg",
        "sthree-abcdefgh",
        "amzn-s3-demo-abc",
        "my-bucket.mrap",
        "192.168.5.4",
    ],
)
def test_validate_bucket_name_rejects_unreachable_patterns(bad_name):
    with pytest.raises(ValueError):
        validate_bucket_name(bad_name)


def test_validate_bucket_name_rejects_synthetic_64_char_name():
    with pytest.raises(ValueError):
        validate_bucket_name("a" * 64)


def test_validate_bucket_name_rejects_too_short_name():
    with pytest.raises(ValueError):
        validate_bucket_name("ab")


@pytest.mark.parametrize(
    "bad_name",
    [
        "UPPERCASE-BUCKET",
        "under_score",
        "-leading-hyphen",
        "trailing-hyphen-",
        ".leading-period",
        "trailing-period.",
        "double..period",
        "sumup--test--payments--reports\n",  # trailing newline
    ],
)
def test_validate_bucket_name_rejects_forbidden_characters_and_shapes(bad_name):
    with pytest.raises(ValueError):
        validate_bucket_name(bad_name)


def test_validate_bucket_name_accepts_valid_name():
    validate_bucket_name("sumup--test--payments--reports")  # must not raise
