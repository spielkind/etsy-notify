from datetime import UTC, datetime

from pydantic import BaseModel


class Listing(BaseModel):
    """Subset of an Etsy v3 ShopListing; only these fields are stored locally."""

    listing_id: int
    title: str
    url: str
    last_modified_timestamp: int

    @property
    def last_modified(self) -> datetime:
        return datetime.fromtimestamp(self.last_modified_timestamp, tz=UTC)
