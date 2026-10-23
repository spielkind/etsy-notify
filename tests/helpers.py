from collections.abc import Sequence
from typing import Any

from shop_notify.db import ListingStore
from shop_notify.models import Listing


def make_listing(listing_id: int, title: str = "Item") -> Listing:
    return Listing(
        listing_id=listing_id,
        title=f"{title} {listing_id}",
        url=f"https://www.etsy.com/listing/{listing_id}",
        last_modified_timestamp=1_700_000_000,
    )


class Synced:
    """``SyncResult`` plus the queued listings, as returned by ``sync`` up to version 1.2."""

    def __init__(self, result: object, pending: list[Listing]) -> None:
        self.__dict__.update(vars(result))
        self.pending = pending


def sync(store: ListingStore, listings: Sequence[Listing], **kwargs: Any) -> Any:
    """Poll into ``store`` and return what changed together with the queued listings."""
    listings = list(listings)
    result = store.sync(listings, **kwargs)
    return Synced(result, store.pending(listings))
