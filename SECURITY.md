# Security policy

## Scope

This project handles OAuth refresh tokens, a Discord bot token, email metadata,
and potentially untrusted email bodies. Treat the default deployment as a
personal, single-user system.

## Reporting a vulnerability

Please do not open a public issue containing credentials, tokens, personal
email content, Discord identifiers, or an exploit that could expose them.
Use GitHub's private vulnerability reporting feature when it is enabled for the
repository, or contact the repository owner privately before disclosure.

## Credential rules

- Never commit `.env`, OAuth files, Discord tokens, client secrets, or runtime
  data.
- Keep credential files mode `0600` and outside the repository.
- Revoke and replace any credential that is accidentally exposed.
- Do not paste tokens into issues, pull requests, logs, or chat.
- Review network allowlists and container privileges before deployment.

Security fixes should include a regression test where practical and must not
include real provider data in fixtures.
