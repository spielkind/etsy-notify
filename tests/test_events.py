"""Events beyond new listings: restocked, price changes, sold out and low stock."""

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx
from pydantic import ValidationError

from shop_notify import __main__ as cli
from shop_notify.config import NotifySettings
from shop_notify.db import SCHEMA_VERSION, EventSettings, ListingStore, SyncResult
from shop_notify.etsy import EtsyClient, EtsyError
from shop_notify.models import EVENTS, Listing, Money, Notice
from shop_notify.notifications import MessageRenderer, format_duration, summarize
from tests.helpers import make_listing, sync
from tests.test_main import RecordingNotifier

BASE = "https://openapi.etsy.com/v3/application/"
ALL = frozenset(EVENTS)
HOUR = 3600


def at(seconds: float) -> AbstractContextManager[Any]:
    return patch("shop_notify.db.time.time", return_value=seconds)


def priced(
    listing_id: int, cents: int, quantity: int | None = None, currency: str = "USD"
) -> Listing:
    return make_listing(listing_id).model_copy(
        update={
            "price": Money(amount=cents, divisor=100, currency_code=currency),
            "quantity": quantity,
        }
    )


def make_store(**kwargs: Any) -> ListingStore:
    return ListingStore(":memory:", events=EventSettings(**({"enabled": ALL} | kwargs)))


@pytest.fixture
def store() -> Iterator[ListingStore]:
    s = make_store()
    yield s
    s.close()


def notify_all(store: ListingStore, listings: list[Listing], **kwargs: Any) -> list[Listing]:
    pending: list[Listing] = sync(store, listings, **kwargs).pending
    store.mark_as_notified(pending)
    return pending


def kinds(items: list[Listing]) -> list[str]:
    return [item.kind for item in items]


def test_default_events_are_new_and_back() -> None:
    assert EventSettings().enabled == {"new", "back"}


def test_sold_out_and_restocked(store: ListingStore) -> None:
    with at(0):
        notify_all(store, [priced(1, 2499, 3)])
    with at(10):
        result = store.sync([])
    assert result.newly_missing == [1]
    with at(20):
        store.record_states({1: "sold_out"}, result)
    assert result.sold_out == 1
    [sold] = store.pending()
    assert sold.kind == "sold_out"
    assert sold.event is not None and sold.event.first_seen is not None
    with at(30):
        store.mark_as_notified([sold])

    # back in stock long before the grace period ends: notified immediately
    with at(HOUR):
        result = store.sync([priced(1, 1999, 1)])
    assert result.restocked == 1
    [item] = store.pending()
    assert item.kind == "restocked"
    assert item.event is not None
    assert item.event.sold_out_since is not None
    assert item.event.sold_out_since.timestamp() == 20
    assert item.event.previous_price == Money(amount=2499, divisor=100, currency_code="USD")
    assert item.event.quantity == 1
    assert [e.event for e in store.events(listing_id=1)] == [
        "new",
        "notified",
        "sold_out",
        "notified",
        "price_changed",
        "restocked",
        "low_stock",
    ]
    assert store.events(listing_id=1)[3].details == {"kind": "sold_out"}


def test_restocked_after_the_grace_period_beats_back(store: ListingStore) -> None:
    with at(0):
        notify_all(store, [priced(1, 1000)])
    with at(10):
        result = store.sync([], forget_after=60)
        store.record_states({1: "sold_out"}, result)
        store.mark_as_notified(store.pending())
    with at(100):
        assert len(store.sync([], forget_after=60).gone) == 1
    with at(200):
        assert kinds(sync(store, [priced(1, 1000)], forget_after=60).pending) == ["restocked"]


def test_restocked_disabled_falls_back_to_back() -> None:
    store = make_store(enabled=frozenset({"new", "back"}))
    with at(0):
        notify_all(store, [priced(1, 1000)])
    with at(10):
        result = store.sync([], forget_after=60)
        store.record_states({1: "sold_out"}, result)
    assert store.pending() == []  # sold_out isn't enabled
    with at(100):
        store.sync([], forget_after=60)
    with at(200):
        assert kinds(sync(store, [priced(1, 1000)], forget_after=60).pending) == ["back"]
    store.close()


def test_restocked_disabled_within_the_grace_period_notifies_nothing() -> None:
    store = make_store(enabled=frozenset({"new", "back"}))
    with at(0):
        notify_all(store, [priced(1, 1000)])
    with at(10):
        store.record_states({1: "sold_out"}, store.sync([]))
    with at(20):
        assert sync(store, [priced(1, 1000)]).pending == []
    assert [e.event for e in store.events(listing_id=1)][-2:] == ["sold_out", "restocked"]
    store.close()


def test_other_states_are_recorded_only(store: ListingStore) -> None:
    with at(0):
        notify_all(store, [priced(1, 1000), priced(2, 1000), priced(3, 1000)])
    with at(10):
        result = store.sync([])
        store.record_states({1: "inactive", 2: "removed", 3: "active", 99: "sold_out"}, result)
    assert store.pending() == []
    assert result.sold_out == 0
    assert [e.event for e in store.events(since=10)] == ["inactive", "removed"]


@pytest.mark.parametrize(
    ("prices", "expected"),
    [
        ([2500, 2375], ["price_drop"]),  # -5 %
        ([2500, 2400], []),  # -4 %
        ([2500, 2625], ["price_rise"]),  # +5 %
        ([2500, 2600], []),  # +4 %
        # flipping prices: only the first drop below the notified price counts
        ([2500, 2000, 2500, 2000, 1900], ["price_drop", "price_rise", "price_drop"]),
    ],
)
def test_price_changes(prices: list[int], expected: list[str]) -> None:
    store = make_store()
    notified = []
    for second, cents in enumerate(prices):
        with at(second):
            notified += notify_all(store, [priced(1, cents)])
    assert kinds(notified[1:]) == expected
    store.close()


def test_price_drop_counts_from_the_lowest_notified_price() -> None:
    store = make_store(enabled=frozenset({"new", "price_drop"}))
    notified = []
    for second, cents in enumerate([2500, 2000, 2500, 2000, 1900]):
        with at(second):
            notified += notify_all(store, [priced(1, cents)])
    assert kinds(notified) == ["new", "price_drop", "price_drop"]
    assert notified[2].event is not None
    assert notified[2].event.previous_price == Money(amount=2000, divisor=100, currency_code="USD")
    store.close()


def test_price_changes_need_comparable_prices(store: ListingStore) -> None:
    with at(0):
        notify_all(store, [make_listing(1)])
    with at(1):
        assert sync(store, [priced(1, 100)]).pending == []  # no price before
    with at(2):
        assert sync(store, [priced(1, 50, currency="EUR")]).pending == []  # other currency
    with at(3):
        assert sync(store, [make_listing(1)]).pending == []  # no price now
    with at(4):
        notify_all(store, [priced(1, 0)])
    with at(5):
        assert sync(store, [priced(1, 100)]).pending == []  # from 0 to 1


def test_custom_price_threshold() -> None:
    store = make_store(price_change_percent=Decimal(20))
    with at(0):
        notify_all(store, [priced(1, 1000)])
    with at(1):
        assert sync(store, [priced(1, 850)]).pending == []
    with at(2):
        assert kinds(sync(store, [priced(1, 800)]).pending) == ["price_drop"]
    store.close()


def test_low_stock_is_notified_once_until_it_rises(store: ListingStore) -> None:
    notified = []
    for second, quantity in enumerate([3, 1, 1, 0, 2, 1]):
        with at(second):
            notified += notify_all(store, [priced(1, 1000, quantity)])
    assert kinds(notified) == ["new", "low_stock", "low_stock"]
    assert [item.event.quantity for item in notified if item.event] == [None, 1, 1]


def test_new_listing_with_low_stock_mentions_it(store: ListingStore) -> None:
    [item] = sync(store, [priced(1, 1000, 1)]).pending
    assert item.kind == "new"
    assert item.event is not None and item.event.quantity == 1
    [event] = store.events()
    assert event.details["quantity"] == 1


def test_more_important_notice_wins(store: ListingStore) -> None:
    with at(0):
        notify_all(store, [priced(1, 1000, 5)])
    with at(1):
        sync(store, [priced(1, 900, 5)])  # price drop, not sent
    with at(2):
        assert kinds(sync(store, [priced(1, 900, 1)]).pending) == ["price_drop"]  # low stock
    with at(3):
        result = store.sync([])
        store.record_states({1: "sold_out"}, result)
    assert kinds(store.pending()) == ["sold_out"]  # replaces the outdated notice
    with at(4):
        assert kinds(sync(store, [priced(1, 900, 1)]).pending) == ["restocked"]


def test_a_new_listing_stays_new(store: ListingStore) -> None:
    with at(0):
        sync(store, [priced(1, 1000)])  # not sent yet
    with at(1):
        assert kinds(sync(store, [priced(1, 500, 1)]).pending) == ["new"]


def test_filtered_notices(store: ListingStore) -> None:
    with at(0):
        notify_all(store, [priced(1, 1000)])
    with at(1):
        [drop] = sync(store, [priced(1, 500)]).pending
        store.mark_as_filtered([(drop, "price")])
    with at(2):
        result = sync(store, [priced(1, 500)])
    assert (result.pending, result.refilter) == ([], [])  # dropped, not checked again

    with at(3):
        [new] = sync(store, [priced(1, 500), priced(2, 500)]).pending
        store.mark_as_filtered([(new, "x")])
    with at(4):
        assert ids(store.sync([priced(1, 500), priced(2, 500)]).refilter) == [2]


def ids(items: list[Listing]) -> list[int]:
    return [item.listing_id for item in items]


def test_polls_count_restocked_and_sold_out(store: ListingStore) -> None:
    result = SyncResult(restocked=2, sold_out=1)
    store.record_poll(reported=1, received=1, complete=True, result=result)
    [poll] = store.polls()
    assert (poll.restocked, poll.sold_out) == (2, 1)


def _create_v2(path: Path) -> None:
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE listings (
            listing_id INTEGER PRIMARY KEY, first_seen INTEGER NOT NULL,
            last_seen INTEGER NOT NULL, missing_since INTEGER, gone_since INTEGER,
            notified_date INTEGER, filtered INTEGER NOT NULL DEFAULT 0, back TEXT,
            result TEXT NOT NULL);
        CREATE TABLE listing_events (
            id INTEGER PRIMARY KEY, listing_id INTEGER NOT NULL, time INTEGER NOT NULL,
            event TEXT NOT NULL, details TEXT);
        CREATE TABLE polls (
            id INTEGER PRIMARY KEY, time INTEGER NOT NULL, reported INTEGER,
            received INTEGER, complete INTEGER, new INTEGER NOT NULL DEFAULT 0,
            back INTEGER NOT NULL DEFAULT 0, missing INTEGER NOT NULL DEFAULT 0,
            gone INTEGER NOT NULL DEFAULT 0, filtered INTEGER NOT NULL DEFAULT 0, error TEXT);
        PRAGMA user_version = 2;
        """
    )
    back = '{"last_seen": "1970-01-01T00:01:40Z", "previous_price": null}'
    db.executemany(
        "INSERT INTO listings (listing_id, first_seen, last_seen, notified_date, back, result) "
        "VALUES (?, 100, 100, ?, ?, ?)",
        [
            (1, 100, None, priced(1, 2500).model_dump_json()),  # notified
            (2, None, None, make_listing(2).model_dump_json()),  # new, pending
            (3, None, back, make_listing(3).model_dump_json()),  # back, pending
        ],
    )
    db.commit()
    db.close()


def test_migrates_a_database_from_version_1_2(tmp_path: Path) -> None:
    path = tmp_path / "shop-notify.db"
    _create_v2(path)
    store = ListingStore(path, events=EventSettings(enabled=ALL))
    assert (tmp_path / "shop-notify.db.bak-v2").is_file()
    pending = store.pending()
    assert [(item.listing_id, item.kind) for item in pending] == [(2, "new"), (3, "back")]
    assert pending[1].event is not None
    assert pending[1].event.last_seen is not None
    assert pending[1].event.last_seen.timestamp() == 100
    # the notified price was taken over: a drop is measured from it
    with at(200):
        assert kinds(sync(store, [priced(1, 2000)]).pending)[0] == "price_drop"
    store.close()
    db = sqlite3.connect(path)
    columns = {row[1] for row in db.execute("PRAGMA table_info(listings)")}
    assert "back" not in columns
    assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    db.close()


# --- Etsy -----------------------------------------------------------------------


@respx.mock
def test_listing_states() -> None:
    route = respx.get(f"{BASE}listings/batch").mock(
        side_effect=[
            httpx.Response(
                404, json={"error": "Not all requested listings exist. Missing listing_ids: 3, 4."}
            ),
            httpx.Response(
                200,
                json={
                    "count": 2,
                    "results": [
                        {"listing_id": 1, "state": "sold_out"},
                        {"listing_id": 2, "state": "inactive"},
                    ],
                },
            ),
        ]
    )
    with EtsyClient("key", "secret", base_url=BASE) as client:
        states = client.listing_states([1, 2, 3, 4, 1])
    assert states == {1: "sold_out", 2: "inactive", 3: "removed", 4: "removed"}
    assert route.calls[0].request.url.params["listing_ids"] == "1,2,3,4"
    assert route.calls[1].request.url.params["listing_ids"] == "1,2"


@respx.mock
def test_listing_states_without_answer_are_removed() -> None:
    respx.get(f"{BASE}listings/batch").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )
    with EtsyClient("key", "secret", base_url=BASE) as client:
        assert client.listing_states([5]) == {5: "removed"}


@respx.mock
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="boom"),
        httpx.Response(404, json={"error": "Not found"}),
        httpx.Response(404, json={"error": "Missing listing_ids: 99."}),
    ],
)
def test_listing_states_errors(response: httpx.Response) -> None:
    respx.get(f"{BASE}listings/batch").mock(return_value=response)
    with EtsyClient("key", "secret", base_url=BASE) as client, pytest.raises(EtsyError):
        client.listing_states([1])


# --- poll -----------------------------------------------------------------------


def _client() -> Any:
    client = MagicMock(spec=EtsyClient)
    client.quota = None
    client.listings_reported = client.listings_received = 0
    client.listings_complete = True
    client.listing_images.return_value = {}
    return client


def test_poll_notifies_restocked_items(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    client = _client()
    store = make_store(enabled=frozenset({"new", "back", "restocked"}))
    notifier = RecordingNotifier()
    client.active_listings.return_value = [priced(1, 1000), priced(2, 1000)]
    with patch("time.time", return_value=0):
        cli.run_once(client, store, notifier, 42)

    client.active_listings.return_value = [priced(2, 1000)]
    client.listing_states.return_value = {1: "sold_out"}
    with patch("time.time", return_value=60):
        assert cli.run_once(client, store, notifier, 42) == 0  # sold_out isn't enabled
    client.listing_states.assert_called_once_with([1])
    assert "Listing 1 is no longer listed: sold out" in caplog.text

    client.active_listings.return_value = [priced(1, 1000, 1), priced(2, 1000)]
    with patch("time.time", return_value=120):
        assert cli.run_once(client, store, notifier, 42) == 1
    assert notifier.calls[-1] == [1]
    assert "Back in stock: Item 1 (https://www.etsy.com/listing/1), sold out since" in (caplog.text)
    assert ", 1 left" in caplog.text
    assert [(p.sold_out, p.restocked) for p in store.polls()] == [(0, 0), (1, 0), (0, 1)]
    store.close()


def test_poll_survives_failing_state_lookup(caplog: pytest.LogCaptureFixture) -> None:
    client = _client()
    store = make_store()
    client.active_listings.return_value = [priced(1, 1000)]
    cli.run_once(client, store, RecordingNotifier(), 42)
    client.active_listings.return_value = []
    client.listing_states.side_effect = EtsyError("down")
    cli.run_once(client, store, RecordingNotifier(), 42)
    assert "Could not look up the state of missing listings: down" in caplog.text
    store.close()


def test_gap_in_etsys_index_is_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    client = _client()
    store = make_store()
    client.active_listings.return_value = [priced(1, 1000)]
    cli.run_once(client, store, RecordingNotifier(), 42)
    client.active_listings.return_value = []
    client.listing_states.return_value = {1: "active"}
    cli.run_once(client, store, RecordingNotifier(), 42)
    assert "no longer listed" not in caplog.text
    store.close()


@pytest.mark.parametrize(
    ("notice", "line"),
    [
        ({"kind": "new"}, "New item: Item 1 (https://www.etsy.com/listing/1)"),
        (
            {"kind": "back", "last_seen": "2026-10-01T10:00:00Z", "previous_price": None},
            "Back in the shop: Item 1 (https://www.etsy.com/listing/1), last seen 2026-10-01",
        ),
        (
            {
                "kind": "price_drop",
                "previous_price": {"amount": 2000, "divisor": 100, "currency_code": "USD"},
            },
            "Price drop: Item 1 (https://www.etsy.com/listing/1), was 20.00 USD",
        ),
        (
            {"kind": "low_stock", "quantity": 0},
            "Almost sold out: Item 1 (https://www.etsy.com/listing/1), 0 left",
        ),
    ],
)
def test_describe_notice(notice: dict[str, Any], line: str) -> None:
    item = make_listing(1).model_copy(update={"event": Notice.model_validate(notice)})
    assert cli.describe_notice(item).startswith(line)
    assert (
        cli.describe_notice(make_listing(1)) == "New item: Item 1 (https://www.etsy.com/listing/1)"
    )


# --- settings -------------------------------------------------------------------


def test_event_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTIFY_EVENTS", " new, restocked ,price_drop,")
    monkeypatch.setenv("NOTIFY_PRICE_CHANGE_PERCENT", "10")
    monkeypatch.setenv("NOTIFY_LOW_STOCK", "2")
    settings = NotifySettings().event_settings()
    assert settings == EventSettings(
        enabled=frozenset({"new", "restocked", "price_drop"}),
        price_change_percent=Decimal(10),
        low_stock=2,
    )

    monkeypatch.setenv("NOTIFY_EVENTS", "new,back")
    monkeypatch.setenv("NOTIFY_BACK", "false")
    assert NotifySettings().event_settings().enabled == {"new"}


def test_unknown_event(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTIFY_EVENTS", "new,sale")
    with pytest.raises(ValidationError, match="unknown event"):
        NotifySettings()


# --- messages -------------------------------------------------------------------


def _with(kind: str, **notice: Any) -> Listing:
    return priced(1, 1999).model_copy(update={"event": Notice(kind=kind, **notice)})


@pytest.mark.parametrize(
    ("kinds_", "en", "de"),
    [
        (["price_drop"], "1 price drop", "1 Preissenkung"),
        (["price_drop", "price_drop"], "2 price drops", "2 Preissenkungen"),
        (
            ["new", "restocked", "price_rise"],
            "1 new, 1 back in stock and 1 price increase",
            "1 neu, 1 wieder verfügbar und 1 Preiserhöhung",
        ),
        (
            ["sold_out", "low_stock"],
            "1 almost sold out and 1 sold out",
            "1 fast ausverkauft und 1 ausverkauft",
        ),
    ],
)
def test_summary(kinds_: list[str], en: str, de: str) -> None:
    items = [_with(kind) for kind in kinds_]
    assert summarize(items, "en") == en
    assert summarize(items, "de") == de


def test_messages_for_events() -> None:
    old = Money(amount=2499, divisor=100, currency_code="USD")
    now = datetime.now(UTC)
    items = [
        _with("restocked", sold_out_since=now - timedelta(hours=11), quantity=1),
        _with("price_drop", previous_price=old),
        _with("price_rise", previous_price=Money(amount=1500, divisor=100, currency_code="USD")),
        _with("sold_out", first_seen=now - timedelta(days=3)),
        _with("price_drop", previous_price=Money(amount=2499, divisor=100, currency_code="EUR")),
    ]
    en = MessageRenderer(shop_name="shop").render(items)
    assert "Back in stock · $19.99 · sold out for 11 hours · only 1 left" in en.text
    assert "Price drop · $19.99 (was $24.99, \u221220%)" in en.text
    assert "Price increase · $19.99 (was $15.00, +33%)" in en.text
    assert "Sold out · $19.99 · in the shop since " in en.text
    assert "Price drop · $19.99 (was €24.99) · " in en.text  # no percentage across currencies
    assert en.items[0].subject == "Back in stock in shop: Item 1"
    assert "line-through" in en.html and ">Back in stock<" in en.html

    de = MessageRenderer(shop_name="shop", language="de").render(items[:2])
    assert "Wieder verfügbar · 19,99 $ · 11 Stunden ausverkauft · nur noch 1" in de.text
    assert "Preissenkung · 19,99 $ (vorher 24,99 $, \u221220 %)" in de.text
    assert de.subject == "1 wieder verfügbar und 1 Preissenkung in shop"


@pytest.mark.parametrize(
    ("seconds", "en", "de"),
    [
        (60, "1 minute", "1 Minute"),
        (3 * 3600, "3 hours", "3 Stunden"),
        (2 * 86400, "2 days", "2 Tage"),
    ],
)
def test_format_duration(seconds: int, en: str, de: str) -> None:
    assert format_duration(seconds, "en") == en
    assert format_duration(seconds, "de") == de


def test_notice_without_dates() -> None:
    assert Notice(kind="restocked").gone_for == 0
    assert _with("restocked").back is None
