"""Team platform helper.

Strict declaration validation, platform-context derivation, input rendering,
and credential-free fixture checks against the generic root.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import jsonschema

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "team.schema.json"
_SCHEMA_VERSION = 1
# A declaration/config file has no business being large; this just stops a
# pathological file (accidental or malicious, e.g. in an open PR before
# review) from being read fully into memory. Generous relative to any
# realistic declaration (a few hundred 16-char-max buckets is still tiny).
_MAX_DECLARATION_BYTES = 1_000_000

# Section 3.1: team/bucket-key identifiers, reused in Python for fields that
# never flow through the declaration JSON Schema (team_id, environment).
_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_TEAM_ID_MAX_LENGTH = 16
_ENVIRONMENT_MAX_LENGTH = 8

_ACCOUNT_ID_RE = re.compile(r"^\d{12}$")
# Structurally excludes GovCloud ("us-gov-west-1" has three hyphenated letter
# groups before the digit, not two) and is additionally denylisted below for
# the China partition, which this single regex can't distinguish from a
# commercial region name shape. This is a pragmatic approximation, not a full
# partition table; real provider execution's allowed_account_ids/caller check
# (Section 3.2) is the actual safety mechanism.
_REGION_RE = re.compile(r"^[a-z]{2}-[a-z]+-\d+$")
_NON_COMMERCIAL_REGION_PREFIXES = ("cn-",)

# Section 6.2 (trust): exact same-account role ARN, never account-root or a
# wildcard/non-role principal.
_ROLE_ARN_RE = re.compile(r"^arn:aws:iam::(\d{12}):role/[A-Za-z0-9+=,.@_-]{1,64}$")

_CONFIG_FIELDS = {"account_id", "region", "environment", "state_bucket", "trusted_principal_arn"}

# Section 3.3: reserved S3 name prefixes/suffixes. The fixed sumup--<environment>--
# ...-- grammar can never produce the prefix cases or the IP/.mrap suffix
# cases through a real team declaration (no component contains a period, and
# the name always starts with "sumup--"); they're still enforced here for
# direct calls against arbitrary names. Pin to AWS's bucket-naming-rules page
# and recheck on dependency changes.
_RESERVED_BUCKET_PREFIXES = ("xn--", "sthree-", "amzn-s3-demo-")
_RESERVED_BUCKET_SUFFIXES = ("-s3alias", "--ol-s3", ".mrap", "--x-s3", "--table-s3", "-an")
_BUCKET_CHARSET_RE = re.compile(r"^[a-z0-9.-]+$")
_IP_ADDRESS_FORM_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")


def _load_schema() -> dict[str, Any]:
    with _SCHEMA_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


_VALIDATOR = jsonschema.Draft7Validator(_load_schema())


def _reject_non_finite(constant: str) -> Any:
    raise ValueError(f"non-finite JSON constant: {constant}")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _strict_json_loads(text: str) -> Any:
    """Decode JSON, rejecting duplicate keys at every depth and non-finite constants."""
    return json.loads(
        text,
        object_pairs_hook=_no_duplicate_keys,
        parse_constant=_reject_non_finite,
    )


def validate_declaration(value: Any) -> dict[str, Any]:
    """Validate an already-decoded declaration object against the closed schema.

    No coercion: the input must already be exactly the types the schema expects.
    Used both for file-loaded declarations and for declarations strictly decoded
    from other sources (e.g. committed Git blobs in later tasks).
    """
    if not isinstance(value, dict):
        raise ValueError(f"declaration must be a JSON object, got {type(value).__name__}")
    try:
        _VALIDATOR.validate(value)
    except jsonschema.exceptions.ValidationError as exc:
        location = "/".join(str(part) for part in exc.absolute_path) or "<root>"
        raise ValueError(f"{location}: {exc.message}") from exc
    # Belt-and-suspenders: schema_version must be the literal integer 1, never a
    # bool (Python bool is a subclass of int) and never coerced from another type.
    schema_version = value.get("schema_version")
    if type(schema_version) is not int or schema_version != _SCHEMA_VERSION:
        raise ValueError(
            f"schema_version: must be the integer {_SCHEMA_VERSION}, got {schema_version!r}"
        )
    # The schema's character-class pattern anchors leading whitespace out but not
    # trailing whitespace (the last character is drawn from the same class as the
    # middle ones), so outer whitespace needs an explicit strip-comparison here.
    owner = value["owner"]
    if owner != owner.strip():
        raise ValueError("owner: must not have leading or trailing whitespace")
    # Belt-and-suspenders, Python-specific: jsonschema validates "pattern" using
    # Python's re module, whose $ anchor (unlike true ECMA-262 $) matches just
    # before a trailing newline -- "reports\n" would otherwise pass the schema's
    # portable pattern. fullmatch() closes that gap without making the schema
    # file itself non-portable (a prior \Z-based fix broke real ECMA-262/JS
    # consumers of this same schema; verified directly against Node's engine).
    for bucket_key in value["buckets"]:
        if not _IDENTIFIER_RE.fullmatch(bucket_key) or len(bucket_key) > 16:
            raise ValueError(f"buckets/{bucket_key!r}: must match {_IDENTIFIER_RE.pattern!r} with max length 16")
    return value


def load_declaration(path: Path) -> dict[str, Any]:
    """Strictly load and validate a team declaration file.

    Rejects symlinks, non-files, non-UTF-8 content, duplicate JSON keys, and
    non-finite JSON constants before schema validation runs.
    """
    if path.is_symlink():
        raise ValueError(f"{path}: refusing to read a symlink")
    if not path.is_file():
        raise ValueError(f"{path}: not a regular file")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError(f"{path}: cannot stat file: {exc}") from exc
    if size > _MAX_DECLARATION_BYTES:
        raise ValueError(f"{path}: {size} bytes exceeds the {_MAX_DECLARATION_BYTES}-byte declaration limit")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"{path}: cannot read file: {exc}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path}: not valid UTF-8: {exc}") from exc
    try:
        value = _strict_json_loads(text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc
    try:
        return validate_declaration(value)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc


def validate_bucket_name(name: str) -> None:
    """Validate a completed S3 bucket name: length, character shape, and the
    reserved prefix/suffix list from Section 3.3. Raises ValueError identifying
    the violated rule. Operates on the finished string, independent of whether
    it came from our naming formula."""
    if not (3 <= len(name) <= 63):
        raise ValueError(f"bucket name length {len(name)} is outside 3-63: {name!r}")
    if not _BUCKET_CHARSET_RE.fullmatch(name):
        raise ValueError(f"bucket name has characters outside [a-z0-9.-]: {name!r}")
    if name[0] in ".-" or name[-1] in ".-":
        raise ValueError(f"bucket name must start and end with a letter or digit: {name!r}")
    if ".." in name:
        raise ValueError(f"bucket name must not contain two adjacent periods: {name!r}")
    if _IP_ADDRESS_FORM_RE.fullmatch(name):
        raise ValueError(f"bucket name must not be formatted as an IP address: {name!r}")
    for prefix in _RESERVED_BUCKET_PREFIXES:
        if name.startswith(prefix):
            raise ValueError(f"bucket name starts with reserved prefix {prefix!r}: {name!r}")
    for suffix in _RESERVED_BUCKET_SUFFIXES:
        if name.endswith(suffix):
            raise ValueError(f"bucket name ends with reserved suffix {suffix!r}: {name!r}")


def _check_identifier(value: Any, field_name: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name}: must be a string, got {type(value).__name__}")
    if len(value) > max_length or not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(
            f"{field_name}: must match {_IDENTIFIER_RE.pattern!r} with max length "
            f"{max_length}, got {value!r}"
        )
    return value


def _check_state_bucket(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError(f"state_bucket: must be a string, got {type(value).__name__}")
    if not (3 <= len(value) <= 63) or not _BUCKET_CHARSET_RE.fullmatch(value):
        raise ValueError(f"state_bucket: not a plausible S3 bucket name: {value!r}")
    if value[0] in ".-" or value[-1] in ".-":
        raise ValueError(f"state_bucket: must start and end with a letter or digit: {value!r}")
    return value


def derive_context(team_id: Any, config: Any) -> dict[str, Any]:
    """Validate team_id and the platform config, then return the pure, derived
    execution context. No API calls, no defaults, no coercion."""
    team_id = _check_identifier(team_id, "team_id", _TEAM_ID_MAX_LENGTH)

    if not isinstance(config, dict):
        raise ValueError(f"config: must be a JSON object, got {type(config).__name__}")
    if set(config.keys()) != _CONFIG_FIELDS:
        missing = _CONFIG_FIELDS - config.keys()
        unknown = config.keys() - _CONFIG_FIELDS
        raise ValueError(f"config: missing {sorted(missing)}, unknown {sorted(unknown)}")

    account_id = config["account_id"]
    if not isinstance(account_id, str) or not _ACCOUNT_ID_RE.fullmatch(account_id):
        raise ValueError(f"account_id: must be exactly 12 digits, got {account_id!r}")

    region = config["region"]
    if (
        not isinstance(region, str)
        or not _REGION_RE.fullmatch(region)
        or region.startswith(_NON_COMMERCIAL_REGION_PREFIXES)
    ):
        raise ValueError(f"region: not a supported commercial region: {region!r}")

    environment = _check_identifier(config["environment"], "environment", _ENVIRONMENT_MAX_LENGTH)

    state_bucket = _check_state_bucket(config["state_bucket"])

    trusted_principal_arn = config["trusted_principal_arn"]
    match = (
        _ROLE_ARN_RE.fullmatch(trusted_principal_arn)
        if isinstance(trusted_principal_arn, str)
        else None
    )
    if match is None:
        raise ValueError(
            "trusted_principal_arn: must be an exact same-account IAM role ARN "
            f"(no wildcard/account-root trust), got {trusted_principal_arn!r}"
        )
    if match.group(1) != account_id:
        raise ValueError(
            f"trusted_principal_arn: account {match.group(1)!r} does not match "
            f"account_id {account_id!r} (must be same-account trust)"
        )

    state_key = f"workloads/{account_id}/{environment}/teams/{team_id}/terraform.tfstate"

    return {
        "team_id": team_id,
        "account_id": account_id,
        "environment": environment,
        "region": region,
        "trusted_principal_arn": trusted_principal_arn,
        "state_bucket": state_bucket,
        "state_key": state_key,
    }


def render_inputs(
    declaration: dict[str, Any], context: dict[str, Any], output_dir: Path
) -> tuple[Path, Path]:
    """Validate every completed bucket name, then write inputs.tfvars.json and
    backend.hcl.json into output_dir. Pure: no Terraform init, no AWS calls, no
    credentials. Writes nothing if any bucket name fails validation."""
    bucket_names: dict[str, str] = {}
    for bucket_key in declaration["buckets"]:
        name = (
            f"sumup--{context['environment']}--"
            f"{context['team_id']}--{bucket_key}"
        )
        validate_bucket_name(name)
        bucket_names[bucket_key] = name

    inputs = {
        "team_id": context["team_id"],
        "environment": context["environment"],
        "account_id": context["account_id"],
        "owner": declaration["owner"],
        "buckets": declaration["buckets"],
        "trusted_principal_arn": context["trusted_principal_arn"],
        "region": context["region"],
    }
    if "permissions_boundary_arn" in context:
        inputs["permissions_boundary_arn"] = context["permissions_boundary_arn"]
    backend = {
        "bucket": context["state_bucket"],
        "key": context["state_key"],
        "region": context["region"],
        "encrypt": True,
        "dynamodb_table": context.get("dynamodb_table", context["state_bucket"]),
        "allowed_account_ids": [context["account_id"]],
    }

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        inputs_path = output_dir / "inputs.tfvars.json"
        backend_path = output_dir / "backend.hcl.json"
        inputs_path.write_text(json.dumps(inputs, indent=2, sort_keys=True), encoding="utf-8")
        backend_path.write_text(json.dumps(backend, indent=2, sort_keys=True), encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"{output_dir}: cannot write rendered output: {exc}") from exc
    return inputs_path, backend_path


_STACKS_DIR = Path(__file__).resolve().parent.parent / "stacks" / "team"


def _terraform_bin() -> str:
    # Match Make's local preference for direct CLI consumers too. Previously
    # smoke-check only worked when Make injected an override; invoking the
    # helper directly could accidentally select an older system Terraform.
    override = os.environ.get("TEAM_PLATFORM_TERRAFORM")
    if override:
        return override
    local = Path(__file__).resolve().parent.parent / ".local/bin/terraform"
    return str(local) if local.is_file() and os.access(local, os.X_OK) else "terraform"


_TERRAFORM_INIT_TIMEOUT_SECONDS = 120
_TERRAFORM_TEST_TIMEOUT_SECONDS = 120


def _terraform_init(tf_data_dir: Path) -> dict[str, str]:
    env = {**os.environ, "TF_DATA_DIR": str(tf_data_dir)}
    try:
        result = subprocess.run(
            [_terraform_bin(), f"-chdir={_STACKS_DIR}", "init", "-backend=false", "-lockfile=readonly"],
            capture_output=True,
            text=True,
            env=env,
            timeout=_TERRAFORM_INIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"terraform init timed out after {_TERRAFORM_INIT_TIMEOUT_SECONDS}s") from exc
    if result.returncode != 0:
        raise ValueError(f"terraform init failed: {result.stderr.strip()}")
    return env


def _run_mocked_root_test(inputs_path: Path, env: dict[str, str]) -> None:
    try:
        result = subprocess.run(
            [
                _terraform_bin(),
                f"-chdir={_STACKS_DIR}",
                "test",
                "-filter=tests/declaration.tftest.hcl",
                f"-var-file={inputs_path}",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=_TERRAFORM_TEST_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"mocked root check timed out after {_TERRAFORM_TEST_TIMEOUT_SECONDS}s") from exc
    if result.returncode != 0:
        raise ValueError(f"mocked root check failed:\n{result.stdout.strip()}\n{result.stderr.strip()}")


def smoke_check(fixtures_dir: Path, config: dict[str, Any]) -> None:
    """Render every <fixtures_dir>/<id>/resources.json and run the mocked root
    check against it, sharing one Terraform init. fixtures_dir holds
    ephemeral, uncommitted declarations, so nothing here reads committed
    state. This backs the always-run CI fixture-smoke job: a readiness signal
    that the pipeline executes in the live environment, not proof of
    correctness at scale or of AWS behavior.
    """
    fixture_ids = sorted(p.name for p in fixtures_dir.iterdir() if (p / "resources.json").is_file())
    if not fixture_ids:
        return

    with tempfile.TemporaryDirectory(prefix="smoke-check-") as tmp:
        tmp_path = Path(tmp)
        env = _terraform_init(tmp_path / ".terraform-data")

        failures: list[str] = []
        for i, fixture_id in enumerate(fixture_ids):
            try:
                declaration = load_declaration(fixtures_dir / fixture_id / "resources.json")
                context = derive_context(fixture_id, config)
                inputs_path, _ = render_inputs(declaration, context, tmp_path / f"fixture-{i}")
                _run_mocked_root_test(inputs_path, env)
            except ValueError as exc:
                failures.append(f"{fixture_id}: {exc}")

    if failures:
        raise ValueError(f"fixture smoke had {len(failures)} failure(s):\n\n" + "\n\n".join(failures))


def _load_config(path: Path) -> dict[str, Any]:
    """Strictly load a platform config file (same duplicate-key/UTF-8/non-finite
    rules as a declaration; field-level validation happens in derive_context)."""
    if path.is_symlink():
        raise ValueError(f"{path}: refusing to read a symlink")
    if not path.is_file():
        raise ValueError(f"{path}: not a regular file")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError(f"{path}: cannot stat file: {exc}") from exc
    if size > _MAX_DECLARATION_BYTES:
        raise ValueError(f"{path}: {size} bytes exceeds the {_MAX_DECLARATION_BYTES}-byte config limit")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"{path}: cannot read file: {exc}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path}: not valid UTF-8: {exc}") from exc
    try:
        return _strict_json_loads(text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc


def _cmd_validate(args: argparse.Namespace) -> int:
    try:
        load_declaration(Path(args.file))
    except ValueError as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return 1
    print(f"valid: {args.file}")
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    try:
        declaration = load_declaration(Path(args.file))
        config = _load_config(Path(args.config))
        context = derive_context(args.team_id, config)
        inputs_path, backend_path = render_inputs(declaration, context, Path(args.out))
    except ValueError as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return 1
    print(f"rendered: {inputs_path}")
    print(f"rendered: {backend_path}")
    return 0


def _cmd_smoke_check(args: argparse.Namespace) -> int:
    try:
        config = _load_config(Path(args.config))
        smoke_check(Path(args.fixtures_dir), config)
    except ValueError as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return 1
    print("fixture smoke: ok")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="team_platform.py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate", help="Strictly validate a team declaration file"
    )
    validate_parser.add_argument("--file", required=True, help="Path to resources.json")
    validate_parser.set_defaults(func=_cmd_validate)

    render_parser = subparsers.add_parser(
        "render", help="Validate a declaration and context, then render root/backend JSON"
    )
    render_parser.add_argument("--file", required=True, help="Path to resources.json")
    render_parser.add_argument("--team-id", required=True)
    render_parser.add_argument("--config", required=True, help="Path to platform config JSON")
    render_parser.add_argument("--out", required=True, help="Output directory")
    render_parser.set_defaults(func=_cmd_render)

    smoke_check_parser = subparsers.add_parser(
        "smoke-check", help="Run the mocked root check over ephemeral fixtures (CI fixture-smoke job)"
    )
    smoke_check_parser.add_argument(
        "--fixtures-dir", required=True, help="Directory of <id>/resources.json ephemeral fixtures"
    )
    smoke_check_parser.add_argument("--config", required=True, help="Path to platform config JSON")
    smoke_check_parser.set_defaults(func=_cmd_smoke_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
