"""Security-gate wiring and real scanner regression canaries (make test-security)."""
import re

import pytest
import yaml

from scripts import security_check

ROOT = security_check.ROOT


def test_deployed_roots_pin_runtime_minor_and_provider_major():
    for stack in ['team', 'backends']:
        text = (ROOT / 'stacks' / stack / 'versions.tf').read_text()
        assert 'required_version = "~> 1.17.0"' in text
        assert 'version = "~> 6.0"' in re.sub(r' +', ' ', text)
    # Reusable module compatibility is deliberately broader than deployed roots.
    for module in ['team-resources', 'team-backend', 'team-ci']:
        text = (ROOT / 'modules' / module / 'versions.tf').read_text()
        assert '">= 5.0, < 7.0"' in text


def test_scanners_do_not_receive_cloud_credentials_or_skip_overrides(monkeypatch):
    for name in ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'GITHUB_TOKEN',
                 'BC_API_KEY', 'PRISMA_API_URL', 'TRIVY_SKIP_DIRS', 'CKV_SKIP_CHECK']:
        monkeypatch.setenv(name, 'synthetic-do-not-forward')
    env = security_check.scanner_environment()
    assert not any('synthetic-do-not-forward' == value for value in env.values())
    assert env['CHECKOV_SKIP_MAPPING'] == 'true'


def test_both_ci_paths_gate_on_the_shared_security_action():
    main = yaml.load((ROOT / '.github/workflows/terraform.yml').read_text(), Loader=yaml.BaseLoader)
    assert main['jobs']['checks']['needs'] == 'security'
    assert any(s.get('uses') == './.github/actions/security-checks' for s in main['jobs']['security']['steps'])
    team = yaml.load((ROOT / '.github/workflows/team-infrastructure.yml').read_text(), Loader=yaml.BaseLoader)
    assert team['jobs']['deploy']['needs'] == 'check'
    assert any(s.get('uses') == './platform/.github/actions/security-checks' for s in team['jobs']['check']['steps'])
    action = (ROOT / '.github/actions/security-checks/action.yml').read_text()
    assert 'sha256sum --check --strict' in action
    assert 'make security test-security' in action
    assert 'continue-on-error' not in action


def test_security_configs_do_not_globally_skip_checks():
    for name in ['trivy', 'checkov']:
        config = yaml.safe_load((ROOT / f'config/{name}.yaml').read_text())
        assert not {'skip-check', 'soft-fail', 'skip-path', 'severity'} & config.keys()
    assert all(not line.strip() or line.lstrip().startswith('#')
               for line in (ROOT / 'config/trivy.ignore').read_text().splitlines())


def test_missing_scanner_is_a_failure(tmp_path, monkeypatch):
    monkeypatch.setenv('PATH', str(tmp_path))
    with pytest.raises(ValueError, match='missing'):
        security_check.scan(ROOT, tmp_path / 'results')

