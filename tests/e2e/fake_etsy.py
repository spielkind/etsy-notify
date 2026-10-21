"""Minimal stand-in for the Etsy API v3 used by the end-to-end test.

GET  /v3/application/shops?shop_name=…           → the test shop
GET  /v3/application/shops/<id>/listings/active   → current listings, newest first
GET  /v3/application/listings/batch               → main image per listing
GET  /image.png                                   → sample image
POST /_add                                        → publish one more listing
POST /_hide_once                                  → leave out the oldest listing once

Run with: python fake_etsy.py PORT
"""

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SHOP_ID = 4711
SHOP_NAME = "TestShop"
IMAGE = Path(__file__).resolve().parents[2] / "docs" / "sample-item.png"

listings: list[dict[str, object]] = []
port = 0
state = {"hide_once": False}


def add_listing() -> dict[str, object]:
    number = len(listings) + 1
    listing = {
        "listing_id": 1000 + number,
        "title": f"Handmade test item {number}",
        "url": f"https://www.etsy.com/listing/{1000 + number}/test-item",
        "last_modified_timestamp": int(time.time()),
        "state_timestamp": int(time.time()),
        "price": {"amount": 1250 + number, "divisor": 100, "currency_code": "EUR"},
        "image_url": f"http://localhost:{port}/image.png",
    }
    listings.insert(0, listing)
    return listing


class Handler(BaseHTTPRequestHandler):
    def _json(self, data: object) -> None:
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path == "/image.png":
            body = IMAGE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif not self.headers.get("x-api-key"):
            self.send_error(403, "missing x-api-key")
        elif url.path == "/v3/application/shops":
            found = query.get("shop_name") == [SHOP_NAME]
            shops = [{"shop_id": SHOP_ID, "shop_name": SHOP_NAME}] if found else []
            self._json({"count": len(shops), "results": shops})
        elif url.path == f"/v3/application/shops/{SHOP_ID}/listings/active":
            # like a gap in Etsy's listing index: the listing is missing everywhere
            visible = listings[:-1] if state["hide_once"] else listings
            state["hide_once"] = False
            offset = int(query.get("offset", ["0"])[0])
            limit = int(query.get("limit", ["100"])[0])
            page = [
                {k: v for k, v in item.items() if k != "image_url"}
                for item in visible[offset : offset + limit]
            ]
            self._json({"count": len(visible), "results": page})
        elif url.path == "/v3/application/listings/batch":
            ids = {int(i) for i in query["listing_ids"][0].split(",")}
            results = [
                {
                    "listing_id": item["listing_id"],
                    "images": [{"rank": 1, "url_570xN": item["image_url"]}],
                }
                for item in listings
                if item["listing_id"] in ids
            ]
            self._json({"count": len(results), "results": results})
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        if self.path == "/_add":
            self._json(add_listing())
        elif self.path == "/_hide_once":
            state["hide_once"] = True
            self._json({})
        else:
            self.send_error(404)


if __name__ == "__main__":
    port = int(sys.argv[1])
    for _ in range(3):
        add_listing()
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
