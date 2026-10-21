#!/usr/bin/env bash
# End-to-end test of the Docker image: a fake Etsy API and Mailpit (SMTP server with
# an HTTP API) stand in for the real services.
#
#   1. first run: the existing listings are recorded, no mail is sent
#   2. a new listing appears: exactly one HTML mail with title, price and image
#   3. further polls: no duplicate mail
#
# Usage: tests/e2e/run.sh [IMAGE]   (default: shop-notify:ci; needs docker, curl, python3)
set -euo pipefail

IMAGE=${1:-shop-notify:ci}
MAILPIT=axllent/mailpit:v1.31.6@sha256:23fe39e81bde596a918000b3135c0f85dc8bb4c9ea6be274b051143f3e300387
ETSY_PORT=18080
SMTP_PORT=11025
MAILPIT_API=http://localhost:18025/api/v1
DIR=$(cd "$(dirname "$0")" && pwd)

cleanup() {
  status=$?
  if ((status != 0)); then
    echo "--- shop-notify log ---"
    docker logs shop-notify-e2e 2>&1 | tail -40 || true
  fi
  docker rm -f shop-notify-e2e mailpit-e2e >/dev/null 2>&1 || true
  [[ -n "${ETSY_PID:-}" ]] && kill "$ETSY_PID" 2>/dev/null
  exit "$status"
}
trap cleanup EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

# wait_for SECONDS COMMAND… – retry until the command succeeds
wait_for() {
  local seconds=$1; shift
  for ((i = 0; i < seconds; i++)); do
    "$@" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}

mail_count() { curl -sf "$MAILPIT_API/messages" | python3 -c 'import json,sys; print(json.load(sys.stdin)["total"])'; }

python3 "$DIR/fake_etsy.py" "$ETSY_PORT" &
ETSY_PID=$!
docker run -d --name mailpit-e2e --network host "$MAILPIT" \
  --smtp 127.0.0.1:$SMTP_PORT --listen 127.0.0.1:18025 >/dev/null
wait_for 30 curl -sf "$MAILPIT_API/messages" || fail "Mailpit did not start"
wait_for 10 curl -sf "http://localhost:$ETSY_PORT/image.png" || fail "fake Etsy did not start"

MAIL_URL="mailto://localhost:$SMTP_PORT?mode=insecure&from=shop-notify@example.com&to=me@example.com" # gitleaks:allow
docker run -d --name shop-notify-e2e --network host \
  -e ETSY_API_KEY=e2e-key -e ETSY_SHARED_SECRET=e2e-secret \
  -e ETSY_API_ENDPOINT="http://localhost:$ETSY_PORT/v3/application/" \
  -e ETSY_SHOP_NAME=TestShop -e POLL_INTERVAL=10 \
  -e NOTIFY_URLS="$MAIL_URL" \
  "$IMAGE" >/dev/null

echo "1. first run is silent"
wait_for 60 sh -c 'docker logs shop-notify-e2e 2>&1 | grep -q "First run: 3 existing item"' \
  || fail "first run not logged"
sleep 3
[[ $(mail_count) == 0 ]] || fail "mail sent on the first run"

echo "2. a new listing is notified once"
curl -sf -X POST "http://localhost:$ETSY_PORT/_add" >/dev/null
wait_for 60 sh -c "[ \"\$(curl -sf $MAILPIT_API/messages | grep -o '\"total\":[0-9]*')\" = '\"total\":1' ]" \
  || fail "no mail for the new listing"
id=$(curl -sf "$MAILPIT_API/messages" | python3 -c 'import json,sys; print(json.load(sys.stdin)["messages"][0]["ID"])')
curl -sf "$MAILPIT_API/message/$id" | python3 -c '
import json, sys
m = json.load(sys.stdin)
html = m["HTML"]
print("   subject:", m["Subject"])
assert "Handmade test item 4" in m["Subject"] + html, "title missing"
assert "12.54" in html, "price missing"
assert "image.png" in html or m.get("Inline") or m.get("Attachments"), "image missing"
assert "Handmade test item 3" not in html, "old listing included"
' || fail "unexpected mail content"

echo "3. no duplicate on the next polls"
sleep 25
[[ $(mail_count) == 1 ]] || fail "duplicate mail"
docker logs shop-notify-e2e 2>&1 | grep -q "No new items this time" || fail "no further poll logged"

echo "OK"
