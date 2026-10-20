from collections.abc import Iterator
from typing import Any

import pytest
from apprise.decorators import notify

SENT: list[dict[str, Any]] = []


@notify(on="shoptest", name="Shop Notify test target")  # type: ignore[untyped-decorator, no-untyped-call]
def _shoptest(body: str, title: str, notify_type: str, meta: dict[str, Any], **_: Any) -> bool:
    SENT.append({"title": title, "body": body, "meta": meta})
    return meta.get("host") != "fail"


@pytest.fixture
def sent() -> Iterator[list[dict[str, Any]]]:
    SENT.clear()
    yield SENT
    SENT.clear()
