# Security policy

## Supported versions

Only the latest release (and the current `main` branch) receives fixes.

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Report them privately via
[GitHub's private vulnerability reporting](https://github.com/spielkind/shop-notify/security/advisories/new)
instead. You can expect a first answer within a week.

Please include the affected version (`shop-notify --version`), how it is run (Docker,
systemd, locally) and steps to reproduce.

## How reports are handled

1. **Acknowledge** – a maintainer confirms receipt within a week.
2. **Assess** – we reproduce the issue, rate its severity (CVSS) and agree on a
   timeline with the reporter. If it is not a vulnerability, we explain why.
3. **Fix** – the fix is developed in a private fork of the security advisory and
   reviewed there; a CVE is requested through GitHub if appropriate.
4. **Release** – a patch release with the fix is published (target: within 60 days of
   the report, critical issues as soon as possible); the image is rebuilt and the
   changelog lists the fix under *Security*.
5. **Disclose** – the [security advisory](https://github.com/spielkind/shop-notify/security/advisories)
   is published together with the release.

Reporters are credited by name (or handle) in the advisory and the changelog, unless
they prefer to stay anonymous.

What Shop Notify protects and the threat model are described in
[docs/security.md](docs/security.md).

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

## Verifying releases

Docker images, release files and PyPI packages carry signed build provenance from this
repository's release workflow:

```sh
gh attestation verify oci://ghcr.io/spielkind/shop-notify:latest --owner spielkind
gh attestation verify shop_notify-X.Y.Z-py3-none-any.whl --owner spielkind
```

On PyPI the attestations are shown under *Verified details* of each file.

## Handling secrets

Shop Notify works with credentials: the Etsy API key and shared secret, mail
passwords and bot tokens in `.env` and `notify.yml`. They are masked in the log, never
copied into the Docker image and ignored by git. In addition, [gitleaks](https://github.com/gitleaks/gitleaks)
checks every commit (pre-commit hook) and every push and pull request (CI) for secrets,
including passwords and bot tokens in notification URLs (see `.gitleaks.toml`). If you share logs or configuration in an
issue, double-check that no credentials are included – if one leaked, revoke it (Etsy
app, Google app password, Telegram `@BotFather`).
