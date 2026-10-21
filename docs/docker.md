# Running with Docker
Images for `linux/amd64` and `linux/arm64` (Raspberry Pi with a 64-bit OS, Apple Silicon) are published as `ghcr.io/spielkind/shop-notify`:

| Tag | Content |
|---|---|
| `latest` | newest release (including release candidates) |
| `X.Y.Z`, `X.Y` | a specific release, e.g. `1.0.0-rc.1` (release candidates have no `X.Y` tag) |
| `main` | current development state of the `main` branch |
| `sha-<commit>` | a specific commit |

With [`compose.yaml`](../compose.yaml) and your `.env` (no checkout needed):

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

## Without Compose

```sh
docker run -d --name shop-notify --restart unless-stopped \
  --env-file .env -v "$PWD/data:/data" ghcr.io/spielkind/shop-notify:latest
```

## Verifying the image

Every published image carries a signed build provenance attestation and an SBOM. Verify that an image was built by this repository's workflow:

```sh
gh attestation verify --owner spielkind oci://ghcr.io/spielkind/shop-notify:latest
```


## Moving an existing installation

To keep the items that were already seen (and skip the [first run](../README.md#first-run)), copy the database into `data/` before starting:

```sh
scp shop-notify.db server:~/shop-notify/data/
ssh server 'sudo chown -R 1000:1000 ~/shop-notify/data'
```

Only run **one** instance per shop – two instances send every notification twice and share the API quota.

## Troubleshooting

| Problem | Solution |
|---|---|
| `permission denied while trying to connect to the docker API` | add your user to the `docker` group (`sudo usermod -aG docker $USER`) and log in again |
| `Permission denied` on `/data` | `sudo chown -R 1000:1000 data` |
| `notification config /config/notify.yml does not exist` | uncomment the `notify.yml` volume in `compose.yaml`; the file must exist before `docker compose up` |
| dates in UTC | set `TZ` in `.env`; check with `docker compose exec shop-notify date` |
| using a remote engine via `DOCKER_HOST=ssh://…` | bind mounts (`./data`, `./notify.yml`) refer to paths **on the remote host** – copy the files there and run Compose on that host |
