# Security

This document describes what Shop Notify protects, what it does not protect, and why we
believe its security requirements are met (assurance case). How to report a
vulnerability is described in [SECURITY.md](../SECURITY.md); the components and data
flows are described in [architecture.md](architecture.md).

## Security requirements

Shop Notify handles no user accounts and no payments. Its assets are the **credentials
in its configuration** and the **integrity of the notifications**. It must:

1. **Keep credentials confidential**: the Etsy API key and shared secret and the
   passwords and tokens in notification URLs must not appear in logs, notifications,
   images, the repository or error messages.
2. **Treat shop content as untrusted**: titles, URLs and image URLs from the Etsy API
   must not lead to code execution, injection into the database or HTML/markup injection
   into notifications, and a malformed response must not stop the service.
3. **Only talk to the configured services over authenticated channels**: Etsy and
   images via HTTPS with certificate verification; notification services as configured
   by the operator.
4. **Run with least privilege**: no root, no listening ports, no write access outside
   its data directory.
5. **Deliver unmodified software**: releases and images must be traceable to the
   source code in this repository and verifiable by users.

## What is not protected

Users should be aware of these limits:

- **Anyone with access to the host or the container** can read `.env`, `notify.yml`
  and the database. Protect these files with file permissions (the systemd unit uses
  `UMask=0077` and a private state directory); Shop Notify does not encrypt them.
- **Notification services see the content of the notifications.** Some services are
  public by design: an ntfy topic on `ntfy.sh` without an account can be read by anyone
  who guesses its name – use a long, random topic or your own server.
- **Notification transport security depends on the URL.** Apprise uses TLS where the
  service supports it; an SMTP URL with `mode=insecure` or a plain `http://` webhook
  sends data unencrypted. The operator chooses the targets.
- **Content of listings is shown as is.** A shop owner can put misleading text or links
  in a listing; Shop Notify escapes it but cannot judge whether it is trustworthy.
- **Availability depends on Etsy.** If the API is unavailable or the quota is used up,
  notifications are delayed; a failed delivery is retried with the next poll.
- **No protection against a compromised Etsy API, notification service or Python
  package index** beyond TLS and the pinned, hash-checked dependencies.

## Threat model

| Threat | Entry point | Mitigation |
|---|---|---|
| Credentials leak through logs or bug reports | log output, `--help`, exceptions | `SecretStr` in the settings; notification targets are logged with Apprise's privacy mode (passwords masked); the Etsy key is only sent as an HTTP header |
| Credentials committed to git | developer workstation | `.env` and `notify.yml` in `.gitignore`; gitleaks in pre-commit and CI with rules for notification URLs; GitHub secret scanning with push protection |
| Credentials baked into the image | Docker build | `.dockerignore`; configuration only via `env_file` and mounted files at runtime |
| HTML injection via listing titles | Etsy API → e-mail | Jinja2 autoescaping for HTML templates, `StrictUndefined` |
| SQL injection | Etsy API → SQLite | parameterised queries only |
| Malformed or hostile API responses | Etsy API | pydantic validation of every item; invalid items are skipped and logged; timeouts and bounded retries |
| Man-in-the-middle | network | HTTPS with certificate verification (httpx defaults, not configurable); the default Etsy endpoint is HTTPS |
| Privilege escalation after a compromise | runtime | non-root container user, no pip/build tools in the image; sandboxed systemd unit (`NoNewPrivileges`, `ProtectSystem=strict`, system call filter, no capabilities) |
| Vulnerable dependencies | supply chain | `uv.lock` with hashes, Dependabot (with 7-day cooldown), pip-audit in CI, Trivy scans of every image and weekly scans of the released image |
| Malicious or compromised CI actions | supply chain | actions pinned by commit SHA (enforced by repository setting), read-only default token, minimal job permissions, zizmor and actionlint |
| Tampered releases | distribution | signed tags that must point to `main`; immutable GitHub releases; SBOM and signed build provenance (Sigstore) for packages and images |
| Unauthorised changes to `main` | repository | ruleset: pull requests with required checks, signed commits, no force pushes or deletion |

## Assurance case

**Claim:** Shop Notify meets the security requirements above.

**Arguments and evidence:**

1. **Small attack surface.** The process opens no ports, accepts no inbound
   connections and has a single untrusted input (Etsy API responses and images).
   Everything else is configuration supplied by the operator.
   *Evidence:* [architecture.md](architecture.md#external-interfaces-and-trust-boundaries).
2. **Untrusted input is validated and encoded at the boundaries** (requirement 2).
   Responses are parsed into pydantic models item by item; data reaches SQLite only
   through parameterised queries and HTML only through autoescaped templates; no input
   is passed to a shell, `eval` or the file system.
   *Evidence:* `etsy.py`, `db.py`, `notifications.py`; tests for invalid responses,
   escaping and property-based tests with Hypothesis.
3. **Secrets are typed and kept out of outputs** (requirement 1). *Evidence:*
   `SecretStr` in `config.py`, tests that check that the log does not contain secrets,
   gitleaks and GitHub push protection.
4. **Secure defaults and least privilege** (requirements 3 and 4). TLS certificate
   verification is always on; the container runs as `1000:1000`; the systemd unit is
   sandboxed. *Evidence:* `Dockerfile`, CI smoke test (`id -u` = 1000),
   `contrib/systemd/shop-notify.service`.
5. **Common weaknesses are addressed by tooling** (CWE/OWASP classes such as injection,
   hard-coded credentials, vulnerable components). *Evidence:* CodeQL, ruff, mypy
   strict, gitleaks, pip-audit, Trivy, zizmor, hadolint – all run on
   every pull request and must pass.
6. **Verified supply chain** (requirement 5). *Evidence:* pinned dependencies and base
   images, signed tags, immutable releases, SBOM and provenance attestations
   (`gh attestation verify`), OpenSSF Scorecard.
7. **Behaviour is tested end to end.** 100 % line and branch coverage plus an
   end-to-end test of the Docker image against a fake Etsy API and a mail server.

**Design principles applied** (Saltzer and Schroeder): economy of mechanism (one
process, few dependencies), fail-safe defaults (TLS verification, silent first run,
no notification on doubt), least privilege, complete mediation of untrusted input at
the API boundary, separation of configuration from code, and open design (all security
measures are public in this repository).

**Residual risks** are listed under [What is not protected](#what-is-not-protected).
