"""Run independent, pinned, offline Terraform security checks. No AWS calls."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def scanner_environment() -> dict[str, str]:
    # No AWS/GitHub/Prisma credentials, scanner skip overrides, user CLI options,
    # or network proxy settings reach the scanners.
    keep = ('PATH', 'HOME', 'TMPDIR', 'TMP', 'TEMP', 'SYSTEMROOT', 'LANG', 'LC_ALL',
            'SSL_CERT_FILE', 'SSL_CERT_DIR')
    env = {key: os.environ[key] for key in keep if key in os.environ}
    env.update(CHECKOV_SKIP_MAPPING='true', PYTHONDONTWRITEBYTECODE='1', AWS_EC2_METADATA_DISABLED='true')
    return env


def invoke(args: list[str], env: dict, *, cwd: Path) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=180)
    except FileNotFoundError as exc:
        raise ValueError(f'{args[0]} is missing; install the pinned version in config/security-tools.json (docs/security-scanning.md)') from exc


def scanner_workspace(root: Path, destination: Path) -> None:
    """Scan every production TF file, with fixture inputs for the two real roots.

    A separate snapshot avoids reading local states/caches or writing synthetic
    auto.tfvars into a user's working deployment root. Original files stay untouched.
    """
    for section in ('modules', 'stacks'):
        for path in (root / section).rglob('*.tf'):
            relative = path.relative_to(root)
            if any(part.startswith('.') for part in relative.parts):
                continue
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    target = destination / 'examples/security'
    target.mkdir(parents=True)
    shutil.copy2(root / 'examples/security/main.tf', target / 'main.tf')
    # Use the same contract/renderer as team checks, always with the synthetic
    # context. No account credentials, init, plan, state or API requests are used.
    from scripts.team_platform import derive_context, load_declaration, render_inputs
    config = json.loads((ROOT / 'config/fixture.json').read_text())
    context = derive_context('security', config)
    context['permissions_boundary_arn'] = 'arn:aws:iam::000000000000:policy/sumup-boundary--test--security'
    # Real workload root is tested private-only; the dedicated public caller
    # exercises the public branch without waiving checks on the real root.
    declaration = load_declaration(ROOT / 'examples/minimal/resources.json')
    inputs, _ = render_inputs(declaration, context, destination / 'stacks/team')
    workload = json.loads(inputs.read_text())
    inputs.unlink()
    bootstrap = {'account_id': '000000000000', 'region': 'eu-central-1', 'team_ids': ['security'],
                 'ci_bindings': {'security--test': {'team_id': 'security', 'environment': 'test',
                     'oidc_subject': 'repo:example/security:environment:test'}}}
    for stack, values in [('team', workload), ('backends', bootstrap)]:
        # JSON values are valid HCL expressions; .tfvars is supported consistently
        # by both source parsers, including Terraform object/map inputs.
        (destination / 'stacks' / stack / 'terraform.tfvars').write_text(
            '\n'.join(f'{key} = {json.dumps(value)}' for key, value in values.items()) + '\n')


def scan(root: Path, output: Path) -> dict:
    root, output = root.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    versions = json.loads((root / 'config/security-tools.json').read_text())
    env = scanner_environment()
    commands = {"trivy": "trivy", "checkov": str(ROOT / "tools/security/.venv/bin/checkov")}
    for name in ('trivy', 'checkov'):
        result = invoke([commands[name], '--version'], env, cwd=root)
        match = re.search(r'(?:Version: )?(\d+\.\d+\.\d+)', result.stdout)
        if result.returncode or not match or match[1] != versions[f'{name}_version']:
            raise ValueError(f'{name} must be version {versions[f"{name}_version"]}; see docs/security-scanning.md')
    # One fresh workspace provides source snapshots and a pristine rule cache.
    # This includes the actual roots, not only the example composition.
    with tempfile.TemporaryDirectory(prefix='security-workspace-', dir=output) as temporary:
        workspace = Path(temporary)
        source = workspace / 'source'
        empty_credentials = workspace / 'empty-aws-config'
        empty_credentials.touch()
        env.update(AWS_CONFIG_FILE=str(empty_credentials), AWS_SHARED_CREDENTIALS_FILE=str(empty_credentials))
        scanner_workspace(root, source)
        trivy = invoke(['trivy', '--config', str(root / 'config/trivy.yaml'), 'config',
            '--disable-telemetry', '--skip-version-check', '--skip-check-update', '--cache-dir', str(workspace / 'cache'),
            '--ignorefile', str(root / 'config/trivy.ignore'), '--misconfig-scanners', 'terraform',
            '--include-non-failures', '--exit-code', '1', '--format', 'json',
            '--output', str(output / 'trivy.json'), str(source)], env, cwd=root)
        checkov = invoke([commands['checkov'], '--config-file', str(root / 'config/checkov.yaml'),
            '-d', str(source), '--framework', 'terraform',
            '--download-external-modules', 'false', '--skip-download', '--skip-results-upload',
            '--quiet', '--compact', '-o', 'json'], env, cwd=root)
    (output / 'checkov.json').write_text(checkov.stdout)
    (output / 'trivy.log').write_text(trivy.stderr)
    (output / 'checkov.log').write_text(checkov.stderr)
    try:
        trivy_data = json.loads((output / 'trivy.json').read_text())
        checkov_data = json.loads(checkov.stdout)
    except (ValueError, OSError) as exc:
        raise ValueError(f'scanner produced no valid report; inspect {output}') from exc
    results = trivy_data.get('Results', [])
    expected_roots = {'stacks/team', 'stacks/backends', 'examples/security'}
    if not expected_roots <= {r.get('Target') for r in results}:
        raise ValueError('security scan omitted a required deployed root or concrete fixture')
    findings = [(r.get('Target'), m['ID'], m.get('Status')) for r in results
                for m in r.get('Misconfigurations', []) if m.get('Status') == 'FAIL']
    evaluated = sum(sum(r.get('MisconfSummary', {}).values()) for r in results)
    summary = checkov_data.get('summary', {})
    if not evaluated or not summary.get('resource_count') or summary.get('parsing_errors'):
        raise ValueError('security scan had no evaluated resources or had parsing errors; refusing an empty green result')
    report = {'versions': versions, 'trivy_evaluated': evaluated, 'trivy_failures': findings,
              'checkov': summary, 'status': 'PASS' if trivy.returncode == checkov.returncode == 0 and not findings and not summary.get('failed') else 'FAIL'}
    (output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    for target, rule, _ in findings:
        print(f'Trivy: {rule} at {target}')
    for finding in checkov_data.get('results', {}).get('failed_checks', []):
        print(f"Checkov: {finding['check_id']} at {finding['resource']}")
    print(f"Security {report['status']}: Trivy evaluated {evaluated}; Checkov {summary.get('passed', 0)} passed, {summary.get('failed', 0)} failed, {summary.get('skipped', 0)} documented skips. Reports: {output}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT, help='Repository root; override only for temporary regression fixtures')
    parser.add_argument('--output', type=Path, default=ROOT / '.runs/security')
    args = parser.parse_args()
    try:
        return 0 if scan(args.root, args.output)['status'] == 'PASS' else 1
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f'security scan failed: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
