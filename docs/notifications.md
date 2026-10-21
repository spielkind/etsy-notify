# Notifications

Shop Notify sends notifications with [Apprise](https://github.com/caronc/apprise), so e-mail, [ntfy](https://ntfy.sh), Telegram, Signal, Discord, Pushover and [100+ more services](https://github.com/caronc/apprise/wiki) are supported – also several at once.

## Configuration
For more than one target, copy [`notify.example.yml`](../notify.example.yml) to `notify.yml`, adjust it and set `NOTIFY_CONFIG=notify.yml`:

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

- **E-mail** gets one HTML message with all new items and their pictures. **Push and chat services** that support attachments (ntfy, Telegram, Signal, Pushover, …) get **one message per item with its picture** – up to `NOTIFY_IMAGES_MAX` items per poll, above that one summary message. Set `NOTIFY_IMAGES_IN_SUMMARY=true` to attach the pictures to the summary as well; for Telegram add `?album=yes` to the URL to get them as one album (ntfy shows only the first picture).
- The configuration is checked at startup; credentials are masked in the log.
- If all targets fail, the items stay *new* and are sent again with the next poll. If only some fail, a warning is logged.
- `notify.yml` and `.env` contain passwords – both are ignored by git and never copied into the Docker image.

## Testing notifications
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

## Message templates
E-mails are sent as HTML with the item's main image, title, price and date; push and chat services get one message per item (`item_subject.txt.j2`, `item_body.txt.j2`) or the compact plain-text summary shown above (`subject.txt.j2`, `body.txt.j2`).

The built-in messages are available in English and German (`NOTIFY_LANGUAGE=de`); dates and prices are formatted accordingly, e.g. `Oct 14, 2026, 19:46` / `€24.50` or `14.10.2026, 19:46 Uhr` / `24,50 €`.

To customise them, copy any of the [built-in templates](../src/shop_notify/templates/) (`subject.txt.j2`, `body.txt.j2`, `body.html.j2`, `item_subject.txt.j2`, `item_body.txt.j2` from the folder of your language) into a directory and set `NOTIFY_TEMPLATE_DIR` to it – files you don't copy keep their default. Templates use [Jinja2](https://jinja.palletsprojects.com/templates/); the variables are `item` (per-item templates only), `listings` (with `title`, `url`, `price`, `image_url`, `listed` – when the item went online, `last_modified`), `shop_name`, `initial` (true for the [first run](../README.md#first-run)) and `test` (true for [test notifications](#testing-notifications)), and the filters `localtime` and `money` format dates and prices in the configured language. Values are HTML-escaped automatically in `*.html.j2`.

## Setting up common services

### E-mail via Gmail
Recipients don't need to do anything. You need a [Google App Password](https://support.google.com/accounts/answer/185833) (requires 2-step verification). Google shows it in groups of four – leave out the spaces:

```yaml
  - mailtos://yourname:abcdefghijklmnop@gmail.com:
      - bcc: alice@example.com, bob@example.com
        from: Shop Notify <yourname@gmail.com>
```

`yourname` is the part of your Gmail address before the `@`. Without `to`/`bcc` the mail goes to your own address. Gmail allows about 500 recipients per day. Recipients in `bcc` don't see each other.

### ntfy
No account needed: install the [ntfy app](https://ntfy.sh) (Android/iOS) or open <https://ntfy.sh/app> and subscribe to a long, random topic name – everyone who knows the name can read it.

```yaml
  - ntfys://ntfy.sh/shopwatch-k7f3q9x2
```

### Telegram
1. Talk to [@BotFather](https://t.me/BotFather), send `/newbot` and pick a name; you get a **bot token** like `123456789:AAH…` (the number before the colon is the bot's ID and part of the token).
2. Open your bot (`https://t.me/<bot username>`), press **Start** and send any message.
3. Find your **chat ID**: open `https://api.telegram.org/bot<TOKEN>/getUpdates` and look for `"chat":{"id": …}` – or ask [@userinfobot](https://t.me/userinfobot). Group IDs are negative; add the bot to the group first. The `id` in `getMe` is the bot itself, not your chat.

```yaml
  - tgram://123456789:AAH-your-bot-token/987654321
  # several pictures as one album (NOTIFY_IMAGES_IN_SUMMARY):
  # - tgram://123456789:AAH-your-bot-token/987654321?album=yes
```

If `getUpdates` returns an empty `result`, the bot hasn't received a message in the last 24 hours – send another one and reload.

### WhatsApp
Apprise supports WhatsApp only through Meta's WhatsApp Business Cloud API: it needs a Meta developer account, a separate sender number and – for messages outside a 24-hour window – pre-approved message templates, which may cost money. For personal notifications e-mail, Telegram, Signal or ntfy are much simpler.
