<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/banner-dark.svg">
  <img alt="Shop Notify – get notified when new items appear in a shop" src="docs/banner-light.svg">
</picture>

# Shop Notify

[![CI](https://github.com/spielkind/shop-notify/actions/workflows/ci.yml/badge.svg)](https://github.com/spielkind/shop-notify/actions/workflows/ci.yml)
[![Coverage](https://raw.githubusercontent.com/spielkind/shop-notify/python-coverage-comment-action-data/badge.svg)](https://github.com/spielkind/shop-notify/tree/python-coverage-comment-action-data)

Shop Notify watches the listings of an Etsy shop and notifies interested parties about new items.

It does that by polling the [Etsy Open API v3](https://developers.etsy.com/documentation/), analyzing the response and identifying any items that are new in the shop, either brand-new ones or any that have re-appeared. A notification is sent for all new items.

It is meant to run unattended on a small device like a Raspberry Pi.

*Note:* Currently only a single shop can be watched.

## Prerequisites
This tool requires Python 3.14+ and uses [uv](https://docs.astral.sh/uv/) for dependency management. Install uv with:

    curl -LsSf https://astral.sh/uv/install.sh | sh

uv will automatically download a matching Python version if needed. Install all dependencies with:

    uv sync

## Creating an Etsy app
The tool only reads public listings, so it needs an API key but no OAuth login.

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
4. New apps start as *Pending Personal Approval*. Until the status changes to **Active**, every request fails with `403 API key not found or not active`. Approval can take from a few hours to several days.

## Configuration
Copy `.env.example` to `.env` and fill in your values:

- `ETSY_API_KEY` / `ETSY_SHARED_SECRET`: keystring and shared secret from the step above.
- `ETSY_SHOP_NAME`: name of the shop to watch, as in `etsy.com/shop/<name>`. The numeric ID is looked up at startup. Alternatively set `ETSY_SHOP_ID` directly.
- `NOTIFY_CONFIG` / `NOTIFY_URLS`: where to send notifications, see below. Without either, new items are only printed to the console (handy for a first test).

Optional: `POLL_INTERVAL` (seconds, default 300), `DB_PATH`, `LOG_FILE` (empty to log to stdout only), `LOG_LEVEL`, `HEARTBEAT_FILE` (default: next to the database).

**Choosing `POLL_INTERVAL`:** a new Etsy app may make 5,000 requests per day. Every poll needs one request per 100 active listings, so stay above *35 s × pages* to use at most half of the quota (e.g. ≥ 35 s for up to 100 listings, ≥ 70 s for up to 200). The default of 5 minutes needs fewer than 300 requests per day for a typical shop. The tool logs a warning when less than 20 % of the daily quota is left.

Only listing ID, title, URL, price and modification time are stored locally; entries of listings that have vanished are removed after they were notified. If Etsy responds with `429 Too Many Requests`, the tool waits as long as the `retry-after` header asks before retrying.

All settings can also be passed as environment variables.

### Notifications
Notifications are sent with [Apprise](https://github.com/caronc/apprise), so e-mail, [ntfy](https://ntfy.sh), Telegram, Signal, Discord, Pushover and [many more](https://github.com/caronc/apprise/wiki) are supported – also several at once.

For more than one target, use a config file. Copy [`notify.example.yml`](notify.example.yml) to `notify.yml`, adjust it and set `NOTIFY_CONFIG=notify.yml`:

```yaml
version: 1
urls:
  # One e-mail to several people who don't see each other's address
  - mailtos://you:app-password@gmail.com:
      - bcc: alice@example.com, bob@example.com
  # Push notification to your phone
  - ntfys://ntfy.sh/your-long-random-topic
```

For a single target, `NOTIFY_URLS` in `.env` is enough, e.g. `NOTIFY_URLS="ntfys://ntfy.sh/your-long-random-topic"`. Both can be combined.

- **E-mail** recipients don't need to do anything. With Gmail you need a [Google App Password](https://support.google.com/accounts/answer/185833) (requires 2FA); Gmail allows about 500 recipients per day.
- **ntfy** needs no account: install the app and subscribe to a long, random topic name – everyone who knows the name can read it.
- The configuration is checked at startup; credentials are masked in the log.
- If all targets fail, the items are not marked as notified and are sent again with the next poll. If only some fail, a warning is logged.
- `notify.yml` and `.env` contain passwords – both are ignored by git and never copied into the Docker image.

#### Message templates
E-mails are sent as HTML with the item's main image, title, price and date; all other services get a compact plain-text version (title, price, date, link per item).

To customise them, copy any of the [built-in templates](src/shop_notify/templates/) (`subject.txt.j2`, `body.txt.j2`, `body.html.j2`) into a directory and set `NOTIFY_TEMPLATE_DIR` to it – files you don't copy keep their default. Templates use [Jinja2](https://jinja.palletsprojects.com/templates/); the variables are `listings` (with `title`, `url`, `price`, `image_url`, `last_modified`) and `shop_name`, and the `localtime` filter formats a date. Values are HTML-escaped automatically in `*.html.j2`.

## Running

    uv run shop-notify

Stop it with `Ctrl+C` or `SIGTERM`.

### Health check
After every successful poll the tool touches a heartbeat file. To check whether it is still working:

    uv run shop-notify healthcheck

It exits with `0` if the last successful poll is younger than `2 × POLL_INTERVAL + 60 s`, otherwise with `1` (e.g. when Etsy rejects the API key or the network is down). It reads the same configuration as the main command.

## Running with Docker
Images for `linux/amd64` and `linux/arm64` (Raspberry Pi with a 64-bit OS, Apple Silicon) are published to the GitHub Container Registry as `ghcr.io/spielkind/shop-notify`:

| Tag | Content |
|---|---|
| `latest`, `main` | current state of the `main` branch |
| `X.Y.Z`, `X.Y` | releases (git tags `vX.Y.Z`) |
| `sha-<commit>` | a specific commit |

With your `.env` in place (only `compose.yaml` and `.env` are needed, no checkout):

    mkdir -p data
    docker compose pull
    docker compose up -d

To use a notification config file, uncomment the `notify.yml` volume in `compose.yaml` and set `NOTIFY_CONFIG=/config/notify.yml` in `.env`.

- The database and heartbeat file live in `./data` (mounted to `/data`). The container runs as UID 1000, so `data/` must be writable for that user – on a Raspberry Pi the default user `pi` already has UID 1000.
- Logs go to stdout: `docker compose logs -f`
- `docker compose ps` shows the health status (`healthy`/`unhealthy`) from `shop-notify healthcheck`. Docker does not restart unhealthy containers by itself; a crashed process is restarted thanks to `restart: unless-stopped`.
- Update: `docker compose pull && docker compose up -d`
- Build locally instead of pulling: `docker compose up -d --build`

Without Compose:

    docker run -d --name shop-notify --restart unless-stopped \
      --env-file .env -v "$PWD/data:/data" ghcr.io/spielkind/shop-notify:latest

Every published image carries a signed build provenance attestation and an SBOM. Verify that an image was built by this repository's workflow:

    gh attestation verify --owner spielkind oci://ghcr.io/spielkind/shop-notify:latest

## Running as a systemd service
Alternative to Docker, e.g. on Raspberry Pi OS. The service runs as its own system user from `/opt/shop-notify`, logs to the journal and is sandboxed (see [`contrib/systemd/shop-notify.service`](contrib/systemd/shop-notify.service)).

1. Create the user and check out the code:

       sudo useradd --system --home-dir /var/lib/shop-notify --shell /usr/sbin/nologin shop-notify
       sudo git clone https://github.com/spielkind/shop-notify.git /opt/shop-notify
       cd /opt/shop-notify

2. Install the dependencies. `UV_PYTHON_INSTALL_DIR` makes uv put a downloaded Python under `/opt` instead of your home directory, which the sandboxed service could not read:

       sudo env "PATH=$PATH" UV_PYTHON_INSTALL_DIR=/opt/shop-notify/.python uv sync --locked --no-dev

3. Create the configuration (only root can write it, the service can read it):

       sudo cp .env.example .env
       sudo nano .env
       sudo cp notify.example.yml notify.yml   # optional, set NOTIFY_CONFIG=notify.yml
       sudo nano notify.yml
       sudo chown root:shop-notify .env notify.yml
       sudo chmod 640 .env notify.yml

   `DB_PATH` and `LOG_FILE` are set by the unit (`/var/lib/shop-notify/shop-notify.db`, journal only).

4. Install and start the service:

       sudo cp contrib/systemd/shop-notify.service /etc/systemd/system/
       sudo systemctl daemon-reload
       sudo systemctl enable --now shop-notify

Useful commands:

    systemctl status shop-notify
    journalctl -u shop-notify -f
    cd /opt/shop-notify && sudo -u shop-notify env DB_PATH=/var/lib/shop-notify/shop-notify.db \
      .venv/bin/shop-notify healthcheck

The unit uses `Type=notify`: systemd only reports the service as started once the shop was found, shows the result of the last poll in `systemctl status` and restarts the process if it hangs (watchdog). For example:

    ● shop-notify.service - Shop listing notifier (shop-notify)
         Active: active (running) since …
         Status: "Last poll 14:05: 0 new item(s), 4711/5000 API requests left today"

Etsy being unreachable or rejecting the key does *not* trigger a restart – that would not help; check the status line or the journal instead.

Update:

    cd /opt/shop-notify
    sudo git pull
    sudo env "PATH=$PATH" UV_PYTHON_INSTALL_DIR=/opt/shop-notify/.python uv sync --locked --no-dev
    sudo systemctl restart shop-notify

## Development

Install the git hooks once; they run ruff, mypy, actionlint and some basic file checks on every commit:

    uv run pre-commit install

Run the checks manually:

    uv run ruff format
    uv run ruff check
    uv run mypy src tests
    uv run pytest          # includes coverage, fails below 90 %

CI additionally tests against all supported Python versions, audits the locked dependencies with `pip-audit`, and posts a coverage report on pull requests.

## Bugs
Very probably.

## Disclaimer
The term "Etsy" is a trademark of Etsy, Inc. This application uses the Etsy API but is not endorsed or certified by Etsy, Inc.
