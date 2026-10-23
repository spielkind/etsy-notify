# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Python package versions use the equivalent [PEP 440](https://peps.python.org/pep-0440/)
notation (e.g. `1.0.0rc1` for `1.0.0-rc.1`).

## [Unreleased]

## [1.3.0] - 2026-10-23

### Added
- More events, chosen with `NOTIFY_EVENTS` (default `new,back`): `restocked`
  (a sold-out item is available again – notified right away), `price_drop`,
  `price_rise` (`NOTIFY_PRICE_CHANGE_PERCENT`, default 5), `sold_out` and
  `low_stock` (`NOTIFY_LOW_STOCK`, default 1); documented in `docs/events.md`
- For items that disappear from the shop, Etsy is asked why: sold out,
  deactivated, expired or removed; recorded in the history
- Quantities are stored; messages mention when only a few are left
- Messages and subjects for every event, in English and German; template
  variables `item.kind`, `item.event` and new filters
- `history --polls` counts sold-out and restocked items

### Changed
- Database schema version 3 with a notification queue; upgraded automatically
  with a backup copy `<DB_PATH>.bak-v2`
- `NOTIFY_BACK` is superseded by `NOTIFY_EVENTS`; `NOTIFY_BACK=false` still
  works

## [1.2.0] - 2026-10-22

### Added
- Filters: exclude or include items by keyword or regular expression and limit
  the price, in `.env` (`NOTIFY_EXCLUDE`, `NOTIFY_INCLUDE`,
  `NOTIFY_EXCLUDE_REGEX`, `NOTIFY_INCLUDE_REGEX`, `NOTIFY_MIN_PRICE`,
  `NOTIFY_MAX_PRICE`) or in a YAML file (`FILTER_CONFIG`, see
  `filters.example.yml`); documented with many examples in `docs/filters.md`
- Filtered items are recorded in the history (`filtered` with the rule) and
  notified once they pass, e.g. after the title changed
- `shop-notify check-filters` tests a title or the items of a period against
  the filters

### Changed
- Database schema version 2 (column `filtered`); upgraded automatically with a
  backup copy `<DB_PATH>.bak-v1`

## [1.1.0] - 2026-10-22

### Added
- History of every listing: when it appeared, was notified, went missing, was
  gone or came back, and changes of price and title; plus a log of the polls
  (kept for `POLL_HISTORY_DAYS`, default 14)
- `shop-notify history` shows the events of a period or of one listing, and
  the polls (`--polls`)
- Items that come back after being gone are notified as *back in the shop*,
  with their previous price and when they were last seen; `NOTIFY_BACK=false`
  only records them
- Template variable `item.back` and filter `ago`

### Changed
- Listings are no longer deleted from the database when they are gone. The
  database is upgraded automatically on the first start; a backup copy
  `<DB_PATH>.bak-v0` is kept
- An incomplete answer from Etsy is logged as info; a warning follows if it
  lasts longer than an hour, and after `FORGET_AFTER_HOURS` it is processed
  anyway

## [1.0.2] - 2026-10-21

### Fixed
- An item that was briefly missing from Etsy's response (gaps in Etsy's
  listing index, or items moving between pages while paginating) was
  forgotten and notified again as new. Notified items are now only
  forgotten after they have been gone for `FORGET_AFTER_HOURS` (default 24),
  and never after an incomplete response.
- Notifications show when the item went online instead of when it was last
  modified

### Added
- `FORGET_AFTER_HOURS` setting; forgotten items are logged

## [1.0.1] - 2026-10-21

### Added
- Published on [PyPI](https://pypi.org/project/shop-notify/):
  `uv tool install shop-notify` or `pipx install shop-notify`, with trusted
  publishing and signed attestations
- Package metadata (project links, classifiers, keywords)

### Changed
- README links and images are absolute, so they also work on PyPI

## [1.0.0] - 2026-10-21

First stable release: verified against the real Etsy API – a new listing in a
live shop was notified exactly once.

### Added
- Releases include the signed build provenance as in-toto JSON lines
  (`*.intoto.jsonl`) for `slsa-verifier`
- Documentation of the architecture, the security model (threat model and
  assurance case), governance and the vulnerability handling process;
  Code of Conduct
- End-to-end test of the Docker image in CI

### Fixed
- The build provenance of releases no longer lists `dist/.gitignore` as subject

## [1.0.0-rc.4] - 2026-10-21

### Security
- Fixed vulnerabilities in the Docker image: pip, which is not needed at
  runtime, was removed together with its outdated vendored libraries –
  certifi (GHSA-6q48-6c7w-9gw2, critical), urllib3 (CVE-2026-97687,
  CVE-2026-97689, CVE-2026-97688), msgpack (GHSA-6v7p-g79w-8964) and
  setuptools (CVE-2025-47273, CVE-2026-59890). The application's own
  dependencies were not affected.
- The Docker image is scanned for vulnerabilities (Trivy) on every build and
  weekly; critical and high findings fail the build, medium ones are reported
- Base images are pinned by digest
- Secret scanning with gitleaks in pre-commit and CI, with rules for
  passwords and bot tokens in notification URLs
- Release tags can only be created by maintainers, must be signed and must
  point to a commit on `main`; published releases are immutable

### Added
- Releases include the wheel, the source archive, a CycloneDX SBOM and the
  Sigstore bundle of the signed build provenance
- Weekly maintenance run: rebuild of `main`, scan of the released image and
  cleanup of old commit images

### Changed
- The container runs as numeric user and group `1000:1000`
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

[Unreleased]: https://github.com/spielkind/shop-notify/compare/v1.3.0...HEAD
[1.3.0]: https://github.com/spielkind/shop-notify/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/spielkind/shop-notify/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/spielkind/shop-notify/compare/v1.0.2...v1.1.0
[1.0.2]: https://github.com/spielkind/shop-notify/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/spielkind/shop-notify/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/spielkind/shop-notify/compare/v1.0.0-rc.4...v1.0.0
[1.0.0-rc.4]: https://github.com/spielkind/shop-notify/compare/v1.0.0-rc.3...v1.0.0-rc.4
[1.0.0-rc.3]: https://github.com/spielkind/shop-notify/compare/v1.0.0-rc.2...v1.0.0-rc.3
[1.0.0-rc.2]: https://github.com/spielkind/shop-notify/compare/v1.0.0-rc.1...v1.0.0-rc.2
[1.0.0-rc.1]: https://github.com/spielkind/shop-notify/releases/tag/v1.0.0-rc.1
