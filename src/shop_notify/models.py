from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, ValidationError, field_validator

# Events that can be notified, in order of precedence: if several happen to a listing
# before it is notified, the first one in this list wins
EVENTS = ("new", "restocked", "back", "price_drop", "low_stock", "price_rise", "sold_out")
DEFAULT_EVENTS = frozenset({"new", "back"})


class Money(BaseModel):
    amount: int
    divisor: int
    currency_code: str

    @property
    def value(self) -> Decimal:
        return Decimal(self.amount) / Decimal(self.divisor or 1)

    def __str__(self) -> str:
        return f"{self.value:.2f} {self.currency_code}"


class Notice(BaseModel):
    """Why a listing is notified, with the details for the message."""

    kind: str = "new"
    last_seen: datetime | None = None
    """back: when the listing was last seen before it was gone."""
    sold_out_since: datetime | None = None
    """restocked: when the listing was found sold out."""
    first_seen: datetime | None = None
    """sold_out: when Shop Notify first saw the listing."""
    previous_price: Money | None = None
    """The earlier price, if it differs from the current one."""
    quantity: int | None = None
    """The available quantity, if it is low."""

    @property
    def gone_for(self) -> float:
        """Seconds the listing was gone (back) or sold out (restocked), until now."""
        since = self.last_seen or self.sold_out_since or self.first_seen
        return (datetime.now(UTC) - since).total_seconds() if since else 0.0


# The name used up to version 1.2
Back = Notice


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
    quantity: int | None = None
    image_url: str | None = None
    # Set by Shop Notify for listings to notify; not stored
    event: Notice | None = Field(default=None, exclude=True)

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

    @field_validator("quantity", mode="before")
    @classmethod
    def _ignore_invalid_quantity(cls, value: object) -> object:
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @property
    def kind(self) -> str:
        """The event this listing is notified for ("new" if none is set)."""
        return self.event.kind if self.event else "new"

    @property
    def back(self) -> Notice | None:
        """The notice of a listing that is back in the shop (templates of version 1.1)."""
        return self.event if self.event and self.event.kind == "back" else None

    @property
    def last_modified(self) -> datetime:
        return datetime.fromtimestamp(self.last_modified_timestamp, tz=UTC)

    @property
    def listed(self) -> datetime:
        """When the listing went online (falls back to its last modification)."""
        return datetime.fromtimestamp(self.state_timestamp or self.last_modified_timestamp, tz=UTC)
