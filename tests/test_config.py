from pathlib import Path

import pytest
from pydantic import ValidationError

from etsy_notify.config import NotifierType, Settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for key in ("ETSY_SHOP_ID", "ETSY_SHOP_NAME", "MAIL_TO", "NOTIFIER", "POLL_INTERVAL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ETSY_API_KEY", "key")
    monkeypatch.setenv("ETSY_SHARED_SECRET", "secret")


def test_defaults_with_shop_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ETSY_SHOP_NAME", "someshop")
    settings = Settings(_env_file=None)

    assert settings.etsy_shop_name == "someshop"
    assert settings.etsy_shop_id is None
    assert settings.notifier is NotifierType.CONSOLE
    assert settings.poll_interval == 60
    assert settings.mail_to == []
    assert settings.etsy_api_key.get_secret_value() == "key"


def test_mail_to_is_split(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ETSY_SHOP_ID", "42")
    monkeypatch.setenv("MAIL_TO", " a@x.de, b@y.de ,,")

    assert Settings(_env_file=None).mail_to == ["a@x.de", "b@y.de"]


def test_shop_is_required() -> None:
    with pytest.raises(ValidationError, match="ETSY_SHOP_ID or ETSY_SHOP_NAME"):
        Settings(_env_file=None)


def test_poll_interval_lower_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ETSY_SHOP_ID", "42")
    monkeypatch.setenv("POLL_INTERVAL", "5")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_reads_env_file(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text('ETSY_SHOP_ID=7\nNOTIFIER="gmail"\n')

    settings = Settings()

    assert settings.etsy_shop_id == 7
    assert settings.notifier is NotifierType.GMAIL
