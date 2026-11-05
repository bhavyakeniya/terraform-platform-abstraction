"""Environment catalog and version-two declarations. No AWS calls."""
from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema

from scripts.team_platform import (
    _check_identifier, _strict_json_loads, derive_context, validate_bucket_name, validate_declaration,
)

ROOT = Path(__file__).resolve().parent.parent


def read_json(path: Path, limit: int = 1_000_000) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError(f'{path}: must be a regular, non-symlink file under {limit} bytes')
    value = _strict_json_loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError(f'{path}: expected a JSON object')
    return value


def environment_config(environment: str) -> dict:
    _check_identifier(environment, 'environment', 8)
    value = read_json(ROOT / 'config/environments' / f'{environment}.json')
    if set(value) != {'account_id', 'region', 'deployment_enabled'} or type(value['deployment_enabled']) is not bool:
        raise ValueError('environment catalog requires account_id, region, deployment_enabled only')
    # Reuse all account, region and identifier checks without cloud credentials.
    derive_context('validation', {'account_id': value['account_id'], 'region': value['region'],
        'environment': environment, 'state_bucket': 'validation-only',
        'trusted_principal_arn': f"arn:aws:iam::{value['account_id']}:role/validation-only"})
    for other_path in (ROOT / 'config/environments').glob('*.json'):
        other = read_json(other_path)
        if other.get('account_id') == value['account_id'] and other.get('region') != value['region']:
            raise ValueError('one account must use one consistent backend region across environments')
    return value


def backend_name(account_id: str, team_id: str) -> str:
    _check_identifier(team_id, 'team_id', 16)
    if not isinstance(account_id, str) or len(account_id) != 12 or not account_id.isascii() or not account_id.isdigit():
        raise ValueError('account_id must be 12 ASCII digits')
    name = f'sumup--tfstate--{account_id}--{team_id}'
    validate_bucket_name(name)
    return name


def validate_registration(team_id: str) -> dict:
    """Single platform-owned source for bootstrap bindings and deployment identity."""
    _check_identifier(team_id, 'team_id', 16)
    binding = read_json(ROOT / 'config/teams' / f'{team_id}.json')
    if not {'repository', 'environments'} <= binding.keys() or binding.keys() - {'repository', 'environments', 'retained_backends'}:
        raise ValueError('registration requires repository/environments and optional retained_backends only')
    if not isinstance(binding['repository'], str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', binding['repository']):
        raise ValueError('registration repository must be owner/name')
    if not isinstance(binding['environments'], dict):
        raise ValueError('registration environments must be a map')
    retained = binding.get('retained_backends', [])
    if not isinstance(retained, list) or (not binding['environments'] and not retained):
        raise ValueError('registration requires active environments or explicitly retained backends')
    seen = set()
    for backend in retained:
        if not isinstance(backend, dict) or set(backend) != {'account_id', 'region'}:
            raise ValueError('retained backend requires account_id and region only')
        account = backend['account_id']
        derive_context(team_id, {**backend, 'environment': 'retained',
            'state_bucket': backend_name(account, team_id),
            'trusted_principal_arn': f'arn:aws:iam::{account}:role/validation-only'})
        if account in seen:
            raise ValueError('duplicate retained backend account')
        seen.add(account)
    for environment, entry in binding['environments'].items():
        catalog = environment_config(environment)
        if not isinstance(entry, dict) or set(entry) != {'trusted_principal_arn', 'oidc_subject'}:
            raise ValueError('registered environment requires trusted_principal_arn and oidc_subject only')
        subject = entry['oidc_subject']
        if (not isinstance(subject, str) or not subject.startswith(f"repo:{binding['repository']}:")
            or not re.search(rf':environment:{re.escape(environment)}(?::|$)', subject)
            or '*' in subject or '?' in subject or '\n' in subject or '\r' in subject):
            raise ValueError('OIDC subject must exactly bind the registered repository and environment')
        derive_context(team_id, {'account_id': catalog['account_id'], 'region': catalog['region'],
            'environment': environment, 'state_bucket': backend_name(catalog['account_id'], team_id),
            'trusted_principal_arn': entry['trusted_principal_arn']})
    return binding


def load_environment(directory: Path, team_id: str, *, deployment: bool = False,
                     repository: str | None = None) -> tuple[dict, dict]:
    """Require agreement between the directory, JSON, catalog and deployment binding."""
    if directory.is_symlink() or directory.parent.is_symlink() or not directory.is_dir():
        raise ValueError("environment must be a regular, non-symlink directory")
    environment = directory.name
    catalog = environment_config(environment)
    value = read_json(directory / 'resources.json')
    schema = json.loads((ROOT / 'schemas/consumer.schema.json').read_text())
    try:
        jsonschema.Draft7Validator(schema).validate(value)
    except jsonschema.ValidationError as exc:
        raise ValueError(f'{directory}: {exc.message}') from exc
    if type(value['schema_version']) is not int or value['schema_version'] != 2:
        raise ValueError('schema_version must be integer 2')
    if value['environment'] != environment:
        raise ValueError('JSON environment must match its environment directory')
    declaration = validate_declaration({k: (1 if k == 'schema_version' else v)
                                       for k, v in value.items() if k != 'environment'})
    account = catalog['account_id']
    principal = f'arn:aws:iam::{account}:role/fixture-source'
    execution_role = None
    if deployment:
        if not catalog['deployment_enabled'] or account == '000000000000':
            raise ValueError(f'{environment}: AWS deployment is not enabled by the platform')
        binding = validate_registration(team_id)
        if binding['repository'] != repository:
            raise ValueError('caller repository does not match the platform team registration')
        entry = binding['environments'].get(environment)
        if entry is None:
            raise ValueError('team/environment is not registered')
        principal = entry['trusted_principal_arn']
        execution_role = f'arn:aws:iam::{account}:role/sumup-ci--{environment}--{team_id}'
    context = derive_context(team_id, {'account_id': account, 'region': catalog['region'],
        'environment': environment, 'state_bucket': backend_name(account, team_id),
        'trusted_principal_arn': principal})
    context['dynamodb_table'] = context['state_bucket']
    if execution_role:
        context['execution_role_arn'] = execution_role
        context['permissions_boundary_arn'] = f'arn:aws:iam::{account}:policy/sumup-boundary--{environment}--{team_id}'
    return declaration, context


def consumer_environments(directory: Path) -> list[Path]:
    base = directory / 'environments'
    if base.is_symlink() or not base.is_dir():
        raise ValueError('consumer requires an environments/ directory')
    paths = sorted(base.iterdir())
    if not paths:
        raise ValueError('consumer must declare at least one environment')
    for path in paths:
        if path.is_symlink() or not path.is_dir():
            raise ValueError(f'{path}: environment must be a regular directory')
        environment_config(path.name)
    return paths
