# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Python package versions use the equivalent [PEP 440](https://peps.python.org/pep-0440/)
notation (e.g. `1.0.0rc1` for `1.0.0-rc.1`).

## [Unreleased]

### Added
- Releases include the wheel, the source archive and a CycloneDX SBOM with
  signed build provenance

### Security
- Weekly scheduled scan of the released image and rebuild of `main`;
  old commit images are cleaned up automatically
- The Docker image is scanned for vulnerabilities (Trivy); pip was removed
  from the runtime image as its vendored libraries were outdated
- Base images are pinned by digest

### Changed
- `compose.yaml`: container is named `shop-notify` (was `shop-notify-shop-notify-1`)

## [1.0.0-rc.3] - 2026-10-21

First release verified against the real Etsy API (#6).

### Added
- Push and chat services (ntfy, Telegram, …) get one message per new item
  with its picture; e-mail stays one HTML message with all items.
  `NOTIFY_IMAGES`, `NOTIFY_IMAGES_MAX` (default 5, above that one summary
  message) and `NOTIFY_IMAGES_IN_SUMMARY` (attach pictures to the summary,
  e.g. as Telegram album); new templates `item_subject.txt.j2` and
  `item_body.txt.j2` (#10)

### Changed
- New items are notified newest first (in Etsy's order) instead of by listing ID
- HTTP requests are only logged with `LOG_LEVEL=DEBUG`

## [1.0.0-rc.2] - 2026-10-21

### Added
- `shop-notify test-notify` sends a sample notification to all configured
  targets and reports the result per target; works without Etsy credentials,
  `--url` tests a single Apprise URL (#9)
- German notification messages with `NOTIFY_LANGUAGE=de`; dates and prices
  are formatted per language, new template filter `money` (#11)

### Fixed
- A single malformed listing in an Etsy response no longer fails the whole
  poll: it is skipped with a warning; a malformed price is ignored
- Docker image: install time zone data so that `TZ` (e.g. `Europe/Berlin`)
  applies to dates in notifications and logs

### Changed
- English messages now use English date and price formats
  (`Oct 14, 2026, 19:46`, `€24.50`); built-in templates moved to
  `templates/<language>/`
- Notifications are sent to each target separately; the warning for partial
  failures names the failed targets

## [1.0.0-rc.1] - 2026-10-21

Complete rewrite of the original 2019 tool as **Shop Notify**. Release candidate
until it has been verified against the real Etsy API with an approved key.

### Added
- Etsy Open API v3 client: API key authentication, pagination, `retry-after`
  handling on `429`, daily quota tracking with a warning below 20 % left
- `ETSY_SHOP_NAME` as alternative to `ETSY_SHOP_ID`; the ID is looked up at startup
- Notifications via [Apprise](https://github.com/caronc/apprise): e-mail, ntfy,
  Telegram and 100+ other services, configured in `notify.yml` (`NOTIFY_CONFIG`)
  or `NOTIFY_URLS`; credentials are masked in the log
- HTML e-mails with item image, price and date; plain text for other services;
  customisable Jinja2 templates (`NOTIFY_TEMPLATE_DIR`)
- `NOTIFY_CONSOLE` to print notifications to stdout in addition to other targets
- First run: items already in the shop are only recorded and shown on the
  console (`NOTIFY_EXISTING_ON_FIRST_RUN` to send them anyway)
- Every notified item is logged with title and URL
- `shop-notify healthcheck` based on a heartbeat file, `shop-notify --version`
- Docker image for `linux/amd64` and `linux/arm64` on GHCR with SBOM and
  signed build provenance, `compose.yaml`
- systemd unit with sandboxing and `Type=notify` (readiness, status line, watchdog)
- Graceful shutdown on `SIGINT`/`SIGTERM`; Etsy and notification errors no
  longer stop the polling loop
- CI: ruff, mypy (strict), pytest with 100 % coverage, pip-audit, actionlint,
  Docker builds for both architectures; pre-commit hooks

### Changed
- Renamed from `etsy-notify` to `shop-notify` (package, command, image, service)
- Python 3.14+, dependency management with uv instead of Pipenv
- `POLL_INTERVAL` defaults to 300 seconds and is configurable
- All settings are read from `.env` or environment variables; nothing is
  hard-coded anymore
- SQLite storage keeps only listing ID, title, URL, price and modification time

### Removed
- Etsy API v2 and OAuth 1 (shut down by Etsy)
- Built-in Gmail sender (`GMAIL_*`, `MAIL_*` settings); use an Apprise
  `mailtos://` URL instead
- Travis CI and Rancher pipeline configuration

## 0.1.0 - 2019

Original version for the Etsy API v2 (never tagged).

[Unreleased]: https://github.com/spielkind/shop-notify/compare/v1.0.0-rc.3...HEAD
[1.0.0-rc.3]: https://github.com/spielkind/shop-notify/compare/v1.0.0-rc.2...v1.0.0-rc.3
[1.0.0-rc.2]: https://github.com/spielkind/shop-notify/compare/v1.0.0-rc.1...v1.0.0-rc.2
[1.0.0-rc.1]: https://github.com/spielkind/shop-notify/releases/tag/v1.0.0-rc.1
