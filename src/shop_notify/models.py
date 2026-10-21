from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ValidationError, field_validator


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

    @field_validator("price", mode="before")
    @classmethod
    def _ignore_invalid_price(cls, value: object) -> object:
        """A missing or malformed price must not make the whole listing unusable."""
        if value is None or isinstance(value, Money):
            return value
        try:
            return Money.model_validate(value)
        except ValidationError:
            return None

    @property
    def last_modified(self) -> datetime:
        return datetime.fromtimestamp(self.last_modified_timestamp, tz=UTC)
