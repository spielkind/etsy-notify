from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from apprise.decorators import notify

from shop_notify import __main__ as cli
from shop_notify.config import Settings

SENT: list[dict[str, Any]] = []

# A local copy of the sample image, so that no test downloads anything
SAMPLE_IMAGE = Path(__file__).parent.parent / "docs" / "sample-item.png"


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep the developer's .env, shell environment and the network out of the tests."""
    monkeypatch.chdir(tmp_path)
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    monkeypatch.delenv("WATCHDOG_USEC", raising=False)
    monkeypatch.setattr(cli, "SAMPLE_IMAGE_URL", str(SAMPLE_IMAGE))


@notify(on="shoptest", name="Shop Notify test target")  # type: ignore[untyped-decorator, no-untyped-call]
def _shoptest(body: str, title: str, notify_type: str, meta: dict[str, Any], **kwargs: Any) -> bool:
    attach = kwargs.get("attach")
    SENT.append(
        {
            "title": title,
            "body": body,
            "meta": meta,
            "attach": [a.name for a in attach] if attach else [],
        }
    )
    return meta.get("host") != "fail"


@pytest.fixture
def sent() -> Iterator[list[dict[str, Any]]]:
    SENT.clear()
    yield SENT
    SENT.clear()
