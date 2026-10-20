from collections.abc import Iterator
from unittest.mock import patch

import pytest

from shop_notify.db import ListingStore
from tests.helpers import make_listing


@pytest.fixture
def store() -> Iterator[ListingStore]:
    s = ListingStore(":memory:")
    yield s
    s.close()


def test_new_listings_are_returned_until_notified(store: ListingStore) -> None:
    items = [make_listing(1), make_listing(2)]

    assert [i.listing_id for i in store.sync(items)] == [1, 2]
    store.mark_as_notified(items)
    assert store.sync(items) == []


def test_reappearing_listing_is_notified_again(store: ListingStore) -> None:
    with patch("shop_notify.db.time.time", return_value=100):
        store.mark_as_notified(store.sync([make_listing(1), make_listing(2)]))
    with patch("shop_notify.db.time.time", return_value=200):
        assert store.sync([make_listing(2)]) == []
    with patch("shop_notify.db.time.time", return_value=300):
        assert [i.listing_id for i in store.sync([make_listing(1), make_listing(2)])] == [1]


def test_unnotified_listing_survives_disappearing(store: ListingStore) -> None:
    with patch("shop_notify.db.time.time", return_value=100):
        store.sync([make_listing(1)])
    with patch("shop_notify.db.time.time", return_value=200):
        assert [i.listing_id for i in store.sync([])] == [1]
