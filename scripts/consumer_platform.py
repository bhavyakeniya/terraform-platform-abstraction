"""Check a separate consumer's declaration using the platform's existing root."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from scripts.environments import consumer_environments, load_environment, read_json

from scripts.team_platform import (
    _strict_json_loads,
    derive_context,
    load_declaration,
    smoke_check,
)

PLATFORM_ROOT = Path(__file__).resolve().parent.parent


def load_consumer(directory: Path, team_id: str) -> tuple[dict, dict]:
    """Combine platform validation with the consumer's own acceptance contract.

    The expectations are business regression checks, not deployment approval.
    They require named buckets and limit public ones, while allowing new private
    buckets without a platform code edit.
    """
    if directory.parent.name == "environments":
        declaration, context = load_environment(directory, team_id)
    else:
        # Legacy v1 fixtures remain supported for the low-level platform tests.
        context = derive_context(team_id, fixture_config())
        declaration = load_declaration(directory / "resources.json")
    path = directory / "expectations.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 100_000:
        raise ValueError("expectations.json must be a regular file under 100 KB")
    expectations = _strict_json_loads(path.read_text(encoding="utf-8"))
    if not isinstance(expectations, dict) or set(expectations) != {
        "required_buckets", "allowed_public_buckets"
    }:
        raise ValueError("expectations must contain required_buckets and allowed_public_buckets only")
    for key, values in expectations.items():
        if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
            raise ValueError(f"{key} must be a list of bucket keys")
        if len(values) != len(set(values)):
            raise ValueError(f"{key} must not contain duplicates")
    buckets = declaration["buckets"]
    missing = set(expectations["required_buckets"]) - buckets.keys()
    unapproved = {k for k, v in buckets.items() if v["visibility"] == "public"} - set(
        expectations["allowed_public_buckets"]
    )
    if missing:
        raise ValueError(f"consumer requires missing bucket keys: {sorted(missing)}")
    if unapproved:
        raise ValueError(f"consumer does not allow public bucket keys: {sorted(unapproved)}")
    return declaration, context


def fixture_config() -> dict:
    return json.loads((PLATFORM_ROOT / "config/fixture.json").read_text(encoding="utf-8"))


def check_consumer(directory: Path, team_id: str) -> None:
    if (directory / "environments").is_dir():
        if read_json(directory / "team.json") != {"team_id": team_id}:
            raise ValueError("team.json does not match the selected team")
        for environment in consumer_environments(directory):
            check_consumer(environment, team_id)
        return
    declaration, context = load_consumer(directory, team_id)
    # Reuse the real render -> native root path. No copied consumer Terraform.
    with tempfile.TemporaryDirectory(prefix="consumer-check-") as temporary:
        fixtures = Path(temporary)
        target = fixtures / team_id
        target.mkdir()
        (target / "resources.json").write_text(json.dumps(declaration), encoding="utf-8")
        config = fixture_config()
        config["environment"] = context["environment"]
        smoke_check(fixtures, config)
    print(f"{team_id}/{context['environment']}: declaration, expectations and mocked root PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--consumer-dir", type=Path, required=True)
    parser.add_argument("--team-id", required=True)
    args = parser.parse_args()
    try:
        check_consumer(args.consumer_dir.resolve(), args.team_id)
    except (ValueError, OSError, UnicodeError) as exc:
        parser.exit(1, f"consumer check failed: {exc}\n")
    print(f"{args.team_id}: declaration, consumer expectations, and mocked root PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
