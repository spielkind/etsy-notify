# Running as a systemd service

Alternative to Docker, e.g. on Raspberry Pi OS. The service runs as its own system user from `/opt/shop-notify`, logs to the journal and is sandboxed (see [`contrib/systemd/shop-notify.service`](../contrib/systemd/shop-notify.service)).

## Installation

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

## Update

```sh
cd /opt/shop-notify
sudo git pull
sudo env "PATH=$PATH" UV_PYTHON_INSTALL_DIR=/opt/shop-notify/.python uv sync --locked --no-dev
sudo systemctl restart shop-notify
```


## Status and logs

The unit uses `Type=notify`, so `systemctl status shop-notify` shows the result of the last poll, and systemd restarts the process if it hangs (watchdog):

```text
● shop-notify.service - Shop listing notifier (shop-notify)
     Active: active (running) since …
     Status: "Last poll 14:05: 0 new item(s), 4711/5000 API requests left today"
```

Logs: `journalctl -u shop-notify -f`. Etsy being unreachable or rejecting the key does *not* trigger a restart – check the status line instead.
