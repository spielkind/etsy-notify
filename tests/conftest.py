from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from apprise.decorators import notify

from shop_notify.config import Settings

SENT: list[dict[str, Any]] = []


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep the developer's .env and shell environment out of the tests."""
    monkeypatch.chdir(tmp_path)
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    monkeypatch.delenv("WATCHDOG_USEC", raising=False)


@notify(on="shoptest", name="Shop Notify test target")  # type: ignore[untyped-decorator, no-untyped-call]
def _shoptest(body: str, title: str, notify_type: str, meta: dict[str, Any], **_: Any) -> bool:
    SENT.append({"title": title, "body": body, "meta": meta})
    return meta.get("host") != "fail"


@pytest.fixture
def sent() -> Iterator[list[dict[str, Any]]]:
    SENT.clear()
    yield SENT
    SENT.clear()
