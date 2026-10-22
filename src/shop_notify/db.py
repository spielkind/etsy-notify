"""SQLite storage of listings, their history and the polls.

Schema version 1 (see ``docs/architecture.md`` for a diagram):

- ``listings``: one row per listing ever seen, with its latest state; rows are kept
  when a listing leaves the shop (``gone_since``).
- ``listing_events``: append-only history per listing.
- ``polls``: one row per poll, kept for ``poll_history_days``.
"""

import json
import logging
import shutil
import sqlite3
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shop_notify.models import Back, Listing

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    listing_id    INTEGER PRIMARY KEY,
    first_seen    INTEGER NOT NULL,
    last_seen     INTEGER NOT NULL,
    missing_since INTEGER,
    gone_since    INTEGER,
    notified_date INTEGER,
    back          TEXT,
    result        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS listing_events (
    id         INTEGER PRIMARY KEY,
    listing_id INTEGER NOT NULL REFERENCES listings (listing_id),
    time       INTEGER NOT NULL,
    event      TEXT NOT NULL,
    details    TEXT
);
CREATE INDEX IF NOT EXISTS listing_events_listing ON listing_events (listing_id, time);
CREATE INDEX IF NOT EXISTS listing_events_time ON listing_events (time);
CREATE TABLE IF NOT EXISTS polls (
    id       INTEGER PRIMARY KEY,
    time     INTEGER NOT NULL,
    reported INTEGER,
    received INTEGER,
    complete INTEGER,
    new      INTEGER NOT NULL DEFAULT 0,
    back     INTEGER NOT NULL DEFAULT 0,
    missing  INTEGER NOT NULL DEFAULT 0,
    gone     INTEGER NOT NULL DEFAULT 0,
    error    TEXT
);
CREATE INDEX IF NOT EXISTS polls_time ON polls (time);
"""

# Schema of versions up to 1.0.x (user_version 0)
_LEGACY_COLUMNS = {"listing_id", "request_date", "notified_date", "result"}


@dataclass
class SyncResult:
    """What changed in the shop since the previous poll."""

    pending: list[Listing] = field(default_factory=list)
    """Listings to notify: new ones and those back in the shop, plus earlier unsent ones."""
    new: int = 0
    back: int = 0
    missing: int = 0
    gone: list[Listing] = field(default_factory=list)


@dataclass(frozen=True)
class Event:
    listing_id: int
    time: datetime
    event: str
    details: dict[str, Any]
    title: str


@dataclass(frozen=True)
class Poll:
    time: datetime
    reported: int | None
    received: int | None
    complete: bool | None
    new: int
    back: int
    missing: int
    gone: int
    error: str | None


def _ts(value: int) -> datetime:
    return datetime.fromtimestamp(value, tz=UTC)


class ListingStore:
    """Persists the listings of a shop, their history and the polls."""

    def __init__(self, path: Path | str, *, poll_history_days: float = 14) -> None:
        self._poll_history = poll_history_days * 86400
        self._db = sqlite3.connect(path)
        self._db.execute("PRAGMA foreign_keys = ON")
        try:
            self._migrate(path)
        except BaseException:
            self._db.close()
            raise

    def close(self) -> None:
        self._db.close()

    # -- schema ---------------------------------------------------------------

    def _migrate(self, path: Path | str) -> None:
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"Database {path} has schema version {version}, which is newer than this "
                f"version of Shop Notify supports ({SCHEMA_VERSION}) - please update"
            )
        if version == SCHEMA_VERSION:
            return
        columns = {row[1] for row in self._db.execute("PRAGMA table_info(listings)")}
        if columns and str(path) != ":memory:":
            backup = Path(f"{path}.bak-v{version}")
            log.info("Upgrading database schema to version %d, backup: %s", SCHEMA_VERSION, backup)
            shutil.copyfile(path, backup)
        with self._db:
            if columns == _LEGACY_COLUMNS:
                self._db.execute("ALTER TABLE listings RENAME TO listings_v0")
            self._db.executescript(_SCHEMA)
            if columns == _LEGACY_COLUMNS:
                self._db.execute(
                    """
                    INSERT INTO listings (listing_id, first_seen, last_seen, notified_date, result)
                    SELECT listing_id, MIN(request_date, COALESCE(notified_date, request_date)),
                           request_date, notified_date, result
                    FROM listings_v0
                    """
                )
                self._db.execute(
                    """
                    INSERT INTO listing_events (listing_id, time, event)
                    SELECT listing_id, first_seen, 'imported' FROM listings
                    """
                )
                self._db.execute("DROP TABLE listings_v0")
            self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    # -- polling --------------------------------------------------------------

    def is_empty(self) -> bool:
        return self._db.execute("SELECT 1 FROM listings LIMIT 1").fetchone() is None

    def sync(
        self, listings: Iterable[Listing], *, complete: bool = True, forget_after: float = 86400
    ) -> SyncResult:
        """Store the current listings and record what changed.

        Returns the listings to notify in the order given (Etsy: newest first),
        followed by pending ones that are no longer listed. Listings missing from a
        ``complete`` result are marked as missing; once they have not been seen for more
        than ``forget_after`` seconds, they count as gone and are notified again if they
        come back. An incomplete result never marks anything as missing or gone.
        """
        now = int(time.time())
        listings = list(listings)
        result = SyncResult()
        rows = {
            row[0]: row
            for row in self._db.execute(
                "SELECT listing_id, last_seen, missing_since, gone_since, result FROM listings"
            )
        }
        with self._db:
            for item in listings:
                row = rows.get(item.listing_id)
                if row is None:
                    self._insert(item, now)
                    result.new += 1
                elif self._update(item, row, now):
                    result.back += 1
            if complete:
                result.missing, result.gone = self._mark_missing(listings, now, forget_after)

        position = {item.listing_id: index for index, item in enumerate(listings)}
        cursor = self._db.execute(
            "SELECT result, back FROM listings WHERE notified_date IS NULL ORDER BY listing_id"
        )
        for data, back in cursor:
            item = Listing.model_validate_json(data)
            if back:
                item.back = Back.model_validate_json(back)
            result.pending.append(item)
        result.pending.sort(key=lambda item: position.get(item.listing_id, len(position)))
        return result

    def _event(self, listing_id: int, now: int, event: str, **details: Any) -> None:
        self._db.execute(
            "INSERT INTO listing_events (listing_id, time, event, details) VALUES (?, ?, ?, ?)",
            (listing_id, now, event, json.dumps(details) if details else None),
        )

    def _insert(self, item: Listing, now: int) -> None:
        self._db.execute(
            "INSERT INTO listings (listing_id, first_seen, last_seen, result) VALUES (?, ?, ?, ?)",
            (item.listing_id, now, now, item.model_dump_json()),
        )
        etsy = {
            "price": str(item.price) if item.price else None,
            "created": item.original_creation_timestamp,
            "renewed": item.created_timestamp,
            "active_since": item.state_timestamp,
            "modified": item.last_modified_timestamp,
        }
        self._event(item.listing_id, now, "new", **{k: v for k, v in etsy.items() if v})

    def _update(self, item: Listing, row: tuple[Any, ...], now: int) -> bool:
        """Update a known listing; returns whether it is back after being gone."""
        _, last_seen, missing_since, gone_since, data = row
        old = Listing.model_validate_json(data)
        if old.title != item.title:
            self._event(item.listing_id, now, "title_changed", old=old.title, new=item.title)
        if old.price != item.price:
            self._event(
                item.listing_id,
                now,
                "price_changed",
                old=str(old.price) if old.price else None,
                new=str(item.price) if item.price else None,
            )
        back = None
        if gone_since is not None:
            back = Back(
                last_seen=_ts(last_seen),
                previous_price=old.price if old.price != item.price else None,
            )
            self._event(item.listing_id, now, "back", last_seen=last_seen)
        elif missing_since is not None:
            self._event(item.listing_id, now, "missing", since=last_seen, seconds=now - last_seen)
        self._db.execute(
            """
            UPDATE listings SET last_seen = ?, missing_since = NULL, gone_since = NULL,
                result = ?,
                notified_date = CASE WHEN ? THEN NULL ELSE notified_date END,
                back = COALESCE(?, back)
            WHERE listing_id = ?
            """,
            (
                now,
                item.model_dump_json(),
                back is not None,
                back.model_dump_json() if back else None,
                item.listing_id,
            ),
        )
        return back is not None

    def _mark_missing(
        self, listings: Sequence[Listing], now: int, forget_after: float
    ) -> tuple[int, list[Listing]]:
        present = [item.listing_id for item in listings]
        placeholders = ",".join("?" * len(present))
        absent = f"listing_id NOT IN ({placeholders})" if present else "1"
        # Only notified listings: pending ones are sent anyway, even if they vanished
        missing = self._db.execute(
            f"""
            UPDATE listings SET missing_since = ?
            WHERE {absent} AND notified_date IS NOT NULL
                AND missing_since IS NULL AND gone_since IS NULL
            """,  # only placeholders are interpolated
            (now, *present),
        ).rowcount
        cutoff = int(now - forget_after)
        gone = [
            Listing.model_validate_json(row[0])
            for row in self._db.execute(
                """
                UPDATE listings SET gone_since = ?
                WHERE missing_since IS NOT NULL AND gone_since IS NULL AND last_seen < ?
                RETURNING result
                """,
                (now, cutoff),
            ).fetchall()
        ]
        for item in gone:
            self._event(item.listing_id, now, "gone")
        return missing, gone

    def mark_as_notified(self, listings: Iterable[Listing], *, sent: bool = True) -> None:
        """Mark listings as notified; ``sent=False`` if they were only recorded."""
        now = int(time.time())
        with self._db:
            for item in listings:
                updated = self._db.execute(
                    """
                    UPDATE listings SET notified_date = ?, back = NULL
                    WHERE listing_id = ? AND notified_date IS NULL
                    """,
                    (now, item.listing_id),
                ).rowcount
                if updated:
                    self._event(item.listing_id, now, "notified" if sent else "recorded")

    def record_poll(
        self,
        *,
        reported: int | None = None,
        received: int | None = None,
        complete: bool | None = None,
        result: SyncResult | None = None,
        error: str | None = None,
    ) -> None:
        """Record a poll and delete polls older than the configured retention."""
        now = int(time.time())
        result = result or SyncResult()
        with self._db:
            self._db.execute(
                """
                INSERT INTO polls (time, reported, received, complete, new, back, missing,
                                   gone, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    reported,
                    received,
                    complete,
                    result.new,
                    result.back,
                    result.missing,
                    len(result.gone),
                    error,
                ),
            )
            self._db.execute("DELETE FROM polls WHERE time < ?", (now - self._poll_history,))

    def incomplete_since(self) -> datetime | None:
        """Start of the current series of incomplete polls, if the last one was incomplete."""
        row = self._db.execute(
            """
            SELECT MIN(time) FROM polls
            WHERE complete = 0
                AND time > COALESCE((SELECT MAX(time) FROM polls WHERE complete = 1), 0)
            """
        ).fetchone()
        return _ts(row[0]) if row[0] is not None else None

    # -- history --------------------------------------------------------------

    def events(self, *, listing_id: int | None = None, since: float = 0) -> list[Event]:
        query = """
            SELECT e.listing_id, e.time, e.event, e.details, l.result
            FROM listing_events e JOIN listings l USING (listing_id)
            WHERE e.time >= ?
        """
        params: list[Any] = [since]
        if listing_id is not None:
            query += " AND e.listing_id = ?"
            params.append(listing_id)
        query += " ORDER BY e.time, e.id"
        return [
            Event(
                listing_id=row[0],
                time=_ts(row[1]),
                event=row[2],
                details=json.loads(row[3]) if row[3] else {},
                title=Listing.model_validate_json(row[4]).title,
            )
            for row in self._db.execute(query, params)
        ]

    def polls(self, *, since: float = 0) -> list[Poll]:
        return [
            Poll(
                time=_ts(row[0]),
                reported=row[1],
                received=row[2],
                complete=None if row[3] is None else bool(row[3]),
                new=row[4],
                back=row[5],
                missing=row[6],
                gone=row[7],
                error=row[8],
            )
            for row in self._db.execute(
                """
                SELECT time, reported, received, complete, new, back, missing, gone, error
                FROM polls WHERE time >= ? ORDER BY time, id
                """,
                (since,),
            )
        ]
