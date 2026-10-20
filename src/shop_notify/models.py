from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel


class Money(BaseModel):
    amount: int
    divisor: int
    currency_code: str

    @property
    def value(self) -> Decimal:
        return Decimal(self.amount) / Decimal(self.divisor or 1)

    def __str__(self) -> str:
        return f"{self.value:.2f} {self.currency_code}"


class Listing(BaseModel):
    """Subset of an Etsy v3 ShopListing; only these fields are stored locally."""

    listing_id: int
    title: str
    url: str
    last_modified_timestamp: int
    price: Money | None = None
    image_url: str | None = None

    @property
    def last_modified(self) -> datetime:
        return datetime.fromtimestamp(self.last_modified_timestamp, tz=UTC)
