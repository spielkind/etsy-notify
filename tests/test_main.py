import logging
import signal
from collections.abc import Iterator, Sequence
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from shop_notify import __main__ as cli
from shop_notify.config import Settings
from shop_notify.db import ListingStore
from shop_notify.etsy import EtsyClient, EtsyError, Quota
from shop_notify.models import Listing
from shop_notify.notifications import AppriseNotifier, ConsoleNotifier, NotificationError
from shop_notify.systemd import SystemdNotifier
from tests.helpers import make_listing

BASE = "https://openapi.etsy.com/v3/application/"


def _client(quota: Quota | None = None) -> MagicMock:
    client = MagicMock(spec=EtsyClient)
    client.quota = quota
    return client


def test_check_quota_warns_when_low(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)

    cli.check_quota(_client())
    cli.check_quota(_client(Quota(remaining=4000, limit=5000)))
    assert "WARNING" not in caplog.text
    assert "4000 of 5000" in caplog.text

    cli.check_quota(_client(Quota(remaining=900, limit=5000)))
    assert "Only 900 of 5000 Etsy API requests left today" in caplog.text


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
        self.images: list[list[str | None]] = []

    def notify(self, listings: Sequence[Listing]) -> None:
        self.calls.append([item.listing_id for item in listings])
        self.images.append([item.image_url for item in listings])


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


def test_build_notifier_apprise(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    notifier = cli.build_notifier(_settings(notify_urls="mailtos://me:pw@gmail.com"))

    assert isinstance(notifier, AppriseNotifier)
    assert "mailtos://me:****@gmail.com/" in caplog.text
    assert ":pw@" not in caplog.text


def test_build_notifier_invalid_config_exits(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="Invalid notification configuration"):
        cli.build_notifier(_settings(notify_config=tmp_path / "missing.yml"))


def test_resolve_shop_id_prefers_configured_id() -> None:
    client = _client()

    assert cli.resolve_shop_id(client, _settings(etsy_shop_id=7)) == 7
    client.find_shop_id.assert_not_called()


def test_resolve_shop_id_by_name() -> None:
    client = _client()
    client.find_shop_id.return_value = 99

    settings = _settings(etsy_shop_id=None, etsy_shop_name="someshop")

    assert cli.resolve_shop_id(client, settings) == 99


def test_resolve_shop_id_not_found_exits() -> None:
    client = _client()
    client.find_shop_id.side_effect = EtsyError("not found")

    with pytest.raises(SystemExit, match="someshop"):
        cli.resolve_shop_id(client, _settings(etsy_shop_id=None, etsy_shop_name="someshop"))


def test_run_once_notifies_only_new_items(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    client = _client()
    client.active_listings.return_value = [make_listing(1), make_listing(2)]
    client.listing_images.return_value = {2: "https://img/2.jpg"}
    store = ListingStore(":memory:")
    notifier = RecordingNotifier()

    assert cli.run_once(client, store, notifier, 42) == 2
    assert cli.run_once(client, store, notifier, 42) == 0
    assert notifier.calls == [[1, 2]]
    assert notifier.images == [[None, "https://img/2.jpg"]]
    client.listing_images.assert_called_once_with([1, 2])
    assert "New item: Item 1 (https://www.etsy.com/listing/1)" in caplog.text
    assert "New item: Item 2 (https://www.etsy.com/listing/2)" in caplog.text
    store.close()


def test_run_once_does_not_log_items_if_notification_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    client = _client()
    client.active_listings.return_value = [make_listing(1)]
    client.listing_images.return_value = {}
    store = ListingStore(":memory:")
    notifier = MagicMock()
    notifier.notify.side_effect = NotificationError("all targets failed")

    with pytest.raises(NotificationError):
        cli.run_once(client, store, notifier, 42)

    assert "New item:" not in caplog.text
    assert [i.listing_id for i in store.sync([make_listing(1)])] == [1]
    store.close()


def test_run_once_notifies_without_images_if_loading_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = _client()
    client.active_listings.return_value = [make_listing(1)]
    client.listing_images.side_effect = EtsyError("boom")
    store = ListingStore(":memory:")
    notifier = RecordingNotifier()

    assert cli.run_once(client, store, notifier, 42) == 1
    assert notifier.images == [[None]]
    assert "Could not load listing images" in caplog.text
    store.close()


def test_setup_logging_writes_file(tmp_path: Path, restore_logging: None) -> None:
    log_file = tmp_path / "shop-notify.log"
    cli.setup_logging(_settings(log_file=log_file, log_level="debug"))
    logging.getLogger("shop_notify").debug("hello")

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
    respx.get(f"{BASE}listings/batch").mock(
        return_value=httpx.Response(200, json={"count": 1, "results": [{"listing_id": 1}]})
    )

    waits = 0

    def fake_wait(_self: object, _timeout: float) -> bool:
        nonlocal waits
        waits += 1
        if waits == 2:
            signal.raise_signal(signal.SIGTERM)
        return False

    with patch("threading.Event.wait", fake_wait):
        cli.main([])

    assert listings.call_count == 2
    assert "1 new item in someshop\n\nItem 1\n" in capsys.readouterr().out
    assert (tmp_path / "test.heartbeat").exists()


def test_main_logs_unexpected_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    restore_signals: None,
    restore_logging: None,
) -> None:
    monkeypatch.chdir(tmp_path)
    log_file = tmp_path / "shop-notify.log"
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
        cli.main([])

    assert "Unexpected error during poll" in log_file.read_text()


def test_heartbeat_defaults_next_to_db(tmp_path: Path) -> None:
    settings = _settings(db_path=tmp_path / "shop.db")
    assert settings.heartbeat_path == tmp_path / "shop.heartbeat"
    assert _settings(heartbeat_file=tmp_path / "hb").heartbeat_path == tmp_path / "hb"


def test_healthcheck_without_heartbeat(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.healthcheck(_settings(heartbeat_file=tmp_path / "hb")) == 1
    assert "no heartbeat yet" in capsys.readouterr().out


def test_healthcheck_fresh_and_stale(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    heartbeat = tmp_path / "hb"
    heartbeat.touch()
    mtime = heartbeat.stat().st_mtime
    settings = _settings(heartbeat_file=heartbeat, poll_interval=60)

    assert cli.healthcheck(settings, now=mtime + 10) == 0
    assert "healthy" in capsys.readouterr().out
    assert cli.healthcheck(settings, now=mtime + 181) == 1
    assert "3 min ago" in capsys.readouterr().out


def test_main_healthcheck_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for key, value in {
        "ETSY_API_KEY": "key",
        "ETSY_SHARED_SECRET": "secret",
        "ETSY_SHOP_ID": "42",
        "HEARTBEAT_FILE": str(tmp_path / "hb"),
    }.items():
        monkeypatch.setenv(key, value)

    with pytest.raises(SystemExit) as exc:
        cli.main(["healthcheck"])
    assert exc.value.code == 1

    (tmp_path / "hb").touch()
    with pytest.raises(SystemExit) as exc:
        cli.main(["healthcheck"])
    assert exc.value.code == 0


class FakeSystemd:
    def __init__(self, watchdog_interval: float | None) -> None:
        self.watchdog_interval = watchdog_interval
        self.pings = 0

    def watchdog(self) -> None:
        self.pings += 1


def test_wait_for_next_poll_pings_watchdog_in_chunks() -> None:
    stop = MagicMock()
    stop.is_set.return_value = False
    systemd = FakeSystemd(watchdog_interval=100)

    cli.wait_for_next_poll(stop, 250, systemd)  # type: ignore[arg-type]

    assert [c.args[0] for c in stop.wait.call_args_list] == [100, 100, 50]
    assert systemd.pings == 3


def test_wait_for_next_poll_without_watchdog_and_stop() -> None:
    stop = MagicMock()
    stop.is_set.side_effect = [False, True]
    systemd = FakeSystemd(watchdog_interval=None)

    cli.wait_for_next_poll(stop, 300, systemd)  # type: ignore[arg-type]

    stop.wait.assert_called_once_with(300)


def test_main_reports_to_systemd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    restore_signals: None,
    restore_logging: None,
) -> None:
    for key, value in {
        "ETSY_API_KEY": "key",
        "ETSY_SHARED_SECRET": "secret",
        "ETSY_SHOP_ID": "42",
        "DB_PATH": ":memory:",
        "HEARTBEAT_FILE": str(tmp_path / "hb"),
        "LOG_FILE": "",
    }.items():
        monkeypatch.setenv(key, value)
    messages: list[str] = []
    monkeypatch.setattr(SystemdNotifier, "_send", lambda _self, msg: messages.append(msg))

    results: list[int | Exception] = [2, EtsyError("403 not active"), RuntimeError("boom")]

    def fake_run_once(client: EtsyClient, *_args: object) -> int:
        client.quota = Quota(remaining=4711, limit=5000)
        result = results.pop(0)
        if not results:
            signal.raise_signal(signal.SIGTERM)
        if isinstance(result, Exception):
            raise result
        return result

    with (
        patch.object(cli, "run_once", fake_run_once),
        patch("threading.Event.wait", return_value=False),
    ):
        cli.main([])

    assert messages[0] == "READY=1\nSTATUS=Watching shop 42"
    assert messages[1].startswith("STATUS=Last poll ")
    assert messages[1].endswith(": 2 new item(s), 4711/5000 API requests left today")
    assert messages[2].endswith("failed: 403 not active")
    assert messages[3].endswith("failed with an unexpected error")
    assert messages[-1] == "STOPPING=1"
