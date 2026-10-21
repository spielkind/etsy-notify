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

    def is_empty(self) -> bool:
        return self._db.execute("SELECT 1 FROM listings LIMIT 1").fetchone() is None

    def sync(self, listings: Iterable[Listing]) -> list[Listing]:
        """Store the current listings and return the un-notified ones.

        Un-notified listings are returned in the order given (Etsy: newest first),
        followed by pending ones that are no longer listed.
        """
        now = int(time.time())
        listings = list(listings)
        position = {item.listing_id: index for index, item in enumerate(listings)}
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

        cursor = self._db.execute(
            "SELECT result FROM listings WHERE notified_date IS NULL ORDER BY listing_id"
        )
        pending = [Listing.model_validate_json(row[0]) for row in cursor]
        return sorted(pending, key=lambda item: position.get(item.listing_id, len(position)))

    def forget(self, missing_for: float) -> list[Listing]:
        """Delete notified listings not seen for more than ``missing_for`` seconds.

        A listing that re-appears after that is notified again; one that is only
        missing for a shorter time (e.g. a gap in Etsy's listing index) is not.
        """
        cutoff = int(time.time() - missing_for)
        with self._db:
            rows = self._db.execute(
                """
                DELETE FROM listings WHERE request_date < ? AND notified_date IS NOT NULL
                RETURNING result
                """,
                (cutoff,),
            ).fetchall()
        return [Listing.model_validate_json(row[0]) for row in rows]

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
