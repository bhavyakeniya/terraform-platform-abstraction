"""Platform-owned preparation and fresh saved-plan deployment. Never executes team code."""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
import subprocess

from scripts.consumer_platform import load_consumer
from scripts.environments import ROOT, load_environment
from scripts.team_platform import _check_identifier, _terraform_bin, render_inputs


def prepare(consumer: Path, team: str, environment: str, repository: str, out: Path) -> dict:
    _check_identifier(environment, 'environment', 8)
    directory = consumer / 'environments' / environment
    declaration, context = load_environment(directory, team, deployment=True, repository=repository)
    load_consumer(directory, team)  # Includes the team's business regression contract.
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    render_inputs(declaration, context, out)
    (out / 'context.json').write_text(json.dumps(context, indent=2) + '\n')
    return context


def plan_summary(plan: dict) -> tuple[str, bool]:
    rows = []
    destructive = False
    for resource in plan.get('resource_changes', []):
        if resource.get('mode') != 'managed':
            continue
        actions = resource['change']['actions']
        if actions == ['no-op']:
            continue
        destructive |= 'delete' in actions
        rows.append(f"- `{resource['address']}`: {', '.join(actions)}")
    return '\n'.join(rows) if rows else 'No infrastructure changes.', destructive


def execute_deployment(out: Path, mode: str, *, allow_destroy: bool = False) -> None:
    if mode not in {'plan', 'apply'}:
        raise ValueError('mode must be plan or apply')
    # This command is deliberately a CI entry point, not an unguarded local apply shortcut.
    if os.environ.get('GITHUB_REF') != f"refs/heads/{os.environ.get('DEFAULT_BRANCH', '')}" or not os.environ.get('DEFAULT_BRANCH'):
        raise ValueError('AWS runs require the consumer default branch')
    if mode == 'apply' and os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch':
        raise ValueError('apply requires a manual workflow dispatch')
    out = out.resolve()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('TF_CLI_ARGS', 'TF_VAR_', 'TF_LOG', 'AWS_ENDPOINT_URL'))
           and k != 'TF_CLI_CONFIG_FILE'}
    env.update(TF_DATA_DIR=str(out / 'terraform-data'), TF_IN_AUTOMATION='true', TF_INPUT='false', TF_WORKSPACE='default')
    binary = str(Path(_terraform_bin()).resolve()) if '/' in _terraform_bin() else _terraform_bin()

    def tf(*args: str, accepted: tuple[int, ...] = (0,)) -> str:
        result = subprocess.run([binary, f'-chdir={ROOT / "stacks/team"}', *args],
                                env=env, capture_output=True, text=True, timeout=900)
        # Raw plans/state/provider diagnostics may contain sensitive values. Keep
        # them on this ephemeral runner, never in public logs or artifacts.
        if result.returncode not in accepted:
            log = out / 'terraform-error.log'
            log.write_text(result.stdout + result.stderr)
            log.chmod(0o600)
            raise ValueError(f'Terraform {args[0]} failed (exit {result.returncode}); private runner diagnostic: {log.name}')
        return result.stdout

    tf('init', '-input=false', '-lockfile=readonly', f'-backend-config={out / "backend.hcl.json"}')
    tf('validate')
    plan_file = out / 'deployment.tfplan'
    tf('plan', '-input=false', '-lock-timeout=60s', f'-var-file={out / "inputs.tfvars.json"}', f'-out={plan_file}')
    summary, destructive = plan_summary(json.loads(tf('show', '-json', str(plan_file))))
    context = json.loads((out / 'context.json').read_text())
    summary = f"### {context['team_id']} / {context['environment']} — {mode}\n\n{summary}\n"
    if mode == 'apply':
        if destructive and not allow_destroy:
            raise ValueError('plan deletes or replaces resources; inspect a plan-only run, then explicitly allow destruction in a new dispatch')
        tf('apply', '-input=false', '-lock-timeout=60s', str(plan_file))
        summary += '\nApplied the exact saved plan created in this job.\n'
    (out / 'summary.md').write_text(summary)
    if target := os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(target, 'a') as stream:
            stream.write(summary)
    print(summary)


def archive_recovery(out: Path) -> None:
    """Best-effort private escrow of Terraform's emergency state after a failed write.

    Called only after refreshed CI credentials. Failure remains fatal and requires
    inventory reconciliation; a missing emergency file performs no AWS request.
    """
    emergency = ROOT / 'stacks/team/errored.tfstate'
    if not emergency.is_file():
        print('No emergency state file was produced.')
        return
    if emergency.is_symlink():
        raise ValueError('refusing a symlink emergency state file')
    context = json.loads((out / 'context.json').read_text())
    run_id = os.environ.get('GITHUB_RUN_ID', '')
    attempt = os.environ.get('GITHUB_RUN_ATTEMPT', '')
    if not re.fullmatch(r'[0-9]+', run_id) or not re.fullmatch(r'[0-9]+', attempt):
        raise ValueError('private recovery requires a valid GitHub run ID and attempt')
    key = f"recovery/{context['environment']}/{run_id}/{attempt}/errored.tfstate"
    env = {k: v for k, v in os.environ.items() if not k.startswith('AWS_ENDPOINT_URL')}
    result = subprocess.run(['aws', '--region', context['region'], '--no-cli-pager', '--output', 'json',
        '--cli-connect-timeout', '10', '--cli-read-timeout', '60', 's3api', 'put-object',
        '--bucket', context['state_bucket'], '--key', key, '--body', str(emergency),
        '--server-side-encryption', 'AES256'], env=env, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise ValueError('PRIVATE RECOVERY UPLOAD FAILED; stop writers and reconcile AWS inventory/state before retrying')
    response = json.loads(result.stdout)
    if not response.get('VersionId') or response.get('ServerSideEncryption') != 'AES256':
        raise ValueError('private recovery upload did not confirm a versioned encrypted object')
    print(f"Emergency state preserved privately: s3://{context['state_bucket']}/{key} (version {response['VersionId']})")
    emergency.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'run', 'recover'])
    parser.add_argument('--consumer-dir', type=Path)
    parser.add_argument('--team-id')
    parser.add_argument('--environment')
    parser.add_argument('--repository')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--mode', choices=['plan', 'apply'], default='plan')
    parser.add_argument('--allow-destroy', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            if not all((args.consumer_dir, args.team_id, args.environment, args.repository)):
                raise ValueError('prepare requires consumer-dir, team-id, environment and repository')
            context = prepare(args.consumer_dir.resolve(), args.team_id, args.environment, args.repository, args.out.resolve())
            if path := os.environ.get('GITHUB_OUTPUT'):
                with open(path, 'a') as stream:
                    stream.write(f"role={context['execution_role_arn']}\nregion={context['region']}\n")
        elif args.command == 'recover':
            archive_recovery(args.out)
        else:
            execute_deployment(args.out, args.mode, allow_destroy=args.allow_destroy)
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f'deployment failed: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
