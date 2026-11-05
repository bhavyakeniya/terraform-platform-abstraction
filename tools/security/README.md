# Isolated, locked scanner dependencies

Checkov and all transitive dependencies are resolved in this directory's uv.lock.
They are separate from the platform application's environment. The host's global
Checkov is deliberately ignored: the same reported package version produced a
different graph-check result with Homebrew dependencies during verification.

`make security-tools` installs this environment with --locked and the project's
pinned Python. The scanner uses tools/security/.venv/bin/checkov directly.
Update config/security-tools.json, this pyproject.toml and uv.lock together when
upgrading, then run both real scanner canaries and the full security fixture.
