"""Run isolated consumer lifecycle tests against free-supported LocalStack APIs.

Owns a fresh ephemeral container on loopback port 4567. Never reuses the user's
existing emulator, a real AWS backend, or real credentials. IAM enforcement and
AWS behavior remain unverified on Hobby; this is provider integration evidence.
"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import uuid

from scripts.consumer_platform import PLATFORM_ROOT, fixture_config, load_consumer
from scripts.team_platform import derive_context, render_inputs
from scripts.environments import backend_name, consumer_environments, read_json

ENDPOINT = "http://127.0.0.1:4567"
S3CONTROL_HOST = "localhost.localstack.cloud"
CONTAINER = "tfp-consumer-localstack"
RUN_LABEL = "com.sumup.terraform-platform.run-id"


def execute(args: list[str], *, env: dict | None = None, timeout: int = 180,
            accepted: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess:
    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=timeout)
    if result.returncode not in accepted:
        raise ValueError(f"{args[0]} {args[1]} failed:\n{result.stdout[-4000:]}\n{result.stderr[-4000:]}")
    return result


def isolated_environment(run: Path) -> dict[str, str]:
    # Keep runtime locations but exclude all ambient AWS/TF settings and proxies.
    keep = ("PATH", "HOME", "TMPDIR", "TMP", "TEMP", "SYSTEMROOT", "LANG", "LC_ALL")
    env = {key: os.environ[key] for key in keep if key in os.environ}
    empty = run / "empty-aws-config"
    empty.touch()
    env.update(AWS_ACCESS_KEY_ID="test", AWS_SECRET_ACCESS_KEY="test",
               AWS_DEFAULT_REGION="eu-central-1", AWS_REGION="eu-central-1",
               AWS_EC2_METADATA_DISABLED="true", AWS_MAX_ATTEMPTS="2",
               AWS_CONFIG_FILE=str(empty), AWS_SHARED_CREDENTIALS_FILE=str(empty),
               AWS_PAGER="", TF_IN_AUTOMATION="true", TF_INPUT="false")
    return env


def aws(env: dict, *args: str, timeout: int = 60) -> dict:
    result = execute(["aws", "--endpoint-url", ENDPOINT, "--region", "eu-central-1",
                      "--no-cli-pager", "--output", "json", *args], env=env, timeout=timeout)
    return json.loads(result.stdout) if result.stdout.strip() else {}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def source_hashes() -> dict[str, str]:
    return {str(p.relative_to(PLATFORM_ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for rel in ("modules/team-resources", "modules/team-backend", "modules/team-ci", "stacks/team", "stacks/backends")
            for p in (PLATFORM_ROOT / rel).iterdir()
            if p.suffix == ".tf" or p.name == ".terraform.lock.hcl"}


def prepare_source(run: Path) -> Path:
    for rel in ("modules/team-resources", "modules/team-backend", "modules/team-ci", "stacks/team", "stacks/backends"):
        destination = run / "source" / rel
        destination.mkdir(parents=True)
        for p in (PLATFORM_ROOT / rel).iterdir():
            if p.suffix == ".tf" or p.name == ".terraform.lock.hcl":
                shutil.copy2(p, destination / p.name)
    root = run / "source/stacks/team"
    (root / "providers.tf").write_text('''provider "aws" {
  region                  = var.region
  allowed_account_ids     = [var.account_id]
  skip_metadata_api_check = true
  s3_use_path_style       = true
  endpoints {
    s3        = "http://127.0.0.1:4567"
    s3control = "http://localhost.localstack.cloud:4567"
    iam       = "http://127.0.0.1:4567"
    sts       = "http://127.0.0.1:4567"
  }
}
''')
    # Bootstrap uses the actual platform backend module, with fixture-only endpoints.
    bootstrap = run / "source/stacks/backends"
    provider = (root / "providers.tf").read_text()
    provider = provider.replace('    iam       =', '    dynamodb  = "http://127.0.0.1:4567"\n    iam       =')
    (bootstrap / "provider_override.tf").write_text(provider)
    # The backend root uses the same explicit account/region variables. Its CI
    # registrations stay empty for this credential-free emulator fixture.
    return root


def workload_policy(names: dict[str, str], account: str) -> dict:
    buckets = [f"arn:aws:s3:::{names[k]}" for k in sorted(names)]
    objects = [f"{arn}/*" for arn in buckets]
    actions = ["s3:ListBucket", "s3:GetBucketLocation", "s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    return {"Version": "2012-10-17", "Statement": [
        {"Sid": "ListOwnedBuckets", "Effect": "Allow", "Action": actions[:2], "Resource": buckets},
        {"Sid": "ReadWriteOwnedObjects", "Effect": "Allow", "Action": actions[2:], "Resource": objects},
        {"Sid": "DenyOutsideOwnedResources", "Effect": "Deny", "Action": "s3:*", "NotResource": buckets + objects},
        {"Sid": "DenyWrongResourceAccount", "Effect": "Deny", "Action": actions,
         "Resource": buckets + objects, "Condition": {"StringNotEquals": {"s3:ResourceAccount": account}}},
    ]}


def empty_bucket(env: dict, bucket: str) -> None:
    # Drain the first bounded page repeatedly: dedicated container, no writers.
    # Do not combine unbounded CLI auto-pagination into a >1000-key delete.
    for _ in range(100):
        page = aws(env, "s3api", "list-object-versions", "--bucket", bucket,
                   "--max-keys", "1000", "--no-paginate", "--expected-bucket-owner", "000000000000")
        entries = [{"Key": item["Key"], "VersionId": item["VersionId"]}
                   for key in ("Versions", "DeleteMarkers") for item in page.get(key, [])]
        if not entries:
            require(not page.get("IsTruncated"), "empty truncated version page")
            return
        require(len(entries) <= 1000, "deletion page exceeds S3 batch limit")
        result = aws(env, "s3api", "delete-objects", "--bucket", bucket,
                     "--expected-bucket-owner", "000000000000", "--delete", json.dumps({"Objects": entries}))
        require(not result.get("Errors"), f"version cleanup errors: {result.get('Errors')}")
        require(len(result.get("Deleted", [])) == len(entries), "cleanup made incomplete progress")
    raise ValueError("version cleanup exceeded 100 pages; stopping")


class ConsumerRun:
    def __init__(self, team: str, declaration: dict, run: Path, root: Path, environment: dict, context: dict | None = None):
        self.team, self.declaration, self.root = team, copy.deepcopy(declaration), root
        config = fixture_config()
        config["environment"] = "demo"
        self.context = context or derive_context(team, config)
        self.context["account_id"] = "000000000000"
        self.context["trusted_principal_arn"] = "arn:aws:iam::000000000000:role/fixture-source"
        self.context["state_bucket"] = backend_name("000000000000", team)
        self.context["dynamodb_table"] = self.context["state_bucket"]
        self.label = f"{team}/{self.context['environment']}"
        self.directory = run / team / self.context["environment"]
        self.directory.mkdir(parents=True)
        self.env = {**environment, "TF_DATA_DIR": str(self.directory / "terraform-data")}
        local = PLATFORM_ROOT / ".local/bin/terraform"
        self.binary = str(local) if local.is_file() else shutil.which("terraform")
        require(bool(self.binary), "pinned Terraform executable is missing")
        self.known_buckets: set[str] = set()
        self.initialized = False
        self.inputs = self.directory / "inputs.tfvars.json"

    def tf(self, *args: str, accepted: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess:
        return execute([self.binary, f"-chdir={self.root}", *args], env=self.env,
                       timeout=300, accepted=accepted)

    def render(self) -> None:
        render_inputs(self.declaration, self.context, self.directory)
        self.known_buckets |= set(self.names().values())

    def names(self) -> dict[str, str]:
        return {key: f"sumup--{self.context['environment']}--{self.team}--{key}" for key in self.declaration["buckets"]}

    def initialize(self) -> None:
        version = self.tf("version", "-json")
        require(json.loads(version.stdout)["terraform_version"] == (PLATFORM_ROOT / ".terraform-version").read_text().strip(),
                "Terraform version differs from platform pin")
        self.render()
        backend = json.loads((self.directory / "backend.hcl.json").read_text())
        backend.update(endpoints={"s3": ENDPOINT, "dynamodb": ENDPOINT, "sts": ENDPOINT},
                       use_path_style=True, skip_metadata_api_check=True)
        (self.directory / "backend.hcl.json").write_text(json.dumps(backend))
        args = ["init", "-input=false", "-lockfile=readonly", f"-backend-config={self.directory / 'backend.hcl.json'}"]
        mirror = PLATFORM_ROOT / "modules/team-resources/.terraform/providers"
        if mirror.is_dir():
            args.append(f"-plugin-dir={mirror}")
        self.tf(*args)
        self.initialized = True

    def apply(self, label: str, *, tag_only: bool = False, no_delete: bool = False,
              failure_expected: bool = False) -> None:
        self.render()
        plan = self.directory / f"{label}.tfplan"
        self.tf("plan", "-input=false", f"-var-file={self.inputs}", f"-out={plan}")
        changes = json.loads(self.tf("show", "-json", str(plan)).stdout).get("resource_changes", [])
        for change in changes:
            if change["mode"] != "managed" or change["change"]["actions"] == ["no-op"]:
                continue
            if no_delete or tag_only:
                require("delete" not in change["change"]["actions"], f"unexpected replacement/deletion: {change['address']}")
            if tag_only:
                before, after = change["change"]["before"], change["change"]["after"]
                require(change["change"]["actions"] == ["update"], "owner edit must only update tags")
                require({k: v for k, v in before.items() if k not in ("tags", "tags_all")} ==
                        {k: v for k, v in after.items() if k not in ("tags", "tags_all")}, "owner edit changed non-tag attributes")
        result = self.tf("apply", "-input=false", str(plan), accepted=(0, 1) if failure_expected else (0,))
        if failure_expected:
            require(result.returncode != 0 and ("BucketNotEmpty" in result.stdout + result.stderr or
                    "bucket is not empty" in (result.stdout + result.stderr).lower()),
                    "expected populated-bucket deletion failure, not success or an unrelated error")

    def no_change(self) -> None:
        self.render()
        result = self.tf("plan", "-input=false", "-detailed-exitcode", f"-var-file={self.inputs}", accepted=(0, 2))
        require(result.returncode == 0, f"{self.team}: refreshed plan still contains changes")

    def inventory(self) -> None:
        names = self.names()
        outputs = json.loads(self.tf("output", "-json").stdout)
        require(outputs["bucket_names"]["value"] == names, "root bucket names/keys differ from declaration")
        role = f"tfp--{self.context['environment']}--{self.team}--s3"
        tags = {"Team": self.team, "Environment": self.context["environment"], "Owner": self.declaration["owner"], "ManagedBy": "Terraform"}
        role_data = aws(self.env, "iam", "get-role", "--role-name", role)["Role"]
        require({t["Key"]: t["Value"] for t in role_data["Tags"]} == tags, "role tags differ")
        trust = role_data["AssumeRolePolicyDocument"]
        require(trust == {"Version": "2012-10-17", "Statement": [{"Sid": "TrustConfiguredPrincipalOnly",
                "Effect": "Allow", "Principal": {"AWS": self.context["trusted_principal_arn"]}, "Action": "sts:AssumeRole"}]}, "workload trust differs")
        policy = aws(self.env, "iam", "get-role-policy", "--role-name", role, "--policy-name", "s3-access")["PolicyDocument"]
        require(policy == workload_policy(names, self.context["account_id"]), "whole workload policy differs")
        state = json.loads(self.tf("show", "-json").stdout)
        resources = state["values"]["root_module"]["child_modules"][0]["resources"]
        require(len(resources) == 6 * len(names) + 2, "unexpected managed resource count")
        for key, name in names.items():
            require(aws(self.env, "s3api", "get-bucket-versioning", "--bucket", name)["Status"] == "Enabled", "versioning missing")
            ownership = aws(self.env, "s3api", "get-bucket-ownership-controls", "--bucket", name)
            require(ownership["OwnershipControls"]["Rules"] == [{"ObjectOwnership": "BucketOwnerEnforced"}], "ownership differs")
            encryption = aws(self.env, "s3api", "get-bucket-encryption", "--bucket", name)
            require(encryption["ServerSideEncryptionConfiguration"]["Rules"][0]["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"] == "AES256", "encryption differs")
            actual_tags = aws(self.env, "s3api", "get-bucket-tagging", "--bucket", name)["TagSet"]
            require({t["Key"]: t["Value"] for t in actual_tags} == tags, "bucket tags differ")
            private = self.declaration["buckets"][key]["visibility"] == "private"
            flags = aws(self.env, "s3api", "get-public-access-block", "--bucket", name)["PublicAccessBlockConfiguration"]
            require(flags == {"BlockPublicAcls": True, "IgnorePublicAcls": True,
                              "BlockPublicPolicy": private, "RestrictPublicBuckets": private}, "public-access flags differ")
            expected = [{"Sid": "DenyInsecureTransport", "Effect": "Deny", "Principal": "*", "Action": "s3:*",
                         "Resource": [f"arn:aws:s3:::{name}", f"arn:aws:s3:::{name}/*"],
                         "Condition": {"Bool": {"aws:SecureTransport": "false"}}}]
            if not private:
                expected.append({"Sid": "AllowPublicReadCurrentObjects", "Effect": "Allow", "Principal": "*",
                                 "Action": "s3:GetObject", "Resource": f"arn:aws:s3:::{name}/*"})
            actual = json.loads(aws(self.env, "s3api", "get-bucket-policy", "--bucket", name)["Policy"])
            require(actual == {"Version": "2012-10-17", "Statement": expected}, "bucket policy differs")

    def object_roundtrip(self, bucket: str) -> str:
        body = self.directory / "synthetic.txt"
        body.write_text(f"Synthetic consumer test: {self.team}\n")
        result = aws(self.env, "s3api", "put-object", "--bucket", bucket, "--key", "fixture.txt", "--body", str(body))
        require(bool(result.get("VersionId")), "fixture upload is not versioned")
        destination = self.directory / "download.txt"
        response = aws(self.env, "s3api", "get-object", "--bucket", bucket, "--key", "fixture.txt", str(destination))
        require(destination.read_bytes() == body.read_bytes(), "object bytes differ")
        require(response.get("ServerSideEncryption") == "AES256", "uploaded object encryption differs")
        return result["VersionId"]

    def lifecycle(self) -> None:
        original = copy.deepcopy(self.declaration)
        private_key = next(k for k, v in original["buckets"].items() if v["visibility"] == "private")
        original_bucket = self.names()[private_key]
        version = self.object_roundtrip(original_bucket)
        self.declaration["buckets"] = dict(reversed(list(original["buckets"].items())))
        self.no_change()
        self.declaration["owner"] = original["owner"] + "+changed"
        self.apply("owner", tag_only=True)
        self.inventory()
        self.declaration = copy.deepcopy(original)
        self.declaration["buckets"]["growth-check"] = {"visibility": "private"}
        self.apply("add", no_delete=True)
        aws(self.env, "s3api", "head-object", "--bucket", original_bucket, "--key", "fixture.txt", "--version-id", version)
        self.inventory()
        public_keys = [k for k, v in original["buckets"].items() if v["visibility"] == "public"]
        if public_keys:
            key = public_keys[0]
            self.declaration["buckets"][key]["visibility"] = "private"
            self.apply("private", no_delete=True)
            self.inventory()
            self.declaration["buckets"][key]["visibility"] = "public"
            self.apply("public", no_delete=True)
            self.inventory()
        growth_bucket = self.names()["growth-check"]
        self.object_roundtrip(growth_bucket)
        grown = copy.deepcopy(self.declaration)
        del self.declaration["buckets"]["growth-check"]
        self.apply("blocked-removal", failure_expected=True)
        aws(self.env, "s3api", "head-object", "--bucket", growth_bucket, "--key", "fixture.txt")
        self.declaration = grown
        self.apply("recover")
        empty_bucket(self.env, growth_bucket)
        self.declaration = original
        self.apply("remove-empty-growth")
        self.inventory()
        self.no_change()

    def cleanup(self) -> None:
        if not self.initialized:
            return
        existing = {b["Name"] for b in aws(self.env, "s3api", "list-buckets").get("Buckets", [])}
        for name in self.known_buckets & existing:
            empty_bucket(self.env, name)
        self.tf("plan", "-destroy", "-input=false", f"-var-file={self.inputs}", f"-out={self.directory / 'destroy.tfplan'}")
        self.tf("apply", "-input=false", str(self.directory / "destroy.tfplan"))
        require(not self.tf("state", "list").stdout.strip(), "managed state is not empty after destroy")


def initialize_backends(run: Path, env: dict, teams: set[str]) -> None:
    root = run / "source/stacks/backends"
    binary = str(PLATFORM_ROOT / ".local/bin/terraform") if (PLATFORM_ROOT / ".local/bin/terraform").exists() else "terraform"
    variables = run / "backend-inputs.json"
    variables.write_text(json.dumps({"account_id": "000000000000", "region": "eu-central-1", "team_ids": sorted(teams)}))
    local_env = {**env, "TF_DATA_DIR": str(run / "bootstrap-data")}
    prefix = [binary, f"-chdir={root}"]
    args = ["init", "-input=false", "-lockfile=readonly"]
    mirror = PLATFORM_ROOT / "modules/team-resources/.terraform/providers"
    if mirror.is_dir():
        args.append(f"-plugin-dir={mirror}")
    execute(prefix + args, env=local_env, timeout=120)
    execute(prefix + ["plan", "-input=false", f"-var-file={variables}", f"-out={run / 'bootstrap.tfplan'}"], env=local_env, timeout=300)
    execute(prefix + ["apply", "-input=false", str(run / "bootstrap.tfplan")], env=local_env, timeout=300)
    for team in teams:
        name = backend_name("000000000000", team)
        require(aws(env, "s3api", "get-bucket-versioning", "--bucket", name)["Status"] == "Enabled", "backend versioning missing")
        flags = aws(env, "s3api", "get-public-access-block", "--bucket", name)["PublicAccessBlockConfiguration"]
        require(all(flags.values()) and len(flags) == 4, "backend must block all public access")
        encryption = aws(env, "s3api", "get-bucket-encryption", "--bucket", name)
        require(encryption["ServerSideEncryptionConfiguration"]["Rules"][0]["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"] == "AES256", "backend encryption missing")
        table = aws(env, "dynamodb", "describe-table", "--table-name", name)["Table"]
        require(table["KeySchema"] == [{"AttributeName": "LockID", "KeyType": "HASH"}], "backend LockID key differs")
        require(table["DeletionProtectionEnabled"], "lock table deletion protection missing")


def verify_backend_locking(consumers: list[ConsumerRun], report: dict) -> None:
    first = consumers[0]
    lock_id = f"{first.context['state_bucket']}/{first.context['state_key']}"
    info = json.dumps({"ID": "11111111-1111-1111-1111-111111111111", "Operation": "OperationTypeApply",
                       "Info": "synthetic lock contention", "Who": "localstack-test", "Version": "1.17.1",
                       "Created": datetime.now(timezone.utc).isoformat(), "Path": lock_id})
    aws(first.env, "dynamodb", "put-item", "--table-name", first.context["dynamodb_table"],
        "--item", json.dumps({"LockID": {"S": lock_id}, "Info": {"S": info}}),
        "--condition-expression", "attribute_not_exists(LockID)")
    try:
        result = first.tf("plan", "-input=false", "-lock-timeout=1s", f"-var-file={first.inputs}", accepted=(1,))
        require("Error acquiring the state lock" in result.stdout + result.stderr, "held DynamoDB lock did not reject a Terraform plan")
        for other in consumers:
            if other.context["state_key"] != first.context["state_key"]:
                other.no_change()  # Independent environments/teams remain usable while the first lock is held.
        report["s3_backend_locking"] = "PASS"
    finally:
        aws(first.env, "dynamodb", "delete-item", "--table-name", first.context["dynamodb_table"],
            "--key", json.dumps({"LockID": {"S": lock_id}}))
    first.no_change()
    for consumer in consumers:
        versions = aws(consumer.env, "s3api", "list-object-versions", "--bucket", consumer.context["state_bucket"],
                       "--prefix", consumer.context["state_key"]).get("Versions", [])
        require(bool(versions), "state object was not stored/versioned in S3")
        head = aws(consumer.env, "s3api", "head-object", "--bucket", consumer.context["state_bucket"], "--key", consumer.context["state_key"])
        require(head.get("ServerSideEncryption") == "AES256" and bool(head.get("VersionId")), "S3 state object lacks encryption/version")


def run_consumers(directories: list[Path], team_id: str | None = None, *, baseline_only: bool = False) -> Path:
    require(team_id is None or len(directories) == 1, "--team-id requires exactly one consumer directory")
    loaded = []
    for directory in directories:
        team = team_id or directory.name
        if (directory / "environments").is_dir():
            require(read_json(directory / "team.json") == {"team_id": team}, "consumer team.json differs from selected team")
            for path in consumer_environments(directory):
                loaded.append((team, *load_consumer(path, team)))
        else:
            declaration, context = load_consumer(directory, team)
            context["environment"] = "demo"
            loaded.append((team, declaration, context))
    require(len({(t, c["environment"]) for t, _, c in loaded}) == len(loaded), "duplicate consumer team/environment IDs")
    require(bool(os.environ.get("LOCALSTACK_AUTH_TOKEN")), "LOCALSTACK_AUTH_TOKEN is missing; no paid trial will be activated")
    image = (PLATFORM_ROOT / ".localstack-image").read_text().strip()
    require(bool(re.fullmatch(r"localstack/localstack(?:-pro)?@sha256:[0-9a-f]{64}", image)), "LocalStack image must be pinned by digest")
    # S3 Control actually connects to the account-prefixed hostname, not the
    # base endpoint string. A hosts-file entry for that name is sufficient.
    for host in ("000000000000." + S3CONTROL_HOST,):
        addresses = {item[4][0] for item in socket.getaddrinfo(host, 4567, family=socket.AF_INET)}
        require(addresses == {"127.0.0.1"}, f"{host} must resolve only to 127.0.0.1; configure local DNS before running")
    require(shutil.which("docker") is not None and shutil.which("aws") is not None, "Docker and AWS CLI v2 are required")
    run_id = uuid.uuid4().hex
    run = PLATFORM_ROOT / ".runs/localstack" / run_id
    run.mkdir(parents=True, mode=0o700)
    env = isolated_environment(run)
    before = source_hashes()
    report = {"run_id": run_id, "started_at": datetime.now(timezone.utc).isoformat(),
              "image": image, "entitlement": "Hobby (user-provided)",
              "tool_versions": {"python": sys.version.split()[0],
                                "terraform": (PLATFORM_ROOT / ".terraform-version").read_text().strip(),
                                "aws_cli": execute(["aws", "--version"], env=env).stdout.strip()},
              "source_hashes": before, "consumers": {}, "status": "FAIL",
              "iam_enforcement": "UNVERIFIED", "aws_acceptance": "UNVERIFIED", "s3_backend_locking": "NOT_RUN", "backend_type": "S3 + DynamoDB", "mode": "baseline-only" if baseline_only else "full-lifecycle"}
    consumers: list[ConsumerRun] = []
    errors = []
    bootstrap_created = False
    try:
        require(execute(["docker", "ps", "-aq", "--filter", f"name=^/{CONTAINER}$"]).stdout.strip() == "",
                f"{CONTAINER} already exists; do not reuse or delete an unrelated container")
        execute(["docker", "run", "--detach", "--name", CONTAINER, "--label", f"{RUN_LABEL}={run_id}",
                 "--publish", "127.0.0.1:4567:4566", "--env", "LOCALSTACK_AUTH_TOKEN", "--env", "PERSISTENCE=0",
                 "--env", "SERVICES=s3,s3control,iam,sts,dynamodb", image], timeout=120)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                with opener.open(ENDPOINT + "/_localstack/health", timeout=2) as response:
                    report["runtime_version"] = json.load(response)["version"]
                if aws(env, "sts", "get-caller-identity", timeout=3)["Account"] == "000000000000":
                    break
            except (OSError, ValueError, subprocess.TimeoutExpired):
                time.sleep(1)
        else:
            raise ValueError("LocalStack did not become ready within the bounded readiness checks")
        require(not aws(env, "s3api", "list-buckets").get("Buckets"), "new emulator must start with no buckets")
        aws(env, "iam", "create-role", "--role-name", "fixture-source", "--assume-role-policy-document",
            json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "ecs-tasks.amazonaws.com"}, "Action": "sts:AssumeRole"}]}))
        bootstrap_created = True
        root = prepare_source(run)
        initialize_backends(run, env, {team for team, _, _ in loaded})
        for team, declaration, context in loaded:
            # Always emulate fixture account/region, even after real catalogs are configured.
            context = derive_context(team, {**fixture_config(), "environment": context["environment"]})
            consumer = ConsumerRun(team, declaration, run, root, env, context)
            consumers.append(consumer)
            consumer.initialize()
            consumer.apply("initial")
            consumer.inventory()
            consumer.no_change()
            report["consumers"][consumer.label] = {"buckets": consumer.names(), "bucket_count": len(declaration["buckets"]),
                                         "declaration_sha256": hashlib.sha256(json.dumps(declaration, sort_keys=True).encode()).hexdigest(),
                                         "backend_key": consumer.context["state_key"], "baseline": "PASS"}
            print(f"{consumer.label}: baseline apply, API configuration/policy readback, separate state, no-change plan PASS", flush=True)
        verify_backend_locking(consumers, report)
        for consumer in consumers:
            if baseline_only:
                report["consumers"][consumer.label]["lifecycle"] = "NOT_RUN"
                continue
            consumer.lifecycle()
            report["consumers"][consumer.label]["lifecycle"] = "PASS"
            report["consumers"][consumer.label]["visibility_transition"] = "PASS" if any(
                v["visibility"] == "public" for v in consumer.declaration["buckets"].values()) else "NOT_APPLICABLE"
            print(f"{consumer.label}: roundtrip, reorder, owner edit, add/remove/recovery PASS; visibility checked where permitted", flush=True)
        require(len({c.context["state_key"] for c in consumers}) == len(consumers), "state keys overlap")
        require(len({c.env["TF_DATA_DIR"] for c in consumers}) == len(consumers), "initialization directories overlap")
        for consumer in consumers:
            consumer.inventory()
            consumer.no_change()
        report["status"] = "PASS"
    except (ValueError, OSError, KeyError, subprocess.TimeoutExpired) as exc:
        errors.append(str(exc))
    finally:
        # Inspect only ownership label, never environment/token values.
        cleanup_errors = []
        owned = False
        try:
            owned = execute(["docker", "inspect", "--format", f'{{{{index .Config.Labels "{RUN_LABEL}"}}}}', CONTAINER], accepted=(0, 1)).stdout.strip() == run_id
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            cleanup_errors.append(f"container ownership check: {exc}")
        if owned:
            for consumer in reversed(consumers):
                try:
                    consumer.cleanup()
                except (ValueError, OSError, KeyError, subprocess.TimeoutExpired) as exc:
                    cleanup_errors.append(f"{consumer.team} cleanup: {exc}")
            # A failed docker run may leave a created-but-not-running container
            # after a port collision. Never call APIs on that occupied port
            # unless this run completed its own bootstrap successfully.
            if bootstrap_created:
                try:
                    remaining = aws(env, "s3api", "list-buckets").get("Buckets", [])
                    expected_backends = {c.context["state_bucket"] for c in consumers}
                    require({b["Name"] for b in remaining} == expected_backends, "unexpected buckets remain after workload destroy")
                    for bucket in expected_backends:
                        empty_bucket(env, bucket)
                        aws(env, "s3api", "delete-bucket", "--bucket", bucket)
                        aws(env, "dynamodb", "update-table", "--table-name", bucket, "--no-deletion-protection-enabled")
                        aws(env, "dynamodb", "delete-table", "--table-name", bucket)
                    require(not aws(env, "s3api", "list-buckets").get("Buckets"), "fixture backend buckets remain")
                    for consumer in consumers:
                        role = f"tfp--{consumer.context['environment']}--{consumer.team}--s3"
                        roles = aws(env, "iam", "list-roles").get("Roles", [])
                        require(role not in {r["RoleName"] for r in roles}, "workload role remains after destroy")
                    aws(env, "iam", "delete-role", "--role-name", "fixture-source")
                except (ValueError, OSError, KeyError, subprocess.TimeoutExpired) as exc:
                    cleanup_errors.append(f"bootstrap cleanup: {exc}")
            try:
                execute(["docker", "rm", "--force", CONTAINER])
            except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
                cleanup_errors.append(f"container removal: {exc}")
        if source_hashes() != before:
            errors.append("original Terraform source/locks changed during integration")
        report["cleanup"] = "FAIL" if cleanup_errors else ("PASS" if owned else "NOT_RUN")
        errors.extend(cleanup_errors)
        if errors:
            report.update(status="FAIL", errors=errors)
        evidence = run / "evidence.json"
        evidence.write_text(json.dumps(report, indent=2) + "\n")
        print(f"Sanitized evidence: {evidence}", flush=True)
    require(not errors, "\n".join(errors))
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--consumer-dir", type=Path, action="append", required=True)
    parser.add_argument("--baseline-only", action="store_true", help="Verify bootstrap, apply, state/locking and reapply; skip extended lifecycle mutations")
    parser.add_argument("--team-id", help="Stable ID for one consumer checked out under an arbitrary directory name")
    args = parser.parse_args()
    lock_path = PLATFORM_ROOT / ".runs/localstack.lock"
    lock_path.parent.mkdir(exist_ok=True)
    try:
        with lock_path.open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            run_consumers([p.resolve() for p in args.consumer_dir], args.team_id, baseline_only=args.baseline_only)
    except (ValueError, OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"LocalStack integration failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
