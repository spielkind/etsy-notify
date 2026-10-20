import sqlite3
import time
from collections.abc import Iterable
from pathlib import Path

from shop_notify.models import Listing

_SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    listing_id    INTEGER PRIMARY KEY,
    request_date  INTEGER NOT NULL,
    notified_date INTEGER,
    result        TEXT
);
"""


class ListingStore:
    """Persists seen listings and tracks which ones have already been notified."""

    def __init__(self, path: Path | str) -> None:
        self._db = sqlite3.connect(path)
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    def sync(self, listings: Iterable[Listing]) -> list[Listing]:
        """Store the current listings, drop vanished notified ones, return un-notified ones.

        Listings that disappear and later re-appear are therefore notified again.
        """
        now = int(time.time())
        rows = [(item.listing_id, now, item.model_dump_json()) for item in listings]

        with self._db:
            self._db.executemany(
                """
                INSERT INTO listings (listing_id, request_date, result) VALUES (?, ?, ?)
                ON CONFLICT (listing_id) DO UPDATE
                SET request_date = excluded.request_date, result = excluded.result
                """,
                rows,
            )
            self._db.execute(
                "DELETE FROM listings WHERE request_date < ? AND notified_date IS NOT NULL",
                (now,),
            )

        cursor = self._db.execute(
            "SELECT result FROM listings WHERE notified_date IS NULL ORDER BY listing_id"
        )
        return [Listing.model_validate_json(row[0]) for row in cursor]

    def mark_as_notified(self, listings: Iterable[Listing]) -> None:
        now = int(time.time())
        with self._db:
            self._db.executemany(
                """
                UPDATE listings SET notified_date = ?
                WHERE listing_id = ? AND notified_date IS NULL
                """,
                [(now, item.listing_id) for item in listings],
            )
