<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/banner-dark.svg">
  <img alt="Shop Notify – get notified when new items appear in a shop" src="docs/banner-light.svg">
</picture>

# etsy-notify

[![CI](https://github.com/spielkind/etsy-notify/actions/workflows/ci.yml/badge.svg)](https://github.com/spielkind/etsy-notify/actions/workflows/ci.yml)
[![Coverage](https://raw.githubusercontent.com/spielkind/etsy-notify/python-coverage-comment-action-data/badge.svg)](https://github.com/spielkind/etsy-notify/tree/python-coverage-comment-action-data)

This is a tool that is meant to watch Etsy shop listings for significant changes and notify interested parties.

It does that by polling the [Etsy Open API v3](https://developers.etsy.com/documentation/), analyzing the response and identifying any items that are new in the shop, either brand-new ones or any that have re-appeared. A notification is sent for all new items.

It is meant to run unattended on a small device like a Raspberry Pi.

*Note:* Currently only a single shop can be watched, and only GMail can be used for email notifications.

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
- `NOTIFIER`: `console` (default, for testing) or `gmail`.
- For `gmail`: `GMAIL_USER`, `GMAIL_PASSWORD` (a [Google App Password](https://support.google.com/accounts/answer/185833), requires 2FA), `MAIL_FROM` and `MAIL_TO` (comma-separated list).

Optional: `POLL_INTERVAL` (seconds, default 60; for a small shop 5–15 minutes is usually plenty), `DB_PATH`, `LOG_FILE` (empty to log to stdout only), `LOG_LEVEL`, `HEARTBEAT_FILE` (default: next to the database).

Only listing ID, title, URL and modification time are stored locally; entries of listings that have vanished are removed after they were notified. If Etsy responds with `429 Too Many Requests`, the tool waits as long as the `retry-after` header asks before retrying.

All settings can also be passed as environment variables.

## Running

    uv run etsy-notify

Stop it with `Ctrl+C` or `SIGTERM`.

### Health check
After every successful poll the tool touches a heartbeat file. To check whether it is still working:

    uv run etsy-notify healthcheck

It exits with `0` if the last successful poll is younger than `2 × POLL_INTERVAL + 60 s`, otherwise with `1` (e.g. when Etsy rejects the API key or the network is down). It reads the same configuration as the main command.

## Running with Docker
The image works on `linux/amd64` and `linux/arm64` (Raspberry Pi with a 64-bit OS, Apple Silicon). With your `.env` in place:

    mkdir -p data
    docker compose up -d --build

- The database and heartbeat file live in `./data` (mounted to `/data`). The container runs as UID 1000, so `data/` must be writable for that user – on a Raspberry Pi the default user `pi` already has UID 1000.
- Logs go to stdout: `docker compose logs -f`
- `docker compose ps` shows the health status (`healthy`/`unhealthy`) from `etsy-notify healthcheck`. Docker does not restart unhealthy containers by itself; a crashed process is restarted thanks to `restart: unless-stopped`.
- Update: `git pull && docker compose up -d --build`

Without Compose:

    docker build -t etsy-notify .
    docker run -d --name etsy-notify --restart unless-stopped \
      --env-file .env -v "$PWD/data:/data" etsy-notify

## Running as a systemd service
Alternative to Docker, e.g. on Raspberry Pi OS. The service runs as its own system user from `/opt/etsy-notify`, logs to the journal and is sandboxed (see [`contrib/systemd/etsy-notify.service`](contrib/systemd/etsy-notify.service)).

1. Create the user and check out the code:

       sudo useradd --system --home-dir /var/lib/etsy-notify --shell /usr/sbin/nologin etsy-notify
       sudo git clone https://github.com/spielkind/etsy-notify.git /opt/etsy-notify
       cd /opt/etsy-notify

2. Install the dependencies. `UV_PYTHON_INSTALL_DIR` makes uv put a downloaded Python under `/opt` instead of your home directory, which the sandboxed service could not read:

       sudo env "PATH=$PATH" UV_PYTHON_INSTALL_DIR=/opt/etsy-notify/.python uv sync --locked --no-dev

3. Create the configuration (only root can write it, the service can read it):

       sudo cp .env.example .env
       sudo nano .env
       sudo chown root:etsy-notify .env
       sudo chmod 640 .env

   `DB_PATH` and `LOG_FILE` are set by the unit (`/var/lib/etsy-notify/etsy.db`, journal only).

4. Install and start the service:

       sudo cp contrib/systemd/etsy-notify.service /etc/systemd/system/
       sudo systemctl daemon-reload
       sudo systemctl enable --now etsy-notify

Useful commands:

    systemctl status etsy-notify
    journalctl -u etsy-notify -f
    cd /opt/etsy-notify && sudo -u etsy-notify env DB_PATH=/var/lib/etsy-notify/etsy.db \
      .venv/bin/etsy-notify healthcheck

Update:

    cd /opt/etsy-notify
    sudo git pull
    sudo env "PATH=$PATH" UV_PYTHON_INSTALL_DIR=/opt/etsy-notify/.python uv sync --locked --no-dev
    sudo systemctl restart etsy-notify

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
