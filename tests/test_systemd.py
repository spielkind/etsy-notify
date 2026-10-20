import os
import socket
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from shop_notify.systemd import SystemdNotifier, _socket_address


@pytest.fixture
def notify_socket() -> Iterator[tuple[str, socket.socket]]:
    # Unix socket paths are limited to ~100 characters, so avoid pytest's long tmp_path
    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        path = str(Path(directory) / "notify.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as server:
            server.bind(path)
            server.settimeout(1)
            yield path, server


def receive_all(server: socket.socket) -> list[str]:
    messages = []
    server.setblocking(False)
    try:
        while True:
            messages.append(server.recv(4096).decode())
    except BlockingIOError:
        pass
    return messages


def test_disabled_without_notify_socket() -> None:
    systemd = SystemdNotifier({})

    assert not systemd.enabled
    assert systemd.watchdog_interval is None
    systemd.ready("x")
    systemd.watchdog()


def test_sends_ready_status_watchdog_and_stopping(notify_socket: tuple[str, socket.socket]) -> None:
    path, server = notify_socket
    systemd = SystemdNotifier({"NOTIFY_SOCKET": path, "WATCHDOG_USEC": "60000000"})

    systemd.ready("Watching shop someshop")
    systemd.status("Last poll 12:00: 0 new item(s)")
    systemd.watchdog()
    systemd.stopping()

    assert systemd.enabled
    assert systemd.watchdog_interval == 30
    assert receive_all(server) == [
        "READY=1\nSTATUS=Watching shop someshop",
        "STATUS=Last poll 12:00: 0 new item(s)",
        "WATCHDOG=1",
        "STOPPING=1",
    ]


@pytest.mark.parametrize(
    "env",
    [
        {"WATCHDOG_USEC": "0"},
        {"WATCHDOG_USEC": "abc"},
        {"WATCHDOG_USEC": "60000000", "WATCHDOG_PID": "1"},
    ],
)
def test_watchdog_disabled_for_invalid_or_foreign_settings(
    notify_socket: tuple[str, socket.socket], env: dict[str, str]
) -> None:
    path, server = notify_socket
    systemd = SystemdNotifier({"NOTIFY_SOCKET": path, **env})

    systemd.watchdog()

    assert systemd.watchdog_interval is None
    assert receive_all(server) == []


def test_watchdog_enabled_for_own_pid(notify_socket: tuple[str, socket.socket]) -> None:
    path, _ = notify_socket
    env = {"NOTIFY_SOCKET": path, "WATCHDOG_USEC": "1000000", "WATCHDOG_PID": str(os.getpid())}

    assert SystemdNotifier(env).watchdog_interval == 0.5


def test_send_errors_are_ignored(tmp_path: Path) -> None:
    SystemdNotifier({"NOTIFY_SOCKET": str(tmp_path / "missing.sock")}).ready("x")


def test_abstract_socket_address() -> None:
    assert _socket_address("@systemd/notify") == "\0systemd/notify"
    assert _socket_address("/run/systemd/notify") == "/run/systemd/notify"
