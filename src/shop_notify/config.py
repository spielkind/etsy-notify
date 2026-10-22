from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # Notify items that are back in the shop after they were gone (FORGET_AFTER_HOURS)
    notify_back: bool = True
    # Directory with custom subject.txt.j2 / body.txt.j2 / body.html.j2 templates
    notify_template_dir: Path | None = None
    # Language of the built-in templates
    notify_language: Literal["en", "de"] = "en"
    # Push/chat services: one message per item with its image, up to this many items
    notify_images: bool = True
    notify_images_max: int = Field(default=5, ge=1)
    # Above notify_images_max: attach the images to the summary message (Telegram album)
    notify_images_in_summary: bool = False

    @field_validator("log_file", "notify_config", "notify_template_dir", mode="before")
    @classmethod
    def _empty_path_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("notify_urls", mode="before")
    @classmethod
    def _empty_urls_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("notify_console", mode="before")
    @classmethod
    def _normalize_console(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

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
