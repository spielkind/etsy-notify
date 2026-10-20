from enum import StrEnum
from pathlib import Path
from typing import Annotated, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class NotifierType(StrEnum):
    CONSOLE = "console"
    GMAIL = "gmail"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    etsy_api_key: SecretStr
    etsy_shared_secret: SecretStr
    etsy_api_endpoint: str = "https://openapi.etsy.com/v3/application/"
    etsy_shop_id: int | None = None
    etsy_shop_name: str | None = None

    poll_interval: int = Field(default=60, ge=10)
    db_path: Path = Path("etsy.db")
    heartbeat_file: Path | None = None
    log_file: Path | None = Path("etsy.log")
    log_level: str = "INFO"

    notifier: NotifierType = NotifierType.CONSOLE
    gmail_user: str | None = None
    gmail_password: SecretStr | None = None
    mail_from: str | None = None
    mail_to: Annotated[list[str], NoDecode] = []

    @field_validator("mail_to", mode="before")
    @classmethod
    def _split_mail_to(cls, value: object) -> object:
        if isinstance(value, str):
            return [addr.strip() for addr in value.split(",") if addr.strip()]
        return value

    @field_validator("log_file", mode="before")
    @classmethod
    def _empty_log_file_disables(cls, value: object) -> object:
        return None if value == "" else value

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
