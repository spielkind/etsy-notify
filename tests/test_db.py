import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from shop_notify.db import SCHEMA_VERSION, Event, ListingStore
from shop_notify.models import Listing, Money
from tests.helpers import make_listing

HOUR = 3600


@pytest.fixture
def store() -> Iterator[ListingStore]:
    s = ListingStore(":memory:")
    yield s
    s.close()


def at(seconds: float) -> AbstractContextManager[Any]:
    return patch("shop_notify.db.time.time", return_value=seconds)


def ids(items: Sequence[Listing | Event]) -> list[int]:
    return [item.listing_id for item in items]


def events(store: ListingStore, listing_id: int | None = None) -> list[tuple[int, str]]:
    return [(e.listing_id, e.event) for e in store.events(listing_id=listing_id)]


def test_new_listings_are_returned_until_notified(store: ListingStore) -> None:
    items = [make_listing(1), make_listing(2)]

    result = store.sync(items)
    assert ids(result.pending) == [1, 2]
    assert result.new == 2
    store.mark_as_notified(items)
    assert store.sync(items).pending == []
    assert events(store) == [(1, "new"), (2, "new"), (1, "notified"), (2, "notified")]


def test_new_listings_keep_the_given_order(store: ListingStore) -> None:
    with at(100):
        store.sync([make_listing(9)])  # pending, will vanish
    with at(200):
        assert ids(store.sync([make_listing(3), make_listing(1), make_listing(2)]).pending) == [
            3,
            1,
            2,
            9,
        ]


def test_unnotified_listing_survives_disappearing(store: ListingStore) -> None:
    with at(100):
        store.sync([make_listing(1)])
    with at(100 + 48 * HOUR):
        result = store.sync([])
    assert ids(result.pending) == [1]
    assert result.missing == 0
    assert result.gone == []


def test_briefly_missing_listing_is_recorded_but_not_notified(store: ListingStore) -> None:
    with at(0):
        store.mark_as_notified(store.sync([make_listing(1), make_listing(2)]).pending)
    with at(HOUR):
        result = store.sync([make_listing(2)], forget_after=2 * HOUR)
        assert result.missing == 1
        assert result.gone == []
    with at(2 * HOUR):
        assert store.sync([make_listing(2)], forget_after=2 * HOUR).missing == 0  # already
    with at(2 * HOUR + 60):
        result = store.sync([make_listing(1), make_listing(2)], forget_after=2 * HOUR)
    assert result.pending == []
    assert result.back == 0
    missing = store.events(listing_id=1)[-1]
    assert missing.event == "missing"
    assert missing.details == {"since": 0, "seconds": 2 * HOUR + 60}


def test_listing_gone_for_longer_is_back_with_last_seen_and_old_price(
    store: ListingStore,
) -> None:
    old = make_listing(1).model_copy(
        update={"price": Money(amount=2499, divisor=100, currency_code="USD")}
    )
    new = old.model_copy(update={"price": Money(amount=1999, divisor=100, currency_code="USD")})
    with at(0):
        store.mark_as_notified(store.sync([old]).pending)
    with at(HOUR):
        assert store.sync([], forget_after=HOUR).missing == 1
    with at(HOUR + 1):
        assert store.sync([], forget_after=HOUR).gone == [old]
    with at(2 * HOUR):
        result = store.sync([new], forget_after=HOUR)

    assert result.back == 1
    [item] = result.pending
    assert item.back is not None
    assert item.back.last_seen.timestamp() == 0
    assert item.back.previous_price == old.price
    assert [e for _, e in events(store, 1)] == [
        "new",
        "notified",
        "gone",
        "price_changed",
        "back",
    ]
    assert store.events(listing_id=1)[3].details == {"old": "24.99 USD", "new": "19.99 USD"}

    # back info survives a failed notification until it was sent
    with at(2 * HOUR + 60):
        [item] = store.sync([new], forget_after=HOUR).pending
    assert item.back is not None
    store.mark_as_notified([item])
    assert store.sync([new]).pending == []


def test_back_without_price_change_has_no_previous_price(store: ListingStore) -> None:
    with at(0):
        store.mark_as_notified(store.sync([make_listing(1)]).pending)
    with at(10):
        store.sync([])
    with at(20):
        store.sync([], forget_after=5)
    with at(30):
        [item] = store.sync([make_listing(1)], forget_after=5).pending
    assert item.back is not None
    assert item.back.previous_price is None


def test_title_change_is_recorded(store: ListingStore) -> None:
    store.mark_as_notified(store.sync([make_listing(1)]).pending)
    store.sync([make_listing(1, title="SALE")])

    [event] = [e for e in store.events(listing_id=1) if e.event == "title_changed"]
    assert event.details == {"old": "Item 1", "new": "SALE 1"}
    assert event.title == "SALE 1"


def test_incomplete_result_marks_nothing_missing(store: ListingStore) -> None:
    with at(0):
        store.mark_as_notified(store.sync([make_listing(1), make_listing(2)]).pending)
    with at(10 * HOUR):
        result = store.sync([make_listing(2)], complete=False, forget_after=HOUR)
    assert (result.missing, result.gone) == (0, [])
    assert events(store, 1) == [(1, "new"), (1, "notified")]


def test_first_run_items_are_recorded(store: ListingStore) -> None:
    store.mark_as_notified(store.sync([make_listing(1)]).pending, sent=False)
    store.mark_as_notified([make_listing(1)])  # already marked: no new event
    assert events(store) == [(1, "new"), (1, "recorded")]


def test_new_event_contains_etsy_timestamps(store: ListingStore) -> None:
    item = make_listing(1).model_copy(
        update={
            "original_creation_timestamp": 10,
            "created_timestamp": 20,
            "state_timestamp": 30,
            "price": Money(amount=100, divisor=100, currency_code="EUR"),
        }
    )
    store.sync([item])
    assert store.events()[0].details == {
        "price": "1.00 EUR",
        "created": 10,
        "renewed": 20,
        "active_since": 30,
        "modified": 1_700_000_000,
    }


def test_events_filtered_by_time(store: ListingStore) -> None:
    with at(100):
        store.sync([make_listing(1)])
    with at(200):
        store.sync([make_listing(2)])
    assert events(store) == [(1, "new"), (2, "new")]
    assert ids(store.events(since=150)) == [2]


def test_polls_are_recorded_and_expire() -> None:
    store = ListingStore(":memory:", poll_history_days=1)
    with at(0):
        store.record_poll(error="boom")
    with at(HOUR):
        result = store.sync([make_listing(1)])
        store.record_poll(reported=2, received=1, complete=False, result=result)
    with at(2 * HOUR):
        assert store.incomplete_since() is not None
        assert store.incomplete_since().timestamp() == HOUR  # type: ignore[union-attr]
        store.record_poll(reported=1, received=1, complete=True)
        assert store.incomplete_since() is None

    polls = store.polls()
    assert [(p.error, p.complete, p.new) for p in polls] == [
        ("boom", None, 0),
        (None, False, 1),
        (None, True, 0),
    ]
    assert len(store.polls(since=HOUR + 1)) == 1
    with at(86400 + 1):
        store.record_poll()
    assert len(store.polls()) == 3  # the first one expired
    store.close()


def test_migrates_a_database_from_version_1_0(tmp_path: Path) -> None:
    path = tmp_path / "shop-notify.db"
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE listings (
            listing_id INTEGER PRIMARY KEY, request_date INTEGER NOT NULL,
            notified_date INTEGER, result TEXT);
        """
    )
    old.executemany(
        "INSERT INTO listings VALUES (?, ?, ?, ?)",
        [
            (1, 200, 100, make_listing(1).model_dump_json()),
            (2, 200, None, make_listing(2).model_dump_json()),
        ],
    )
    old.commit()
    old.close()

    store = ListingStore(path)
    assert (tmp_path / "shop-notify.db.bak-v0").is_file()
    assert events(store) == [(1, "imported"), (2, "imported")]
    assert [e.time.timestamp() for e in store.events()] == [100, 200]
    with at(300):
        assert ids(store.sync([make_listing(1), make_listing(2)]).pending) == [2]
    store.close()

    # opening it again doesn't migrate twice
    store = ListingStore(path)
    assert len(store.events()) == 2
    store.close()
    db = sqlite3.connect(path)
    assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    db.close()


def test_refuses_a_database_from_a_newer_version(tmp_path: Path) -> None:
    path = tmp_path / "shop-notify.db"
    db = sqlite3.connect(path)
    db.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    db.close()
    with pytest.raises(RuntimeError, match="newer than this version"):
        ListingStore(path)


def test_new_database_needs_no_backup(tmp_path: Path) -> None:
    ListingStore(tmp_path / "new.db").close()
    assert [p.name for p in tmp_path.iterdir()] == ["new.db"]
