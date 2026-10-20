import logging
import signal
from collections.abc import Iterator, Sequence
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from etsy_notify import __main__ as cli
from etsy_notify.config import NotifierType, Settings
from etsy_notify.db import ListingStore
from etsy_notify.etsy import EtsyClient, EtsyError
from etsy_notify.models import Listing
from etsy_notify.notifications import ConsoleNotifier, GmailNotifier
from tests.helpers import make_listing

BASE = "https://openapi.etsy.com/v3/application/"


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "etsy_api_key": "key",
        "etsy_shared_secret": "secret",
        "etsy_shop_id": 42,
        "log_file": None,
    }
    values.update(overrides)
    return Settings.model_validate(values)


class RecordingNotifier:
    def __init__(self) -> None:
        self.calls: list[list[int]] = []

    def notify(self, listings: Sequence[Listing]) -> None:
        self.calls.append([item.listing_id for item in listings])


@pytest.fixture
def restore_signals() -> Iterator[None]:
    saved = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    yield
    for sig, handler in saved.items():
        signal.signal(sig, handler)


@pytest.fixture
def restore_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    for handler in root.handlers:
        if handler not in handlers:
            handler.close()
    root.handlers, root.level = handlers, level


def test_build_notifier_console() -> None:
    assert isinstance(cli.build_notifier(_settings()), ConsoleNotifier)


def test_build_notifier_gmail() -> None:
    notifier = cli.build_notifier(
        _settings(
            notifier=NotifierType.GMAIL,
            gmail_user="me@gmail.com",
            gmail_password="pw",
            mail_to=["a@x.de"],
        )
    )

    assert isinstance(notifier, GmailNotifier)
    assert notifier.sent_from == "me@gmail.com"
    assert notifier.password == "pw"


def test_build_notifier_gmail_requires_credentials() -> None:
    with pytest.raises(SystemExit, match="GMAIL_USER"):
        cli.build_notifier(_settings(notifier=NotifierType.GMAIL))


def test_resolve_shop_id_prefers_configured_id() -> None:
    client = MagicMock(spec=EtsyClient)

    assert cli.resolve_shop_id(client, _settings(etsy_shop_id=7)) == 7
    client.find_shop_id.assert_not_called()


def test_resolve_shop_id_by_name() -> None:
    client = MagicMock(spec=EtsyClient)
    client.find_shop_id.return_value = 99

    settings = _settings(etsy_shop_id=None, etsy_shop_name="someshop")

    assert cli.resolve_shop_id(client, settings) == 99


def test_resolve_shop_id_not_found_exits() -> None:
    client = MagicMock(spec=EtsyClient)
    client.find_shop_id.side_effect = EtsyError("not found")

    with pytest.raises(SystemExit, match="someshop"):
        cli.resolve_shop_id(client, _settings(etsy_shop_id=None, etsy_shop_name="someshop"))


def test_run_once_notifies_only_new_items() -> None:
    client = MagicMock(spec=EtsyClient)
    client.active_listings.return_value = [make_listing(1), make_listing(2)]
    store = ListingStore(":memory:")
    notifier = RecordingNotifier()

    assert cli.run_once(client, store, notifier, 42) == 2
    assert cli.run_once(client, store, notifier, 42) == 0
    assert notifier.calls == [[1, 2]]
    store.close()


def test_setup_logging_writes_file(tmp_path: Path, restore_logging: None) -> None:
    log_file = tmp_path / "etsy.log"
    cli.setup_logging(_settings(log_file=log_file, log_level="debug"))
    logging.getLogger("etsy_notify").debug("hello")

    assert "hello" in log_file.read_text()


@respx.mock
def test_main_polls_until_signal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    restore_signals: None,
    restore_logging: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    for key, value in {
        "ETSY_API_KEY": "key",
        "ETSY_SHARED_SECRET": "secret",
        "ETSY_SHOP_NAME": "someshop",
        "DB_PATH": str(tmp_path / "test.db"),
        "LOG_FILE": "",
    }.items():
        monkeypatch.setenv(key, value)
    respx.get(f"{BASE}shops").mock(
        return_value=httpx.Response(
            200, json={"count": 1, "results": [{"shop_id": 42, "shop_name": "someshop"}]}
        )
    )
    listings = respx.get(f"{BASE}shops/42/listings/active").mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(
                200, json={"count": 1, "results": [make_listing(1).model_dump(mode="json")]}
            ),
        ]
    )

    waits = 0

    def fake_wait(_self: object, _timeout: float) -> bool:
        nonlocal waits
        waits += 1
        if waits == 2:
            signal.raise_signal(signal.SIGTERM)
        return False

    with patch("threading.Event.wait", fake_wait):
        cli.main()

    assert listings.call_count == 2
    assert 'NOTIFY: listing ID 1 "Item 1"' in capsys.readouterr().out


def test_main_logs_unexpected_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    restore_signals: None,
    restore_logging: None,
) -> None:
    monkeypatch.chdir(tmp_path)
    log_file = tmp_path / "etsy.log"
    for key, value in {
        "ETSY_API_KEY": "key",
        "ETSY_SHARED_SECRET": "secret",
        "ETSY_SHOP_ID": "42",
        "DB_PATH": ":memory:",
        "LOG_FILE": str(log_file),
    }.items():
        monkeypatch.setenv(key, value)

    def boom(*_args: object) -> int:
        signal.raise_signal(signal.SIGINT)
        raise RuntimeError("boom")

    with (
        patch.object(cli, "run_once", boom),
        patch("threading.Event.wait", return_value=False),
    ):
        cli.main()

    assert "Unexpected error during poll" in log_file.read_text()
