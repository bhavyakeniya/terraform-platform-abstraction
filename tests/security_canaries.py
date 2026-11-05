"""Real offline scanner canaries. Run explicitly with make test-security."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest
from scripts import security_check
ROOT = security_check.ROOT


def scanner_copy(tmp_path):
    for directory in ['config', 'modules', 'stacks', 'examples/security']:
        shutil.copytree(ROOT / directory, tmp_path / directory,
                        ignore=shutil.ignore_patterns('.terraform', 'tests', '*.tfstate*', '*.tfplan'))
    return tmp_path


@pytest.mark.parametrize('mutation', ['private_public_access', 'administrator_policy'])
def test_real_scanners_reject_new_misconfigurations(tmp_path, mutation):
    root = scanner_copy(tmp_path / 'source')
    if mutation == 'private_public_access':
        path = root / 'modules/team-resources/buckets.tf'
        text = path.read_text()
        text = re.sub(r'restrict_public_buckets\s*=\s*var\.buckets\[each.key\]\.visibility == "public" \? false : true',
                      'restrict_public_buckets = false', text)
        path.write_text(text)
    else:
        with (root / 'stacks/team/main.tf').open('a') as stream:
            stream.write('''
resource "aws_iam_policy" "scanner_canary" {
  name = "synthetic-do-not-deploy"
  policy = jsonencode({Version="2012-10-17", Statement=[{
    Effect="Allow", Action="*", Resource="*"
  }]})
}
''')
    output = tmp_path / 'reports'
    command = subprocess.run([sys.executable, '-m', 'scripts.security_check', '--root', str(root),
                              '--output', str(output)], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert command.returncode == 1, command.stdout + command.stderr
    result = json.loads((output / 'summary.json').read_text())
    assert result['status'] == 'FAIL'
    assert result['checkov']['failed'] > 0, 'Checkov must reject both canaries'
    if mutation == 'private_public_access':
        assert result['trivy_failures'], 'Trivy must independently reject unsafe private access'
    # Trivy 0.73 embedded rules do not flag this standalone administrator IAM
    # policy; Checkov's independent IAM rules are the required blocking layer.
    if mutation == 'private_public_access':
        report = json.loads((output / 'trivy.json').read_text())
        assert any(m['ID'] == 'AWS-0093' and m['CauseMetadata']['Resource'] == 'module.private'
                   for r in report['Results'] for m in r.get('Misconfigurations', [])), 'public-fixture waiver must never hide unsafe private access'
