from pathlib import Path

import pytest
from pydantic import ValidationError

from shop_notify.config import Settings

_ENV_KEYS = (
    "ETSY_SHOP_ID",
    "ETSY_SHOP_NAME",
    "NOTIFY_URLS",
    "NOTIFY_CONFIG",
    "POLL_INTERVAL",
    "LOG_FILE",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ETSY_API_KEY", "key")
    monkeypatch.setenv("ETSY_SHARED_SECRET", "secret")


def test_defaults_with_shop_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ETSY_SHOP_NAME", "someshop")
    settings = Settings(_env_file=None)

    assert settings.etsy_shop_name == "someshop"
    assert settings.etsy_shop_id is None
    assert settings.poll_interval == 60
    assert settings.notify_urls is None
    assert settings.notify_config is None
    assert settings.etsy_api_key.get_secret_value() == "key"


def test_empty_values_disable_optional_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ETSY_SHOP_ID", "42")
    monkeypatch.setenv("NOTIFY_URLS", "  ")
    monkeypatch.setenv("NOTIFY_CONFIG", "")
    monkeypatch.setenv("LOG_FILE", "")

    settings = Settings(_env_file=None)

    assert settings.notify_urls is None
    assert settings.notify_config is None
    assert settings.log_file is None


def test_notify_urls_are_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ETSY_SHOP_ID", "42")
    monkeypatch.setenv("NOTIFY_URLS", "mailtos://me:pw@gmail.com")

    settings = Settings(_env_file=None)

    assert "pw" not in repr(settings)
    assert settings.notify_urls is not None
    assert settings.notify_urls.get_secret_value() == "mailtos://me:pw@gmail.com"


def test_shop_is_required() -> None:
    with pytest.raises(ValidationError, match="ETSY_SHOP_ID or ETSY_SHOP_NAME"):
        Settings(_env_file=None)


def test_poll_interval_lower_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ETSY_SHOP_ID", "42")
    monkeypatch.setenv("POLL_INTERVAL", "5")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_reads_env_file(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text('ETSY_SHOP_ID=7\nNOTIFY_CONFIG="notify.yml"\n')

    settings = Settings()

    assert settings.etsy_shop_id == 7
    assert settings.notify_config == Path("notify.yml")
