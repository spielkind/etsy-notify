<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/banner-dark.svg">
  <img alt="Shop Notify – get notified when new items appear in a shop" src="docs/banner-light.svg">
</picture>

# Shop Notify

[![CI](https://github.com/spielkind/shop-notify/actions/workflows/ci.yml/badge.svg)](https://github.com/spielkind/shop-notify/actions/workflows/ci.yml)
[![Docker](https://github.com/spielkind/shop-notify/actions/workflows/docker.yml/badge.svg)](https://github.com/spielkind/shop-notify/actions/workflows/docker.yml)
[![Coverage](https://raw.githubusercontent.com/spielkind/shop-notify/python-coverage-comment-action-data/badge.svg)](https://github.com/spielkind/shop-notify/tree/python-coverage-comment-action-data)

Shop Notify watches an Etsy shop and tells you – and anyone else you like – as soon as new items appear. Perfect for one-of-a-kind pieces that sell out quickly.

- **New and re-appeared items:** every listing is reported once; if it disappears and comes back later, you hear about it again.
- **Any notification channel:** HTML e-mail with item images to as many recipients as you want, push to your phone via ntfy, Telegram, Signal and [100+ more](https://github.com/caronc/apprise/wiki) – also several at once.
- **Runs unattended:** made for a Raspberry Pi, as a Docker container or systemd service, with health check, watchdog and Etsy rate-limit handling.

## How it works

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/how-it-works-dark.svg">
  <img alt="Shop Notify polls the Etsy Open API, compares the active listings with its SQLite database and sends new items via Apprise to e-mail, push and chat services." src="docs/how-it-works-light.svg">
</picture>

Every few minutes Shop Notify fetches the active listings of the shop from the [Etsy Open API v3](https://developers.etsy.com/documentation/) and compares them with the items it has already seen. Each new item is notified exactly once:

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/lifecycle-dark.svg">
  <img alt="Lifecycle of a listing: New, then Notified once sent, then Forgotten when it disappears from the shop; if it re-appears it is New again. Failed notifications are retried with the next poll." src="docs/lifecycle-light.svg">
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

1. **Get an Etsy API key** – see [Creating an Etsy app](#creating-an-etsy-app). You need the *keystring* and the *shared secret*.
2. **Configure:** download [`compose.yaml`](compose.yaml) and [`.env.example`](.env.example), save the latter as `.env` and fill in your key, secret and the shop name (as in `etsy.com/shop/<name>`).
3. **Start:**

   ```sh
   mkdir -p data
   docker compose up -d
   docker compose logs -f
   ```

Without notification targets, new items are only written to the log – a good first test. Then [set up notifications](#notifications).

## Configuration

All settings are read from `.env` in the working directory or from environment variables (which take precedence).

| Variable | Default | Description |
|---|---|---|
| `ETSY_API_KEY` | *required* | Keystring of your Etsy app |
| `ETSY_SHARED_SECRET` | *required* | Shared secret of your Etsy app |
| `ETSY_SHOP_NAME` | – | Shop to watch, as in `etsy.com/shop/<name>`; the ID is looked up at startup |
| `ETSY_SHOP_ID` | – | Numeric shop ID, alternative to `ETSY_SHOP_NAME` |
| `POLL_INTERVAL` | `300` | Seconds between two polls (minimum 10), see [below](#choosing-the-poll-interval) |
| `NOTIFY_CONFIG` | – | Path to an Apprise YAML file with notification targets |
| `NOTIFY_URLS` | – | One or more Apprise URLs, short form for simple setups |
| `NOTIFY_CONSOLE` | `auto` | Print notifications to stdout: `auto` only if no other targets are configured (plus the [first run](#first-run)), `true` always (in addition to them), `false` never |
| `NOTIFY_EXISTING_ON_FIRST_RUN` | `false` | Send the items already in the shop on the [first run](#first-run) to all targets |
| `NOTIFY_LANGUAGE` | `en` | Language of the built-in messages: `en` or `de` |
| `NOTIFY_IMAGES` | `true` | Push/chat services get one message per new item with its picture |
| `NOTIFY_IMAGES_MAX` | `5` | Up to this many new items per poll are sent individually; above, one summary message |
| `NOTIFY_IMAGES_IN_SUMMARY` | `false` | Attach up to 10 pictures to the summary message (a Telegram album with `?album=yes`) |
| `NOTIFY_TEMPLATE_DIR` | – | Directory with [custom message templates](#message-templates) |
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
Notifications are sent with [Apprise](https://github.com/caronc/apprise). For more than one target, copy [`notify.example.yml`](notify.example.yml) to `notify.yml`, adjust it and set `NOTIFY_CONFIG=notify.yml`:

```yaml
version: 1
urls:
  # One e-mail to several people who don't see each other's address
  - mailtos://you:app-password@gmail.com:
      - bcc: alice@example.com, bob@example.com
  # Push notification to your phone
  - ntfys://ntfy.sh/your-long-random-topic
```

For a single target, `NOTIFY_URLS` is enough, e.g. `NOTIFY_URLS="ntfys://ntfy.sh/your-long-random-topic"`. Both can be combined.

- **E-mail** recipients don't need to do anything. With Gmail you need a [Google App Password](https://support.google.com/accounts/answer/185833) (requires 2FA); Gmail allows about 500 recipients per day.
- **ntfy** needs no account: install the app and subscribe to a long, random topic name – everyone who knows the name can read it.
- **E-mail** gets one HTML message with all new items and their pictures. **Push and chat services** that support attachments (ntfy, Telegram, Signal, Pushover, …) get **one message per item with its picture** – up to `NOTIFY_IMAGES_MAX` items per poll, above that one summary message. Set `NOTIFY_IMAGES_IN_SUMMARY=true` to attach the pictures to the summary as well; for Telegram add `?album=yes` to the URL to get them as one album (ntfy shows only the first picture).
- The configuration is checked at startup; credentials are masked in the log.
- If all targets fail, the items stay *new* and are sent again with the next poll. If only some fail, a warning is logged.
- `notify.yml` and `.env` contain passwords – both are ignored by git and never copied into the Docker image.

### Testing notifications
Send a sample notification with two example items to all configured targets – no Etsy key needed, the database is not touched:

```sh
uv run shop-notify test-notify                                   # local
docker compose run --rm shop-notify test-notify                  # Docker
cd /opt/shop-notify && sudo -u shop-notify .venv/bin/shop-notify test-notify   # systemd
```

```text
  ✓ mailtos://you:****@gmail.com/
  ✗ ntfys://ntfy.sh/your-topic

1 of 2 target(s) succeeded.
```

The subject starts with `[Test]`. Use `--url` to try a single Apprise URL before adding it to the configuration, e.g. `shop-notify test-notify --url "ntfys://ntfy.sh/your-topic"`. The exit code is `0` if all targets succeeded, `1` if any failed and `2` for configuration errors.

### Message templates
E-mails are sent as HTML with the item's main image, title, price and date; push and chat services get one message per item (`item_subject.txt.j2`, `item_body.txt.j2`) or the compact plain-text summary shown above (`subject.txt.j2`, `body.txt.j2`).

The built-in messages are available in English and German (`NOTIFY_LANGUAGE=de`); dates and prices are formatted accordingly, e.g. `Oct 14, 2026, 19:46` / `€24.50` or `14.10.2026, 19:46 Uhr` / `24,50 €`.

To customise them, copy any of the [built-in templates](src/shop_notify/templates/) (`subject.txt.j2`, `body.txt.j2`, `body.html.j2`, `item_subject.txt.j2`, `item_body.txt.j2` from the folder of your language) into a directory and set `NOTIFY_TEMPLATE_DIR` to it – files you don't copy keep their default. Templates use [Jinja2](https://jinja.palletsprojects.com/templates/); the variables are `item` (per-item templates only), `listings` (with `title`, `url`, `price`, `image_url`, `last_modified`), `shop_name`, `initial` (true for the [first run](#first-run)) and `test` (true for [test notifications](#testing-notifications)), and the filters `localtime` and `money` format dates and prices in the configured language. Values are HTML-escaped automatically in `*.html.j2`.

## Creating an Etsy app
Shop Notify only reads public listings, so it needs an API key but no OAuth login.

<details>
<summary>Step-by-step registration</summary>

1. Log in to Etsy (a regular account is enough, you don't need a shop) and enable two-factor authentication under *Settings → Security*.
2. Open <https://www.etsy.com/developers/register> and fill in the form:
   - **Name**: anything *without* the word "etsy" (it is a restricted word), e.g. `shop-watcher-yourname`.
   - **Description**: e.g. "Personal tool that polls the active listings of a single shop and emails me when new items appear. Sends notification emails only to myself via my own mail account."
   - **Website URL**: the URL of this repository is fine.
   - **Type of application**: *Buyer Tools*
   - **Users**: *Just myself or colleagues*
   - **Commercial / charge for access**: *No*
   - **Will your app do any of the following**: leave all unchecked (it neither edits listings nor reads sales data, and it does not email Etsy members).
3. Open <https://www.etsy.com/developers/your-apps> → *See API Key Details* and copy the **keystring** and the **shared secret**.

</details>

New apps start as *Pending Personal Approval*. Until the status changes to **Active**, every request fails with `403 API key not found or not active` – approval can take from a few hours to several days.

## Running

### Docker
Images for `linux/amd64` and `linux/arm64` (Raspberry Pi with a 64-bit OS, Apple Silicon) are published as `ghcr.io/spielkind/shop-notify`:

| Tag | Content |
|---|---|
| `latest` | newest release (including release candidates) |
| `X.Y.Z`, `X.Y` | a specific release, e.g. `1.0.0-rc.1` (release candidates have no `X.Y` tag) |
| `main` | current development state of the `main` branch |
| `sha-<commit>` | a specific commit |

With [`compose.yaml`](compose.yaml) and your `.env` (no checkout needed):

```sh
mkdir -p data
docker compose pull
docker compose up -d
```

- To use `notify.yml`, uncomment its volume in `compose.yaml` and set `NOTIFY_CONFIG=/config/notify.yml` in `.env`.
- Set `TZ=Europe/Berlin` (or your time zone) in `.env` – the container runs in UTC otherwise.
- Database and heartbeat live in `./data`. The container runs as UID 1000, so `data/` must be writable for that user – on a Raspberry Pi the default user already has UID 1000.
- Logs: `docker compose logs -f` · Status: `docker compose ps` shows `healthy`/`unhealthy`
- Update: `docker compose pull && docker compose up -d` · Build locally: `docker compose up -d --build`
- Docker restarts a crashed container (`restart: unless-stopped`), but not an unhealthy one.

<details>
<summary>Without Compose, and verifying the image</summary>

```sh
docker run -d --name shop-notify --restart unless-stopped \
  --env-file .env -v "$PWD/data:/data" ghcr.io/spielkind/shop-notify:latest
```

Every published image carries a signed build provenance attestation and an SBOM. Verify that an image was built by this repository's workflow:

```sh
gh attestation verify --owner spielkind oci://ghcr.io/spielkind/shop-notify:latest
```

</details>

### systemd
Alternative to Docker, e.g. on Raspberry Pi OS. The service runs as its own system user from `/opt/shop-notify`, logs to the journal and is sandboxed (see [`contrib/systemd/shop-notify.service`](contrib/systemd/shop-notify.service)).

<details>
<summary>Installation and update</summary>

1. Create the user and check out the code:

   ```sh
   sudo useradd --system --home-dir /var/lib/shop-notify --shell /usr/sbin/nologin shop-notify
   sudo git clone https://github.com/spielkind/shop-notify.git /opt/shop-notify
   cd /opt/shop-notify
   ```

2. Install the dependencies with [uv](https://docs.astral.sh/uv/). `UV_PYTHON_INSTALL_DIR` puts a downloaded Python under `/opt` instead of your home directory, which the sandboxed service could not read:

   ```sh
   sudo env "PATH=$PATH" UV_PYTHON_INSTALL_DIR=/opt/shop-notify/.python uv sync --locked --no-dev
   ```

3. Create the configuration (only root can write it, the service can read it):

   ```sh
   sudo cp .env.example .env && sudo nano .env
   sudo cp notify.example.yml notify.yml && sudo nano notify.yml   # optional
   sudo chown root:shop-notify .env notify.yml
   sudo chmod 640 .env notify.yml
   ```

   `DB_PATH` and `LOG_FILE` are set by the unit (`/var/lib/shop-notify/shop-notify.db`, journal only).

4. Install and start the service:

   ```sh
   sudo cp contrib/systemd/shop-notify.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now shop-notify
   ```

Update:

```sh
cd /opt/shop-notify
sudo git pull
sudo env "PATH=$PATH" UV_PYTHON_INSTALL_DIR=/opt/shop-notify/.python uv sync --locked --no-dev
sudo systemctl restart shop-notify
```

</details>

The unit uses `Type=notify`, so `systemctl status shop-notify` shows the result of the last poll, and systemd restarts the process if it hangs (watchdog):

```text
● shop-notify.service - Shop listing notifier (shop-notify)
     Active: active (running) since …
     Status: "Last poll 14:05: 0 new item(s), 4711/5000 API requests left today"
```

Logs: `journalctl -u shop-notify -f`. Etsy being unreachable or rejecting the key does *not* trigger a restart – check the status line instead.

### Locally
Requires [uv](https://docs.astral.sh/uv/) (it downloads Python 3.14+ if needed):

```sh
uv sync
cp .env.example .env   # and fill it in
uv run shop-notify
```

Stop it with `Ctrl+C`.

### Health check
After every successful poll Shop Notify touches a heartbeat file. `shop-notify healthcheck` exits with `0` if the last successful poll is younger than `2 × POLL_INTERVAL + 60 s`, otherwise with `1` – e.g. when Etsy rejects the API key or the network is down. Docker uses it for its health status; manually:

```sh
uv run shop-notify healthcheck                       # local
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

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow, pull requests and releases. Planned features are on the [roadmap](https://github.com/spielkind/shop-notify/issues?q=is%3Aopen+label%3Aroadmap); security issues please report as described in [SECURITY.md](SECURITY.md).

## License and disclaimer
[MIT](LICENSE).

The term "Etsy" is a trademark of Etsy, Inc. This application uses the Etsy API but is not endorsed or certified by Etsy, Inc.
