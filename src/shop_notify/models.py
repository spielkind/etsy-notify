from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, ValidationError, field_validator


class Money(BaseModel):
    amount: int
    divisor: int
    currency_code: str

    @property
    def value(self) -> Decimal:
        return Decimal(self.amount) / Decimal(self.divisor or 1)

    def __str__(self) -> str:
        return f"{self.value:.2f} {self.currency_code}"


class Back(BaseModel):
    """Context for a listing that is back in the shop after it was gone."""

    last_seen: datetime
    previous_price: Money | None = None
    """The price when it was last seen, if it differs from the current one."""

    @property
    def gone_for(self) -> float:
        """Seconds between the last time the listing was seen and now."""
        return (datetime.now(UTC) - self.last_seen).total_seconds()


class Listing(BaseModel):
    """Subset of an Etsy v3 ShopListing; only these fields are stored locally."""

    listing_id: int
    title: str
    url: str
    last_modified_timestamp: int
    # When the listing became active; missing in data stored by older versions
    state_timestamp: int | None = None
    # When the listing was created or last renewed, and when it was first created
    created_timestamp: int | None = None
    original_creation_timestamp: int | None = None
    price: Money | None = None
    image_url: str | None = None
    # Set by Shop Notify for listings that are back in the shop; not stored
    back: Back | None = Field(default=None, exclude=True)

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

    @property
    def listed(self) -> datetime:
        """When the listing went online (falls back to its last modification)."""
        return datetime.fromtimestamp(self.state_timestamp or self.last_modified_timestamp, tz=UTC)
