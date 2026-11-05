"""Generate a consumer project from platform-owned templates, without publishing it."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from scripts.environments import ROOT, backend_name, environment_config
from scripts.team_platform import _check_identifier, validate_declaration


def onboard(destination: Path, team_id: str, owner: str, environments: list[str], *,
            platform_repository: str | None = None, platform_ref: str | None = None) -> None:
    _check_identifier(team_id, 'team_id', 16)
    declaration = validate_declaration({'schema_version': 1, 'owner': owner,
                                       'buckets': {'data': {'visibility': 'private'}}})
    if not environments or len(environments) != len(set(environments)):
        raise ValueError('choose at least one environment, without duplicates')
    for environment in environments:
        catalog = environment_config(environment)
        backend_name(catalog["account_id"], team_id)
    if bool(platform_repository) != bool(platform_ref):
        raise ValueError('platform repository and immutable ref must be supplied together')
    if platform_repository and (not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', platform_repository)
                                or not re.fullmatch(r'[0-9a-f]{40}', platform_ref or '')):
        raise ValueError('use owner/repository and an immutable forty-character commit SHA')
    if destination.exists():
        raise ValueError('destination already exists; refusing to overwrite a consumer')
    destination.mkdir(parents=True)
    (destination / 'team.json').write_text(json.dumps({'team_id': team_id}, indent=2) + '\n')
    for environment in environments:
        directory = destination / 'environments' / environment
        directory.mkdir(parents=True)
        value = {**declaration, 'schema_version': 2, 'environment': environment}
        (directory / 'resources.json').write_text(json.dumps(value, indent=2) + '\n')
        (directory / 'expectations.json').write_text(json.dumps({'required_buckets': ['data'], 'allowed_public_buckets': []}, indent=2) + '\n')
    workflow = (ROOT / 'templates/consumer/infrastructure.yml').read_text()
    suffix = ''
    if platform_repository:
        workflow = workflow.replace('PLATFORM_REPOSITORY', platform_repository).replace('PLATFORM_REF', platform_ref)
    else:
        # This checkout has not been published: no invented owner, ref or working CI claim.
        suffix = '.template'
    directory = destination / '.github/workflows'
    directory.mkdir(parents=True)
    (directory / f'infrastructure.yml{suffix}').write_text(workflow)
    (destination / '.gitignore').write_text('.runs/\n.terraform/\n*.tfstate*\n*.tfplan\n')
    (destination / 'Makefile').write_text(f'''PLATFORM_DIR ?= ../terraform_platform_abstraction
TEAM_ID := {team_id}
.PHONY: check localstack
check:
\tcd "$(PLATFORM_DIR)" && uv run python -m scripts.consumer_platform check --team-id "$(TEAM_ID)" --consumer-dir "$(CURDIR)"
localstack:
\tcd "$(PLATFORM_DIR)" && uv run python -m scripts.localstack_check --team-id "$(TEAM_ID)" --consumer-dir "$(CURDIR)"
''')
    (destination / 'README.md').write_text(f'''# {team_id} infrastructure

Edit `environments/<environment>/resources.json` and its `expectations.json`.
The JSON environment must match its directory. Bucket visibility is mandatory.

Run `make check` for credential-free checks or `make localstack` for the free
Hobby integration suite. Set `PLATFORM_DIR` when the platform is elsewhere.
No consumer Terraform, backend provisioning, or custom CI scripts are needed.

The generated workflow calls the shared platform workflow at one reviewed SHA.
A `.template` suffix means publication details have not been supplied: it does
not run in GitHub. See the platform's `docs/environments-and-delivery.md` for
activation, platform registration, state migration, approval and retirement.
''')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--team-id', required=True)
    parser.add_argument('--owner', required=True)
    parser.add_argument('--environments', nargs='+', default=['dev', 'staging', 'prod'])
    parser.add_argument('--platform-repository')
    parser.add_argument('--platform-ref')
    args = parser.parse_args()
    try:
        onboard(args.destination, args.team_id, args.owner, args.environments,
                platform_repository=args.platform_repository, platform_ref=args.platform_ref)
    except (ValueError, OSError) as exc:
        parser.exit(1, f'onboarding failed: {exc}\n')
    print(f'{args.destination}: generated locally; no Git commit, push or AWS calls')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
