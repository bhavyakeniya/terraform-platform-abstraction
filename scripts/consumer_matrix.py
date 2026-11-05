"""Select environment jobs from a consumer checkout; removed configs fail closed."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from scripts.environments import consumer_environments, read_json
from scripts.team_platform import _check_identifier


def select_environments(directory: Path, *, selected: str = '', changed: list[str] | None = None) -> list[str]:
    identity = read_json(directory / 'team.json')
    if set(identity) != {'team_id'}:
        raise ValueError('team.json must contain only team_id')
    _check_identifier(identity['team_id'], 'team_id', 16)
    available = [p.name for p in consumer_environments(directory)]
    if selected:
        if selected not in available:
            raise ValueError('selected environment is not configured by this team')
        return [selected]
    if changed is None:
        return available
    touched = set()
    shared = False
    for path in changed:
        parts = path.split('/')
        if len(parts) >= 2 and parts[0] == 'environments':
            if parts[1] not in available:
                receipt = read_json(directory / 'retired-environments' / f'{parts[1]}.json')
                if (set(receipt) != {'team_id', 'environment', 'completed', 'ticket', 'approved_by'}
                    or receipt['team_id'] != identity['team_id'] or receipt['environment'] != parts[1]
                    or receipt['completed'] is not True or not isinstance(receipt['ticket'], str)
                    or not receipt['ticket'].strip() or not isinstance(receipt['approved_by'], str)
                    or not receipt['approved_by'].strip()):
                    raise ValueError('environment removal requires a completed retirement receipt with approval and ticket')
                continue
            touched.add(parts[1])
        elif path == 'team.json' or path.startswith(('.github/', 'Makefile')):
            shared = True
    return available if shared else sorted(touched)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--consumer-dir', type=Path, required=True)
    parser.add_argument('--environment', default='')
    parser.add_argument('--base', default='')
    args = parser.parse_args()
    try:
        changed = None
        if args.base and set(args.base) != {'0'}:
            if not re.fullmatch('[0-9a-f]{40}', args.base):
                raise ValueError('base must be a full Git commit SHA')
            result = subprocess.run(['git', 'diff', '--name-only', '--no-renames', '-z', args.base, 'HEAD'],
                                    cwd=args.consumer_dir, capture_output=True, timeout=60)
            if result.returncode:
                raise ValueError('cannot discover changed environments from the base commit')
            changed = [p.decode('utf-8') for p in result.stdout.split(b'\0') if p]
        environments = select_environments(args.consumer_dir, selected=args.environment, changed=changed)
        identity = read_json(args.consumer_dir / 'team.json')
        result = json.dumps(environments)
        if target := os.environ.get('GITHUB_OUTPUT'):
            with open(target, 'a') as stream:
                stream.write(f'environments={result}\nhas_changes={str(bool(environments)).lower()}\nteam={identity["team_id"]}\n')
        print(result)
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f'environment discovery failed: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
