"""Minimal sd_notify(3) client: readiness, status text and watchdog pings for systemd."""

import logging
import os
import socket
from collections.abc import Mapping

log = logging.getLogger(__name__)


def _socket_address(value: str) -> str:
    # A leading "@" denotes a socket in the Linux abstract namespace
    return "\0" + value[1:] if value.startswith("@") else value


class SystemdNotifier:
    """Talks to systemd if started as a ``Type=notify`` service, otherwise does nothing."""

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        env = os.environ if environ is None else environ
        address = env.get("NOTIFY_SOCKET")
        self._address = _socket_address(address) if address else None
        self.watchdog_interval: float | None = None
        usec = env.get("WATCHDOG_USEC", "")
        pid = env.get("WATCHDOG_PID")
        if self._address and usec.isdigit() and int(usec) > 0 and pid in (None, str(os.getpid())):
            # Ping twice per watchdog period, as recommended by sd_watchdog_enabled(3)
            self.watchdog_interval = int(usec) / 1_000_000 / 2

    @property
    def enabled(self) -> bool:
        return self._address is not None

    def _send(self, message: str) -> None:
        if self._address is None:
            return
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
                sock.sendto(message.encode(), self._address)
        except OSError as e:
            log.debug("sd_notify failed: %s", e)

    def ready(self, status: str) -> None:
        self._send(f"READY=1\nSTATUS={status}")

    def status(self, status: str) -> None:
        self._send(f"STATUS={status}")

    def watchdog(self) -> None:
        if self.watchdog_interval is not None:
            self._send("WATCHDOG=1")

    def stopping(self) -> None:
        self._send("STOPPING=1")
