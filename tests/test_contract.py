"""C01-C03: strict declaration loading and validation (Task 1 scope).

C01 (examples portion): minimal/mixed examples load and validate.
C02: missing/null/empty buckets, invalid/omitted visibility, wrong types/version,
     unknown/duplicate fields, non-finite JSON.
C03 (Task 1 portion): tag-unsafe owner, invalid bucket-key identifiers, symlinks.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.team_platform import load_declaration, validate_declaration

REPO_ROOT = Path(__file__).resolve().parent.parent


def write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def valid_payload() -> dict:
    return {
        "schema_version": 1,
        "owner": "team@example.invalid",
        "buckets": {"reports": {"visibility": "private"}},
    }


# --- C01: committed examples -------------------------------------------------


def test_minimal_example_is_valid():
    result = load_declaration(REPO_ROOT / "examples" / "minimal" / "resources.json")
    assert result["buckets"].keys() == {"data"}
    assert result["buckets"]["data"]["visibility"] == "private"


def test_mixed_example_is_valid():
    result = load_declaration(REPO_ROOT / "examples" / "mixed" / "resources.json")
    assert result["buckets"].keys() == {"reports", "assets"}
    assert result["buckets"]["reports"]["visibility"] == "private"
    assert result["buckets"]["assets"]["visibility"] == "public"


def test_validate_declaration_accepts_valid_payload():
    value = valid_payload()
    result = validate_declaration(value)
    assert result == value


# --- C02: buckets/visibility/type/version/unknown/duplicate/non-finite -------


def test_missing_buckets_rejected():
    value = valid_payload()
    del value["buckets"]
    with pytest.raises(ValueError):
        validate_declaration(value)


def test_null_buckets_rejected():
    value = valid_payload()
    value["buckets"] = None
    with pytest.raises(ValueError):
        validate_declaration(value)


def test_empty_buckets_rejected():
    value = valid_payload()
    value["buckets"] = {}
    with pytest.raises(ValueError):
        validate_declaration(value)


def test_missing_visibility_rejected():
    value = valid_payload()
    value["buckets"]["reports"] = {}
    with pytest.raises(ValueError):
        validate_declaration(value)


def test_null_visibility_rejected():
    value = valid_payload()
    value["buckets"]["reports"]["visibility"] = None
    with pytest.raises(ValueError):
        validate_declaration(value)


@pytest.mark.parametrize("bad_value", ["Public", "PRIVATE", "", "pub", True, 1, []])
def test_invalid_visibility_values_rejected(bad_value):
    value = valid_payload()
    value["buckets"]["reports"]["visibility"] = bad_value
    with pytest.raises(ValueError):
        validate_declaration(value)


def test_wrong_type_buckets_rejected():
    value = valid_payload()
    value["buckets"] = "reports"
    with pytest.raises(ValueError):
        validate_declaration(value)


def test_wrong_type_owner_rejected():
    value = valid_payload()
    value["owner"] = 12345
    with pytest.raises(ValueError):
        validate_declaration(value)


def test_schema_version_boolean_rejected():
    value = valid_payload()
    value["schema_version"] = True
    with pytest.raises(ValueError):
        validate_declaration(value)


def test_schema_version_wrong_integer_rejected():
    value = valid_payload()
    value["schema_version"] = 2
    with pytest.raises(ValueError):
        validate_declaration(value)


def test_schema_version_missing_rejected():
    value = valid_payload()
    del value["schema_version"]
    with pytest.raises(ValueError):
        validate_declaration(value)


def test_unknown_top_level_field_rejected():
    value = valid_payload()
    value["account"] = "000000000000"
    with pytest.raises(ValueError):
        validate_declaration(value)


def test_unknown_bucket_field_rejected():
    value = valid_payload()
    value["buckets"]["reports"]["extra"] = "x"
    with pytest.raises(ValueError):
        validate_declaration(value)


def test_non_dict_input_rejected():
    with pytest.raises(ValueError):
        validate_declaration(["not", "a", "dict"])


def test_duplicate_top_level_key_rejected(tmp_path):
    raw = (
        '{"schema_version": 1, "owner": "a@example.invalid", '
        '"buckets": {"reports": {"visibility": "private"}}, '
        '"owner": "b@example.invalid"}'
    )
    path = write(tmp_path, "resources.json", raw)
    with pytest.raises(ValueError):
        load_declaration(path)


def test_duplicate_nested_key_rejected(tmp_path):
    raw = (
        '{"schema_version": 1, "owner": "a@example.invalid", '
        '"buckets": {"reports": {"visibility": "private", "visibility": "public"}}}'
    )
    path = write(tmp_path, "resources.json", raw)
    with pytest.raises(ValueError):
        load_declaration(path)


def test_duplicate_bucket_key_rejected(tmp_path):
    raw = (
        '{"schema_version": 1, "owner": "a@example.invalid", '
        '"buckets": {"reports": {"visibility": "private"}, '
        '"reports": {"visibility": "public"}}}'
    )
    path = write(tmp_path, "resources.json", raw)
    with pytest.raises(ValueError):
        load_declaration(path)


@pytest.mark.parametrize("const", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_json_constants_rejected(tmp_path, const):
    raw = (
        '{"schema_version": 1, "owner": "a@example.invalid", '
        '"buckets": {"reports": {"visibility": "private"}}, "x": ' + const + "}"
    )
    path = write(tmp_path, "resources.json", raw)
    with pytest.raises(ValueError):
        load_declaration(path)


def test_malformed_json_rejected(tmp_path):
    path = write(tmp_path, "resources.json", "{not valid json")
    with pytest.raises(ValueError):
        load_declaration(path)


def test_non_utf8_input_rejected(tmp_path):
    path = tmp_path / "resources.json"
    path.write_bytes(b"\xff\xfe\x00\x01")
    with pytest.raises(ValueError):
        load_declaration(path)


# --- C03 (Task 1 portion): owner, bucket-key identifiers, symlinks -----------


@pytest.mark.parametrize(
    "bad_owner",
    [
        "",
        " team@example.invalid",
        "team@example.invalid ",
        "team,other@example.invalid",
        "team\n@example.invalid",
        "téam@example.invalid",
        "👍@example.invalid",
    ],
)
def test_tag_unsafe_owner_rejected(bad_owner):
    value = valid_payload()
    value["owner"] = bad_owner
    with pytest.raises(ValueError):
        validate_declaration(value)


@pytest.mark.parametrize(
    "bad_key",
    [
        "Reports",  # uppercase
        "-reports",  # leading hyphen
        "reports-",  # trailing hyphen
        "re--ports",  # consecutive hyphens
        "re_ports",  # underscore
        "",  # empty
        "a" * 17,  # over max length
        "1reports",  # must start with a letter
        "reports\n",  # trailing newline (Python $ matches before a final \n)
    ],
)
def test_invalid_bucket_key_rejected(bad_key):
    value = valid_payload()
    value["buckets"] = {bad_key: {"visibility": "private"}}
    with pytest.raises(ValueError):
        validate_declaration(value)


def test_symlinked_declaration_rejected(tmp_path):
    real = write(tmp_path, "real.json", json.dumps(valid_payload()))
    link = tmp_path / "resources.json"
    link.symlink_to(real)
    with pytest.raises(ValueError):
        load_declaration(link)


def test_missing_file_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_declaration(tmp_path / "does-not-exist.json")


def test_directory_path_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_declaration(tmp_path)


def test_oversized_declaration_rejected_before_reading(tmp_path):
    # Padding via a long owner value would fail schema validation anyway;
    # pad with harmless extra JSON whitespace so the size check is what
    # actually trips, not some other rule.
    huge = valid_payload()
    path = tmp_path / "resources.json"
    path.write_text(json.dumps(huge) + " " * 1_000_001, encoding="utf-8")
    with pytest.raises(ValueError, match="exceeds"):
        load_declaration(path)


# --- CLI ----------------------------------------------------------------------


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "team_platform.py"), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def test_cli_validate_minimal_example_exits_zero():
    result = run_cli("validate", "--file", "examples/minimal/resources.json")
    assert result.returncode == 0, result.stderr


def test_cli_validate_mixed_example_exits_zero():
    result = run_cli("validate", "--file", "examples/mixed/resources.json")
    assert result.returncode == 0, result.stderr


def test_cli_validate_invalid_file_exits_nonzero(tmp_path):
    bad = write(tmp_path, "resources.json", '{"schema_version": 1}')
    result = run_cli("validate", "--file", str(bad))
    assert result.returncode != 0
    assert "owner" in result.stderr or "buckets" in result.stderr
