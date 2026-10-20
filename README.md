# etsy-notify

This is a tool that is meant to watch Etsy shop listings for significant changes and notify interested parties.

It does that by polling the [Etsy Open API v3](https://developers.etsy.com/documentation/), analyzing the response and identifying any items that are new in the shop, either brand-new ones or any that have re-appeared. A notification is sent for all new items.

It is meant to run unattended on a small device like a Raspberry Pi.

*Note:* Currently only a single shop can be watched, and only GMail can be used for email notifications.

## Prerequisites
This tool requires Python 3.15+ and uses [uv](https://docs.astral.sh/uv/) for dependency management. Install uv with:

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

Optional: `POLL_INTERVAL` (seconds, default 60; for a small shop 5–15 minutes is usually plenty), `DB_PATH`, `LOG_FILE`, `LOG_LEVEL`.

Only listing ID, title, URL and modification time are stored locally; entries of listings that have vanished are removed after they were notified. If Etsy responds with `429 Too Many Requests`, the tool waits as long as the `retry-after` header asks before retrying.

All settings can also be passed as environment variables.

## Running

    uv run etsy-notify

Stop it with `Ctrl+C` or `SIGTERM`.

## Development

    uv run ruff format
    uv run ruff check
    uv run mypy src tests
    uv run pytest

## Bugs
Very probably.

## Disclaimer
The term "Etsy" is a trademark of Etsy, Inc. This application uses the Etsy API but is not endorsed or certified by Etsy, Inc.
