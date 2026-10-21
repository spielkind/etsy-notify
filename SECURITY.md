# Security policy

## Supported versions

Only the latest release (and the current `main` branch) receives fixes.

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Report them privately via
[GitHub's private vulnerability reporting](https://github.com/spielkind/shop-notify/security/advisories/new)
instead. You can expect a first answer within a week.

Please include the affected version (`shop-notify --version`), how it is run (Docker,
systemd, locally) and steps to reproduce.

## Vulnerability scanning

- Every Docker build (pull requests, `main`, releases) is scanned with
  [Trivy](https://trivy.dev). Fixable critical, high and medium vulnerabilities are
  reported; critical and high ones fail the build. Vulnerabilities without a fix and
  low ones are not reported.
- Every Monday the released image (`latest`) is scanned again and `main` is rebuilt
  and scanned, so that newly published vulnerabilities show up even without changes
  to the repository. These scheduled scans don't fail; findings appear under
  [Security → Code scanning](https://github.com/spielkind/shop-notify/security/code-scanning)
  and in the job summary of the run. The tool name shows which image is affected:
  **Trivy (latest)** = the released image, **Trivy (main)** = the current development
  state (filter with the *Tool* drop-down or e.g. `tool:"Trivy (latest)"`). A finding that
  only appears for *Trivy (latest)* is fixed by the next release.
- Python dependencies are monitored by Dependabot.

If the released image is affected and the fix is already in `main` (usually through a
newer base image), a patch release is published.

## Handling secrets

Shop Notify works with credentials: the Etsy API key and shared secret, mail
passwords and bot tokens in `.env` and `notify.yml`. They are masked in the log, never
copied into the Docker image and ignored by git. If you share logs or configuration in an
issue, double-check that no credentials are included – if one leaked, revoke it (Etsy
app, Google app password, Telegram `@BotFather`).
