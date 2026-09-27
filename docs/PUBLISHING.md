# Publishing checklist

The project is published in the public GitHub repository below. The public
project site is deployed from `site/` by `.github/workflows/pages.yml`.

## Public branding pages

After GitHub Pages has completed its first deployment, use:

- Homepage: <https://jeyapaul.github.io/personal-digital-assistant/>
- Privacy policy: <https://jeyapaul.github.io/personal-digital-assistant/privacy.html>
- Terms of service: <https://jeyapaul.github.io/personal-digital-assistant/terms.html>

The policy identifies the self-hosted data flow, including local model
processing and the operator-configured Discord DM. These pages are project
information and are not legal advice. Google may require the Pages domain to be
verified in Search Console and added as an authorized domain; if Google does
not accept the GitHub Pages domain, configure a domain you control and point it
to the site before submitting OAuth branding/verification.

## Before each public push

- Keep `.env`, OAuth credentials/client JSON, Discord tokens, databases, mail
  output, screenshots, personal account IDs, and machine-specific absolute
  paths out of the source tree.
- Review the full Git history as well as the current staged diff. Removing a
  credential from the latest tree does not remove it from earlier commits; if a
  real credential is found, revoke/rotate it and purge history before pushing.
- Do not publish private email, provider data, approval audit records, or
  runtime data. Use only synthetic fixtures.
- Check `.gitignore` and `.dockerignore`; review the staged file list.
- The selected public contact email (`jeyshiva@gmail.com`) is intentionally
  published on the site and will be visible to visitors.

## Repository and Pages settings

- Repository: `Jeyapaul/personal-digital-assistant` (public).
- Set the repository website to the project homepage URL above.
- Enable GitHub Pages with **GitHub Actions** as the build/deployment source.
- Keep Actions permissions minimal; the Pages workflow grants only the
  deployment permissions it needs.
- Enable private vulnerability reporting, Dependabot alerts, and push
  protection/secret scanning where available.
- Protect `main` with CI checks and review requirements when the repository
  collaboration model supports them.
- Do not put tokens in Git remote URLs or command history. Use the authenticated
  GitHub CLI or the harness-managed Git credentials.
