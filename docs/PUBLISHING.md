# Publishing checklist

This repository is locally prepared on the `main` branch with one clean
initial commit. No GitHub remote or repository has been created.

## Before creating the repository

- Review the owner and year in `LICENSE`.
- Decide whether the repository should be public or private initially.
- Confirm that the current `.gitignore` and `.dockerignore` rules still exclude
  all credentials and runtime state.
- Keep provider credentials, Discord tokens, OAuth client files, and Hermes
  data outside the repository.
- Review the first commit with:

  ```bash
  git show --stat --summary HEAD
  git grep -n -E 'BEGIN .*PRIVATE KEY|access_token|refresh_token|client_secret' HEAD -- ':!tests'
  ```

  The last command should only show code that handles those fields, never real
  values.

## Creating the GitHub repository later

Create an empty repository without adding a README, license, or `.gitignore`,
then add its URL locally:

```bash
git remote add origin https://github.com/OWNER/REPOSITORY.git
git push -u origin main
```

Do not put tokens in the remote URL or shell history. Use GitHub CLI login,
SSH, or the configured credential helper.

## Repository settings

After the first push:

- Enable Dependabot or another dependency update process if Docker base images
  and GitHub Actions are updated regularly.
- Keep Actions permissions at least as restrictive as `.github/workflows/ci.yml`.
- Enable private vulnerability reporting if the repository is public.
- Protect `main` with pull requests and required CI checks.
- Add a repository description and topics such as `hermes`, `ollama`,
  `gmail`, `discord`, `docker`, and `macos`.
- Never add runtime data, provider credentials, or personal identifiers to
  issues, pull requests, examples, or screenshots.
