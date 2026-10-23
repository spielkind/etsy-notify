from decimal import Decimal
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from shop_notify.db import EventSettings
from shop_notify.filters import Filters
from shop_notify.models import EVENTS


class NotifySettings(BaseSettings):
    """Settings needed to send notifications; no Etsy credentials required."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    etsy_shop_name: str | None = None

    db_path: Path = Path("shop-notify.db")
    log_file: Path | None = Path("shop-notify.log")
    log_level: str = "INFO"

    # Apprise notification targets; without any, notifications go to the console only
    notify_config: Path | None = None
    notify_urls: SecretStr | None = None
    # Print notifications to stdout: "auto" = only if no other targets are configured
    notify_console: Literal["auto"] | bool = "auto"
    # On the first run (empty database) existing items are only recorded, not notified
    notify_existing_on_first_run: bool = False
    # Events to notify about (comma-separated): new, back, restocked, price_drop,
    # price_rise, sold_out, low_stock - see docs/events.md
    notify_events: str = "new,back"
    # Up to version 1.2: false = don't notify items back in the shop
    notify_back: bool = True
    notify_price_change_percent: Decimal = Field(default=Decimal(5), ge=0)
    notify_low_stock: int = Field(default=1, ge=0)
    # Directory with custom subject.txt.j2 / body.txt.j2 / body.html.j2 templates
    notify_template_dir: Path | None = None
    # Language of the built-in templates
    notify_language: Literal["en", "de"] = "en"
    # Push/chat services: one message per item with its image, up to this many items
    notify_images: bool = True
    notify_images_max: int = Field(default=5, ge=1)
    # Above notify_images_max: attach the images to the summary message (Telegram album)
    notify_images_in_summary: bool = False

    # Filters (see docs/filters.md): keywords are comma-separated, each regex is one
    # pattern (use | for alternatives); all are case-insensitive and match the title
    notify_include: str | None = None
    notify_exclude: str | None = None
    notify_include_regex: str | None = None
    notify_exclude_regex: str | None = None
    notify_min_price: Decimal | None = None
    notify_max_price: Decimal | None = None
    # YAML file with any number of filters, merged with the ones above
    filter_config: Path | None = None

    @field_validator(
        "log_file",
        "notify_config",
        "notify_template_dir",
        "filter_config",
        "notify_min_price",
        "notify_max_price",
        mode="before",
    )
    @classmethod
    def _empty_path_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator(
        "notify_urls",
        "notify_include",
        "notify_exclude",
        "notify_include_regex",
        "notify_exclude_regex",
        mode="before",
    )
    @classmethod
    def _empty_urls_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("notify_console", mode="before")
    @classmethod
    def _normalize_console(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("notify_events")
    @classmethod
    def _check_events(cls, value: str) -> str:
        unknown = {e.strip() for e in value.split(",") if e.strip()} - set(EVENTS)
        if unknown:
            raise ValueError(
                f"unknown event(s) {', '.join(sorted(unknown))}; use {', '.join(EVENTS)}"
            )
        return value

    def event_settings(self) -> EventSettings:
        """The events to notify, with ``NOTIFY_BACK=false`` removing "back"."""
        enabled = {e.strip() for e in self.notify_events.split(",") if e.strip()}
        if not self.notify_back:
            enabled.discard("back")
        return EventSettings(
            enabled=frozenset(enabled),
            price_change_percent=self.notify_price_change_percent,
            low_stock=self.notify_low_stock,
        )

    def filters(self) -> Filters:
        """The configured filters; raises ``FilterError`` if they are invalid."""
        return Filters.from_settings(
            include=self.notify_include,
            exclude=self.notify_exclude,
            include_regex=self.notify_include_regex,
            exclude_regex=self.notify_exclude_regex,
            min_price=self.notify_min_price,
            max_price=self.notify_max_price,
            config=self.filter_config,
        )

    @property
    def has_notify_targets(self) -> bool:
        return self.notify_config is not None or self.notify_urls is not None


class Settings(NotifySettings):
    """All settings for watching a shop."""

    etsy_api_key: SecretStr
    etsy_shared_secret: SecretStr
    etsy_api_endpoint: str = "https://openapi.etsy.com/v3/application/"
    etsy_shop_id: int | None = None

    poll_interval: int = Field(default=300, ge=10)
    # Hours a notified listing must be missing from the shop before it counts as gone
    # (and is notified as back in the shop if it returns)
    forget_after_hours: float = Field(default=24, ge=0)
    # Days the poll log is kept (shop-notify history --polls)
    poll_history_days: float = Field(default=14, ge=0)
    heartbeat_file: Path | None = None

    @model_validator(mode="after")
    def _require_shop(self) -> Self:
        if self.etsy_shop_id is None and not self.etsy_shop_name:
            raise ValueError("either ETSY_SHOP_ID or ETSY_SHOP_NAME must be set")
        return self

    @property
    def heartbeat_path(self) -> Path:
        """Heartbeat file, by default next to the database."""
        return self.heartbeat_file or self.db_path.with_suffix(".heartbeat")

    @property
    def heartbeat_max_age(self) -> float:
        """Seconds after which a missing heartbeat update counts as unhealthy."""
        return 2 * self.poll_interval + 60
