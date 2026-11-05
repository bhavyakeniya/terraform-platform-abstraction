"""Multi-environment onboarding, backend boundaries and deployment safety."""
import copy
import json
from pathlib import Path
import subprocess

import pytest
import yaml

from scripts import deploy, environments
from scripts.consumer_matrix import select_environments
from scripts.consumer_platform import check_consumer, load_consumer
from scripts.onboard import onboard
from scripts.team_platform import render_inputs

ROOT = environments.ROOT


@pytest.fixture
def consumer(tmp_path):
    target = tmp_path / 'payments'
    onboard(target, 'payments', 'payments@example.invalid', ['dev', 'staging', 'prod'])
    return target


def test_onboarding_defaults_are_immediately_checkable_and_do_not_publish(consumer):
    assert select_environments(consumer) == ['dev', 'prod', 'staging']
    assert (consumer / '.github/workflows/infrastructure.yml.template').is_file()
    assert not (consumer / '.git').exists()
    for directory in environments.consumer_environments(consumer):
        declaration, context = load_consumer(directory, 'payments')
        assert declaration['buckets'] == {'data': {'visibility': 'private'}}
        assert context['environment'] == directory.name
        assert context['state_bucket'] == 'sumup--tfstate--000000000000--payments'
        assert context['dynamodb_table'] == context['state_bucket']


def test_live_workflow_is_rendered_with_one_immutable_platform_pin(tmp_path):
    target = tmp_path / 'new-team'
    onboard(target, 'new-team', 'owner@example.invalid', ['dev'],
            platform_repository='example/platform', platform_ref='a' * 40)
    text = (target / '.github/workflows/infrastructure.yml').read_text()
    assert 'uses: example/platform/.github/workflows/team-infrastructure.yml@' + 'a' * 40 in text
    assert 'PLATFORM_' not in text
    with pytest.raises(ValueError, match='overwrite'):
        onboard(target, 'new-team', 'owner@example.invalid', ['dev'])


@pytest.mark.parametrize('ref', ['main', 'v1', 'x' * 40, 'a' * 39])
def test_onboarding_rejects_mutable_or_invalid_references(tmp_path, ref):
    with pytest.raises(ValueError, match='immutable'):
        onboard(tmp_path / 'out', 'payments', 'owner@example.invalid', ['dev'],
                platform_repository='example/platform', platform_ref=ref)
    assert not (tmp_path / 'out').exists()


def test_environment_and_team_backend_isolation(consumer, tmp_path):
    contexts = [load_consumer(p, 'payments')[1] for p in environments.consumer_environments(consumer)]
    assert len({c['state_key'] for c in contexts}) == 3
    assert len({c['state_bucket'] for c in contexts}) == 1
    assert environments.backend_name('123456789012', 'customers') != environments.backend_name('123456789012', 'payments')
    assert environments.backend_name('123456789012', 'payments') != environments.backend_name('234567890123', 'payments')
    declaration, context = load_consumer(consumer / 'environments/dev', 'payments')
    _, backend_path = render_inputs(declaration, context, tmp_path / 'render')
    backend = json.loads(backend_path.read_text())
    assert backend['encrypt'] is True
    assert backend['dynamodb_table'] == context['state_bucket']
    assert 'use_lockfile' not in backend
    assert backend['allowed_account_ids'] == ['000000000000']


@pytest.mark.parametrize('update', [
    {'environment': 'prod'}, {'environment': 'dev\n'}, {'schema_version': True},
    {'schema_version': 1}, {'schema_version': 2.0}, {'region': 'eu-west-1'},
    {'buckets': {'data': {}}}, {'buckets': {'data': {'visibility': 'PUBLIC'}}},
])
def test_rejects_mismatches_overrides_and_missing_visibility(consumer, update):
    file = consumer / 'environments/dev/resources.json'
    value = json.loads(file.read_text())
    value.update(update)
    file.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        load_consumer(file.parent, 'payments')


def test_rejects_duplicate_json_keys(consumer):
    path = consumer / 'environments/dev/resources.json'
    path.write_text(path.read_text().replace('"environment": "dev"', '"environment": "dev", "environment": "dev"'))
    with pytest.raises(ValueError, match='duplicate'):
        load_consumer(path.parent, 'payments')


def test_unknown_environment_fails_and_new_catalog_entry_works(consumer, monkeypatch, tmp_path):
    catalog = tmp_path / 'catalog'
    (catalog / 'config/environments').mkdir(parents=True)
    (catalog / 'schemas').mkdir()
    (catalog / 'schemas/consumer.schema.json').write_bytes((ROOT / 'schemas/consumer.schema.json').read_bytes())
    monkeypatch.setattr(environments, 'ROOT', catalog)
    with pytest.raises(ValueError):
        load_consumer(consumer / 'environments/dev', 'payments')
    (catalog / 'config/environments/dev.json').write_bytes((ROOT / 'config/environments/dev.json').read_bytes())
    assert load_consumer(consumer / 'environments/dev', 'payments')[1]['environment'] == 'dev'


def test_selected_changes_do_not_apply_unrelated_environments(consumer):
    assert select_environments(consumer, changed=['environments/dev/resources.json']) == ['dev']
    assert select_environments(consumer, changed=['README.md']) == []
    assert len(select_environments(consumer, changed=['.github/workflows/infrastructure.yml'])) == 3
    assert select_environments(consumer, selected='prod') == ['prod']
    with pytest.raises(ValueError):
        select_environments(consumer, selected='unknown')


def test_environment_removal_requires_a_retirement_receipt(consumer):
    with pytest.raises(ValueError):
        select_environments(consumer, changed=['environments/old/resources.json'])
    target = consumer / 'retired-environments'
    target.mkdir()
    (target / 'old.json').write_text(json.dumps({'team_id': 'payments', 'environment': 'old',
        'completed': True, 'ticket': 'CHG-1', 'approved_by': 'platform-owner'}))
    assert select_environments(consumer, changed=['environments/old/resources.json']) == []


def test_deployment_fails_closed_before_aws_is_available(consumer, tmp_path):
    with pytest.raises(ValueError, match='not enabled'):
        deploy.prepare(consumer, 'payments', 'dev', 'example/payments', tmp_path / 'deploy')
    assert not (tmp_path / 'deploy').exists()


def test_registration_binds_caller_team_environment_and_boundary(consumer, monkeypatch, tmp_path):
    catalog = tmp_path / 'catalog'
    (catalog / 'config/environments').mkdir(parents=True)
    (catalog / 'config/teams').mkdir()
    (catalog / 'schemas').mkdir()
    (catalog / 'schemas/consumer.schema.json').write_bytes((ROOT / 'schemas/consumer.schema.json').read_bytes())
    (catalog / 'config/environments/dev.json').write_text(json.dumps({
        'account_id': '123456789012', 'region': 'eu-central-1', 'deployment_enabled': True}))
    registration = {'repository': 'example/payments', 'environments': {'dev': {
        'oidc_subject': 'repo:example/payments:environment:dev',
        'trusted_principal_arn': 'arn:aws:iam::123456789012:role/payments-app'}}}
    path = catalog / 'config/teams/payments.json'
    path.write_text(json.dumps(registration))
    monkeypatch.setattr(environments, 'ROOT', catalog)
    with pytest.raises(ValueError, match='caller repository'):
        deploy.prepare(consumer, 'payments', 'dev', 'example/customers', tmp_path / 'invalid')
    context = deploy.prepare(consumer, 'payments', 'dev', 'example/payments', tmp_path / 'valid')
    assert context['permissions_boundary_arn'] == 'arn:aws:iam::123456789012:policy/sumup-boundary--dev--payments'
    values = json.loads((tmp_path / 'valid/inputs.tfvars.json').read_text())
    assert values['permissions_boundary_arn'] == context['permissions_boundary_arn']


def test_apply_requires_manual_default_branch_dispatch(monkeypatch, tmp_path):
    monkeypatch.setenv('GITHUB_REF', 'refs/heads/feature')
    monkeypatch.setenv('DEFAULT_BRANCH', 'main')
    with pytest.raises(ValueError, match='default branch'):
        deploy.execute_deployment(tmp_path, 'apply')
    monkeypatch.setenv('GITHUB_REF', 'refs/heads/main')
    monkeypatch.setenv('GITHUB_EVENT_NAME', 'push')
    with pytest.raises(ValueError, match='manual'):
        deploy.execute_deployment(tmp_path, 'apply')


def test_summary_hides_values_and_flags_replacement():
    plan = {'resource_changes': [{'mode': 'managed', 'address': 'module.team.aws_s3_bucket.this["data"]',
        'change': {'actions': ['delete', 'create'], 'before': {'secret': 'never-print'}, 'after': {}}}]}
    summary, destructive = deploy.plan_summary(plan)
    assert destructive and 'delete, create' in summary and 'never-print' not in summary


def test_shared_workflow_keeps_credentials_away_from_prs_and_raw_plans_private():
    workflow = yaml.load((ROOT / '.github/workflows/team-infrastructure.yml').read_text(), Loader=yaml.BaseLoader)
    assert 'pull_request_target' not in workflow['on']
    assert 'id-token' not in workflow['permissions']
    assert 'configure-aws' not in json.dumps(workflow['jobs']['check'])
    deploy_job = workflow['jobs']['deploy']
    assert "github.event_name == 'push'" in deploy_job['if']
    assert "github.event_name == 'workflow_dispatch'" in deploy_job['if']
    assert 'default_branch' in deploy_job['if']
    assert deploy_job['concurrency']['cancel-in-progress'] == 'false'
    assert 'upload-artifact' not in json.dumps(deploy_job)
    localstack_job = workflow['jobs']['localstack']
    assert 'workflow_dispatch' in localstack_job['if'] and 'default_branch' in localstack_job['if']
    assert 'secrets.' not in json.dumps(workflow['jobs']['check'])
    assert deploy_job['environment'] == '${{ matrix.environment }}'


@pytest.mark.parametrize('mode,allow_destroy,actions,should_apply', [
    ('plan', False, ['create'], False),
    ('apply', False, ['create'], True),
    ('apply', False, ['delete', 'create'], False),
    ('apply', True, ['delete', 'create'], True),
])
def test_ci_initializes_readonly_and_applies_only_its_fresh_saved_plan(
    tmp_path, monkeypatch, mode, allow_destroy, actions, should_apply
):
    monkeypatch.setenv('GITHUB_REF', 'refs/heads/main')
    monkeypatch.setenv('DEFAULT_BRANCH', 'main')
    monkeypatch.setenv('GITHUB_EVENT_NAME', 'workflow_dispatch')
    monkeypatch.setenv('TF_CLI_ARGS_plan', '-lock=false')
    monkeypatch.setattr(deploy, '_terraform_bin', lambda: '/fake/terraform')
    calls = []
    (tmp_path / 'context.json').write_text(json.dumps({'team_id': 'payments', 'environment': 'dev'}))
    plan = {'resource_changes': [{'mode': 'managed', 'address': 'module.team.aws_s3_bucket.this["data"]',
                                 'change': {'actions': actions, 'after': {'private': 'secret-value'}}}]}
    def run(args, **kwargs):
        assert not any(k.startswith('TF_CLI_ARGS') for k in kwargs['env'])
        assert kwargs['env']['TF_DATA_DIR'] == str(tmp_path / 'terraform-data')
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, json.dumps(plan) if args[2] == 'show' else '', '')
    monkeypatch.setattr(deploy.subprocess, 'run', run)
    if mode == 'apply' and 'delete' in actions and not allow_destroy:
        with pytest.raises(ValueError, match='deletes or replaces'):
            deploy.execute_deployment(tmp_path, mode, allow_destroy=allow_destroy)
    else:
        deploy.execute_deployment(tmp_path, mode, allow_destroy=allow_destroy)
        assert 'secret-value' not in (tmp_path / 'summary.md').read_text()
    assert '-lockfile=readonly' in calls[0]
    plans = [c for c in calls if c[2] == 'plan']
    applies = [c for c in calls if c[2] == 'apply']
    assert len(plans) == 1
    assert bool(applies) == should_apply
    if should_apply:
        saved = next(a.split('=', 1)[1] for a in plans[0] if a.startswith('-out='))
        assert applies[0][-1] == saved


def test_symlink_environment_is_rejected(consumer, tmp_path):
    source = consumer / 'environments/dev'
    destination = tmp_path / 'outside'
    source.rename(destination)
    source.symlink_to(destination, target_is_directory=True)
    with pytest.raises(ValueError, match='non-symlink'):
        environments.load_environment(source, 'payments')


@pytest.mark.parametrize('team', ['team-s3alias', 'team-an'])
def test_backend_names_reject_reserved_suffixes(team):
    with pytest.raises(ValueError, match='reserved suffix'):
        environments.backend_name('123456789012', team)


def test_backend_region_must_be_consistent_within_one_account(tmp_path, monkeypatch):
    catalog = tmp_path / 'config/environments'
    catalog.mkdir(parents=True)
    for name, region in [('dev', 'eu-central-1'), ('prod', 'eu-west-1')]:
        (catalog / f'{name}.json').write_text(json.dumps({'account_id': '123456789012',
            'region': region, 'deployment_enabled': False}))
    monkeypatch.setattr(environments, 'ROOT', tmp_path)
    with pytest.raises(ValueError, match='consistent backend region'):
        environments.environment_config('dev')


def test_bootstrap_uses_one_registration_source_and_preserves_retired_backends(tmp_path, monkeypatch):
    from scripts import bootstrap_inputs
    registry = tmp_path / 'config/teams'
    registry.mkdir(parents=True)
    catalog = tmp_path / 'config/environments'
    catalog.mkdir()
    account = '123456789012'
    (catalog / 'dev.json').write_text(json.dumps({'account_id': account, 'region': 'eu-central-1', 'deployment_enabled': False}))
    (registry / 'payments.json').write_text(json.dumps({'repository': 'example/payments', 'environments': {'dev': {
        'trusted_principal_arn': f'arn:aws:iam::{account}:role/payments-app',
        'oidc_subject': 'repo:example/payments:environment:dev'}}}))
    (registry / 'retired.json').write_text(json.dumps({'repository': 'example/retired', 'environments': {},
        'retained_backends': [{'account_id': account, 'region': 'eu-central-1'}]}))
    monkeypatch.setattr(environments, 'ROOT', tmp_path)
    monkeypatch.setattr(bootstrap_inputs, 'ROOT', tmp_path)
    value = bootstrap_inputs.render_bootstrap(account, tmp_path / 'out.json')
    assert value['team_ids'] == ['payments', 'retired']
    assert list(value['ci_bindings']) == ['payments--dev']
    assert value['ci_bindings']['payments--dev']['oidc_subject'] == 'repo:example/payments:environment:dev'
    assert (tmp_path / 'out.json').stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('subject', [
    'repo:example/customers:environment:dev', 'repo:example/payments:environment:devx',
    'repo:example/*:environment:dev', 'repo:example/payments:ref:refs/heads/main',
])
def test_registry_rejects_the_wrong_oidc_repository_or_environment(tmp_path, monkeypatch, subject):
    (tmp_path / 'config/teams').mkdir(parents=True)
    (tmp_path / 'config/environments').mkdir()
    (tmp_path / 'config/environments/dev.json').write_bytes((ROOT / 'config/environments/dev.json').read_bytes())
    (tmp_path / 'config/teams/payments.json').write_text(json.dumps({'repository': 'example/payments',
        'environments': {'dev': {'trusted_principal_arn': 'arn:aws:iam::000000000000:role/fixture-source', 'oidc_subject': subject}}}))
    monkeypatch.setattr(environments, 'ROOT', tmp_path)
    with pytest.raises(ValueError, match='OIDC subject'):
        environments.validate_registration('payments')


@pytest.mark.parametrize('success', [True, False])
def test_emergency_state_stays_private_and_is_preserved_on_upload_failure(tmp_path, monkeypatch, success):
    root = tmp_path / 'platform'
    directory = root / 'stacks/team'
    directory.mkdir(parents=True)
    state = directory / 'errored.tfstate'
    state.write_text('{"private":"sensitive-state"}')
    out = tmp_path / 'out'
    out.mkdir()
    (out / 'context.json').write_text(json.dumps({'region': 'eu-central-1',
        'state_bucket': 'sumup--tfstate--123456789012--payments', 'environment': 'dev'}))
    monkeypatch.setattr(deploy, 'ROOT', root)
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '2')
    monkeypatch.setenv('AWS_ENDPOINT_URL', 'https://untrusted.invalid')
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        assert 'AWS_ENDPOINT_URL' not in kwargs['env']
        return subprocess.CompletedProcess(args, 0 if success else 1,
            json.dumps({'VersionId': 'synthetic-version', 'ServerSideEncryption': 'AES256'}), 'private-error')
    monkeypatch.setattr(deploy.subprocess, 'run', run)
    if success:
        deploy.archive_recovery(out)
        assert not state.exists()
    else:
        with pytest.raises(ValueError, match='RECOVERY UPLOAD FAILED'):
            deploy.archive_recovery(out)
        assert state.read_text() == '{"private":"sensitive-state"}'
    args = calls[0]
    assert args[args.index('--key') + 1] == 'recovery/dev/123/2/errored.tfstate'
    assert args[args.index('--server-side-encryption') + 1] == 'AES256'
    assert 'sensitive-state' not in ' '.join(args)


def test_missing_emergency_state_does_not_make_an_aws_request(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, 'ROOT', tmp_path)
    monkeypatch.setattr(deploy.subprocess, 'run', lambda *a, **kw: pytest.fail('unexpected AWS request'))
    deploy.archive_recovery(tmp_path)


def test_scaffold_rejects_a_team_that_would_make_a_reserved_backend_name(tmp_path):
    with pytest.raises(ValueError, match='reserved suffix'):
        onboard(tmp_path / 'invalid', 'team-an', 'owner@example.invalid', ['dev'])
    assert not (tmp_path / 'invalid').exists()


def test_three_hundred_teams_render_independent_backends_and_nine_hundred_ci_bindings(tmp_path, monkeypatch):
    from scripts import bootstrap_inputs
    registry = tmp_path / 'config/teams'
    registry.mkdir(parents=True)
    catalog = tmp_path / 'config/environments'
    catalog.mkdir()
    account = '123456789012'
    for environment in ['dev', 'staging', 'prod']:
        (catalog / f'{environment}.json').write_text(json.dumps({'account_id': account,
            'region': 'eu-central-1', 'deployment_enabled': False}))
    for number in range(300):
        team = f'team{number:03}'
        (registry / f'{team}.json').write_text(json.dumps({'repository': f'example/{team}', 'environments': {
            environment: {'trusted_principal_arn': f'arn:aws:iam::{account}:role/{team}-{environment}',
                          'oidc_subject': f'repo:example/{team}:environment:{environment}'}
            for environment in ['dev', 'staging', 'prod']}}))
    monkeypatch.setattr(environments, 'ROOT', tmp_path)
    monkeypatch.setattr(bootstrap_inputs, 'ROOT', tmp_path)
    value = bootstrap_inputs.render_bootstrap(account, tmp_path / 'out.json')
    assert len(value['team_ids']) == 300
    assert len({environments.backend_name(account, team) for team in value['team_ids']}) == 300
    assert len(value['ci_bindings']) == 900
    assert len({(b['team_id'], b['environment']) for b in value['ci_bindings'].values()}) == 900


def test_a_fourth_environment_needs_data_changes_only(tmp_path, monkeypatch):
    catalog = tmp_path / 'platform'
    (catalog / 'config/environments').mkdir(parents=True)
    (catalog / 'schemas').mkdir()
    (catalog / 'schemas/consumer.schema.json').write_bytes((ROOT / 'schemas/consumer.schema.json').read_bytes())
    (catalog / 'config/environments/qa.json').write_text(json.dumps({
        'account_id': '123456789012', 'region': 'eu-central-1', 'deployment_enabled': False}))
    monkeypatch.setattr(environments, 'ROOT', catalog)
    directory = tmp_path / 'consumer'
    onboard(directory, 'payments', 'owner@example.invalid', ['qa'])
    assert select_environments(directory) == ['qa']
    declaration, context = load_consumer(directory / 'environments/qa', 'payments')
    assert context['environment'] == 'qa'
    assert context['state_key'] == 'workloads/123456789012/qa/teams/payments/terraform.tfstate'


def test_ci_permissions_cover_the_pinned_provider_bucket_reads():
    # AWS API and IAM action names differ. This inventory comes from the pinned
    # provider's resourceBucketRead plus AWS's service authorization mapping;
    # it is deliberately independent of the Terraform policy expression.
    import fnmatch
    policy = json.loads((ROOT / 'modules/team-ci/tests/ci-policy.json').read_text())
    allowed = policy['Statement'][0]['Action']
    required = {
        's3:ListBucket', 's3:GetBucketLocation', 's3:GetBucketAcl', 's3:GetBucketPolicy',
        's3:GetBucketVersioning', 's3:GetBucketRequestPayment', 's3:GetBucketLogging',
        's3:GetBucketCORS', 's3:GetBucketWebsite', 's3:GetBucketObjectLockConfiguration',
        's3:GetBucketOwnershipControls', 's3:GetBucketPublicAccessBlock', 's3:GetBucketTagging',
        's3:GetEncryptionConfiguration', 's3:GetAccelerateConfiguration',
        's3:GetLifecycleConfiguration', 's3:GetReplicationConfiguration',
    }
    missing = {action for action in required if not any(fnmatch.fnmatchcase(action, pattern) for pattern in allowed)}
    assert not missing, f'pinned provider read permissions missing: {sorted(missing)}'
    assert 's3:DeleteBucketOwnershipControls' not in allowed
    assert 's3:DeleteBucketTagging' not in allowed
