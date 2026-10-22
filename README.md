<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/spielkind/shop-notify/main/docs/banner-dark.svg">
  <img alt="Shop Notify – get notified when new items appear in a shop" src="https://raw.githubusercontent.com/spielkind/shop-notify/main/docs/banner-light.svg">
</picture>

# Shop Notify

[![CI](https://github.com/spielkind/shop-notify/actions/workflows/ci.yml/badge.svg)](https://github.com/spielkind/shop-notify/actions/workflows/ci.yml)
[![Docker](https://github.com/spielkind/shop-notify/actions/workflows/docker.yml/badge.svg)](https://github.com/spielkind/shop-notify/actions/workflows/docker.yml)
[![Coverage](https://raw.githubusercontent.com/spielkind/shop-notify/python-coverage-comment-action-data/badge.svg)](https://github.com/spielkind/shop-notify/tree/python-coverage-comment-action-data)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/spielkind/shop-notify/badge)](https://scorecard.dev/viewer/?uri=github.com/spielkind/shop-notify)
[![PyPI](https://img.shields.io/pypi/v/shop-notify)](https://pypi.org/project/shop-notify/)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/15766/badge)](https://www.bestpractices.dev/projects/15766)

Shop Notify watches an Etsy shop and tells you – and anyone else you like – as soon as new items appear. Perfect for one-of-a-kind pieces that sell out quickly.

- **New items and items back in the shop:** every listing is reported once; if it is gone for more than a day and comes back, you hear about it – with its previous price and when it was last seen.
- **Any notification channel:** HTML e-mail with item images to as many recipients as you want, push to your phone via ntfy, Telegram, Signal and [100+ more](https://github.com/caronc/apprise/wiki) – also several at once.
- **Runs unattended:** made for a Raspberry Pi, as a Docker container or systemd service, with health check, watchdog and Etsy rate-limit handling.

## How it works

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/spielkind/shop-notify/main/docs/how-it-works-dark.svg">
  <img alt="Shop Notify polls the Etsy Open API, compares the active listings with its SQLite database and sends new items via Apprise to e-mail, push and chat services." src="https://raw.githubusercontent.com/spielkind/shop-notify/main/docs/how-it-works-light.svg">
</picture>

Every few minutes Shop Notify fetches the active listings of the shop from the [Etsy Open API v3](https://developers.etsy.com/documentation/) and compares them with the items it has already seen. Each new item is notified exactly once:

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/spielkind/shop-notify/main/docs/lifecycle-dark.svg">
  <img alt="Lifecycle of a listing: New, then Notified once sent, then Gone once it has been gone from the shop for 24 hours; if it comes back it is notified as back in the shop. Failed notifications are retried with the next poll." src="https://raw.githubusercontent.com/spielkind/shop-notify/main/docs/lifecycle-light.svg">
</picture>

### First run
When the database is empty, all items currently in the shop would be "new". Instead of flooding your phone, Shop Notify only **records** them on the first run and prints them to the console; notifications start with the next new item:

```text
First run: 87 items currently in YourShop (recorded, not notified)
…
```

Set `NOTIFY_EXISTING_ON_FIRST_RUN=true` to send them to all targets anyway. To start over, delete the database (`DB_PATH`).

### Example notification

A notification on your phone (plain text) looks like this – e-mails additionally show the item picture:

```text
2 new items in YourShop

Hand-thrown mug "Morning dew"
€24.50 · Oct 14, 2026, 19:46
https://www.etsy.com/listing/1234567890

Small vase in sage green
€18.00 · Oct 14, 2026, 20:46
https://www.etsy.com/listing/1234567891
```

## Quick start

1. **Get an Etsy API key** – see [Creating an Etsy app](https://github.com/spielkind/shop-notify/blob/main/docs/etsy-app.md). You need the *keystring* and the *shared secret*.
2. **Configure:** download [`compose.yaml`](https://github.com/spielkind/shop-notify/blob/main/compose.yaml) and [`.env.example`](https://github.com/spielkind/shop-notify/blob/main/.env.example), save the latter as `.env` and fill in your key, secret and the shop name (as in `etsy.com/shop/<name>`).
3. **Start:**

   ```sh
   mkdir -p data
   docker compose up -d
   docker compose logs -f
   ```

Without notification targets, new items are only written to the log – a good first test. Then [set up notifications](https://github.com/spielkind/shop-notify/blob/main/docs/notifications.md).

## Configuration

All settings are read from `.env` in the working directory or from environment variables (which take precedence).

| Variable | Default | Description |
|---|---|---|
| `ETSY_API_KEY` | *required* | Keystring of your Etsy app |
| `ETSY_SHARED_SECRET` | *required* | Shared secret of your Etsy app |
| `ETSY_SHOP_NAME` | – | Shop to watch, as in `etsy.com/shop/<name>`; the ID is looked up at startup |
| `ETSY_SHOP_ID` | – | Numeric shop ID, alternative to `ETSY_SHOP_NAME` |
| `POLL_INTERVAL` | `300` | Seconds between two polls (minimum 10), see [below](#choosing-the-poll-interval) |
| `FORGET_AFTER_HOURS` | `24` | An item counts as gone once it has been missing from the shop this long; if it comes back later, it is notified as back in the shop. Shorter gaps – Etsy's listing index is occasionally incomplete – don't cause a notification |
| `NOTIFY_BACK` | `true` | Notify items that are back in the shop; with `false` they are only recorded in the history |
| `POLL_HISTORY_DAYS` | `14` | Days the poll log is kept (`shop-notify history --polls`); the listing history is kept forever |
| `NOTIFY_CONFIG` | – | Path to an Apprise YAML file with notification targets |
| `NOTIFY_URLS` | – | One or more Apprise URLs, short form for simple setups |
| `NOTIFY_CONSOLE` | `auto` | Print notifications to stdout: `auto` only if no other targets are configured (plus the [first run](#first-run)), `true` always (in addition to them), `false` never |
| `NOTIFY_EXISTING_ON_FIRST_RUN` | `false` | Send the items already in the shop on the [first run](#first-run) to all targets |
| `NOTIFY_LANGUAGE` | `en` | Language of the built-in messages: `en` or `de` |
| `NOTIFY_IMAGES` | `true` | Push/chat services get one message per new item with its picture |
| `NOTIFY_IMAGES_MAX` | `5` | Up to this many new items per poll are sent individually; above, one summary message |
| `NOTIFY_IMAGES_IN_SUMMARY` | `false` | Attach up to 10 pictures to the summary message (a Telegram album with `?album=yes`) |
| `NOTIFY_TEMPLATE_DIR` | – | Directory with [custom message templates](https://github.com/spielkind/shop-notify/blob/main/docs/notifications.md#message-templates) |
| `DB_PATH` | `shop-notify.db` | SQLite database of seen items |
| `HEARTBEAT_FILE` | next to `DB_PATH` | Touched after every successful poll, used by the [health check](#health-check) |
| `LOG_FILE` | `shop-notify.log` | Log file; empty to log to stdout only |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, … |
| `ETSY_API_ENDPOINT` | Etsy Open API v3 | Only needed for testing |
| `TZ` | UTC | Docker only: time zone for dates in notifications and logs, e.g. `Europe/Berlin` (locally and with systemd the system time zone is used) |

Only listing ID, title, URL, price and modification time are stored locally; vanished listings are deleted once they were notified.

### Choosing the poll interval
A new Etsy app may make **5,000 requests per day**. Every poll needs one request per 100 active listings, so stay above *35 s × pages* to use at most half of the quota:

| Active listings | Requests per poll | Recommended `POLL_INTERVAL` |
|---|---|---|
| up to 100 | 1 | ≥ 35 s |
| up to 200 | 2 | ≥ 70 s |
| up to 500 | 5 | ≥ 3 min |

The default of 5 minutes needs fewer than 300 requests per day for a typical shop. Shop Notify logs a warning when less than 20 % of the daily quota is left, and waits as long as Etsy asks when it answers `429 Too Many Requests`.

### Notifications
Notifications are sent with [Apprise](https://github.com/caronc/apprise) – e-mail, ntfy, Telegram, Signal and [100+ more](https://github.com/caronc/apprise/wiki). Copy [`notify.example.yml`](https://github.com/spielkind/shop-notify/blob/main/notify.example.yml) to `notify.yml`, adjust it and set `NOTIFY_CONFIG=notify.yml`:

```yaml
version: 1
urls:
  # One e-mail to several people who don't see each other's address
  - mailtos://you:app-password@gmail.com:
      - bcc: alice@example.com, bob@example.com
  # Push notification to your phone
  - ntfys://ntfy.sh/your-long-random-topic
```

E-mail gets one HTML message with all new items; push and chat services get one message per item with its picture. Try your setup with `shop-notify test-notify` – no Etsy key needed.

**→ [Notifications in detail](https://github.com/spielkind/shop-notify/blob/main/docs/notifications.md):** setting up Gmail, ntfy and Telegram, pictures and summaries, testing, custom templates and languages.

## Creating an Etsy app
Shop Notify only reads public listings, so it needs an API key (keystring and shared secret) but no OAuth login. New apps start as *Pending Personal Approval*; until they are **Active**, every request fails with `403`. **→ [Step-by-step registration](https://github.com/spielkind/shop-notify/blob/main/docs/etsy-app.md)**

## Running

### Docker
Images for `linux/amd64` and `linux/arm64` (Raspberry Pi with a 64-bit OS) are published as `ghcr.io/spielkind/shop-notify` (`latest` = newest release). With [`compose.yaml`](https://github.com/spielkind/shop-notify/blob/main/compose.yaml) and your `.env`:

```sh
mkdir -p data
docker compose pull
docker compose up -d
docker compose logs -f
```

To use `notify.yml`, uncomment its volume in `compose.yaml` and set `NOTIFY_CONFIG=/config/notify.yml`; set `TZ=Europe/Berlin` (or your time zone) as the container runs in UTC otherwise. **→ [Docker in detail](https://github.com/spielkind/shop-notify/blob/main/docs/docker.md):** image tags, updates, moving an existing database, verifying the image, troubleshooting.

### systemd
Alternatively install it as a sandboxed systemd service, e.g. on Raspberry Pi OS; `systemctl status` then shows the result of the last poll. **→ [systemd setup](https://github.com/spielkind/shop-notify/blob/main/docs/systemd.md)**

### Locally
Install it from [PyPI](https://pypi.org/project/shop-notify/) with [uv](https://docs.astral.sh/uv/) (it downloads Python 3.14+ if needed) or [pipx](https://pipx.pypa.io/):

```sh
uv tool install shop-notify    # or: pipx install shop-notify
# create .env in the current directory (see .env.example) and fill it in
shop-notify
```

Update with `uv tool upgrade shop-notify`. To run it from a clone of the repository instead: `uv sync`, then `uv run shop-notify`.

Stop it with `Ctrl+C`.

### History
Shop Notify keeps a history of every listing – when it appeared, was notified, went missing, was gone or came back, and price and title changes – and a log of the polls of the last 14 days:

```sh
shop-notify history                      # events of the last 7 days
shop-notify history 1550875589           # everything about one listing
shop-notify history --since 2w           # a longer period (m, h, d, w)
shop-notify history --polls --since 1d   # the polls, e.g. incomplete answers from Etsy
docker compose exec shop-notify shop-notify history   # in Docker
```

```text
2026-10-21 09:07   1550875589  new            Mermaid Dreams- 5 x 7 Mini Art Print  (price: 24.99 USD, created: 2023-08-23 19:26, …)
2026-10-23 14:00   1550875589  price_changed  Mermaid Dreams- 5 x 7 Mini Art Print  (old: 24.99 USD, new: 19.99 USD)
```

Nothing before the first run is known (Etsy has no history), and changes are only noticed at the next poll. The database layout is described in [docs/architecture.md](https://github.com/spielkind/shop-notify/blob/main/docs/architecture.md#database).

### Health check
After every successful poll Shop Notify touches a heartbeat file. `shop-notify healthcheck` exits with `0` if the last successful poll is younger than `2 × POLL_INTERVAL + 60 s`, otherwise with `1` – e.g. when Etsy rejects the API key or the network is down. Docker uses it for its health status; manually:

```sh
shop-notify healthcheck                              # local
docker compose exec shop-notify shop-notify healthcheck   # Docker
```

## FAQ

<details>
<summary>Why not simply use an RSS feed?</summary>

Etsy doesn't provide an official, reliable feed of new shop listings. The Open API is the supported way to read them.
</details>

<details>
<summary>Every request fails with <code>403 API key not found or not active</code></summary>

Your Etsy app is still *Pending Personal Approval*, or keystring and shared secret are mixed up. Check the status under <https://www.etsy.com/developers/your-apps>.
</details>

<details>
<summary>I received the same item twice</summary>

That's intended if the item was gone from the shop in between (sold, deactivated, renewed) – re-appeared items are reported again. It also happens if all notification targets failed: then the items are retried with the next poll.
</details>

<details>
<summary>Can I watch several shops?</summary>

Not yet with a single instance ([planned](https://github.com/spielkind/shop-notify/issues/7)) – run one instance per shop with its own `.env` and `DB_PATH`. Keep the shared API quota in mind.
</details>

<details>
<summary>Why didn't I get notified about the items already in the shop?</summary>

On the [first run](#first-run) existing items are only recorded, so you are not flooded with notifications. Set `NOTIFY_EXISTING_ON_FIRST_RUN=true` and delete the database to receive them once.
</details>

## Development

```sh
uv sync
uv run pre-commit install
uv run pytest
```

See [CONTRIBUTING.md](https://github.com/spielkind/shop-notify/blob/main/CONTRIBUTING.md) for the development workflow, pull requests and releases. Planned features are on the [roadmap](https://github.com/spielkind/shop-notify/issues?q=is%3Aopen+label%3Aroadmap); security issues please report as described in [SECURITY.md](https://github.com/spielkind/shop-notify/blob/main/SECURITY.md).

- [Architecture](https://github.com/spielkind/shop-notify/blob/main/docs/architecture.md) and [security model](https://github.com/spielkind/shop-notify/blob/main/docs/security.md)
- [Governance](https://github.com/spielkind/shop-notify/blob/main/GOVERNANCE.md) and [Code of Conduct](https://github.com/spielkind/shop-notify/blob/main/CODE_OF_CONDUCT.md)

## License and disclaimer
[MIT](https://github.com/spielkind/shop-notify/blob/main/LICENSE).

The term "Etsy" is a trademark of Etsy, Inc. This application uses the Etsy API but is not endorsed or certified by Etsy, Inc.
