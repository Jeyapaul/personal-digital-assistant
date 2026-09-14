# Contributing

Thanks for contributing. This project prioritizes least privilege, local model
execution, read-only mail access, and prompt-injection resistance.

## Before opening a pull request

Run the offline checks:

```bash
./scripts/verify-phase1.sh
./scripts/verify-phase2.sh
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m py_compile scripts/*.py .hermes/plugins/personal-assistant-mail/*.py
sh -n scripts/*.sh docker/container-entrypoint.sh
```

Do not run live OAuth, Gmail, Microsoft, or Discord operations in CI. Use
fixtures and synthetic credentials only.

## Changes involving capabilities

Any change to tools, API hosts, scopes, network policy, Discord delivery,
container privileges, or scheduled execution must update the relevant
security documentation and tests. Do not add broad Google Workspace,
Himalaya, terminal, browser, shell, or mutation capabilities to the scheduled
profile without an explicit design review.

Never include real email bodies, tokens, client secrets, Discord IDs, or runtime
state in commits.
