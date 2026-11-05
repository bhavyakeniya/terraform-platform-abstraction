"""Render privileged backend/CI bootstrap inputs from the platform registry, without AWS calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.environments import ROOT, environment_config, read_json, validate_registration


def render_bootstrap(account_id: str, out: Path) -> dict:
    regions = set()
    teams = set()
    bindings = {}
    for path in sorted((ROOT / 'config/teams').glob('*.json')):
        registration = validate_registration(path.stem)
        for retained in registration.get('retained_backends', []):
            if retained['account_id'] == account_id:
                teams.add(path.stem)
                regions.add(retained['region'])
        for environment, identity in registration['environments'].items():
            config = environment_config(environment)
            if config['account_id'] != account_id:
                continue
            if account_id == '000000000000':
                raise ValueError('cannot bootstrap the fixture account in AWS')
            regions.add(config['region'])
            teams.add(path.stem)
            bindings[f'{path.stem}--{environment}'] = {
                'team_id': path.stem, 'environment': environment,
                'oidc_subject': identity['oidc_subject'],
            }
    if account_id == '000000000000':
        raise ValueError('cannot bootstrap the fixture account in AWS')
    if not teams or len(regions) != 1:
        raise ValueError('account requires registered teams and exactly one backend region')
    result = {'account_id': account_id, 'region': regions.pop(),
              'team_ids': sorted(teams), 'ci_bindings': bindings}
    out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    out.write_text(json.dumps(result, indent=2) + '\n')
    out.chmod(0o600)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account-id', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        value = render_bootstrap(args.account_id, args.out)
    except (ValueError, OSError) as exc:
        parser.exit(1, f'bootstrap rendering failed: {exc}\n')
    print(f'{len(value["team_ids"])} team backends, {len(value["ci_bindings"])} CI bindings rendered; no AWS calls')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
