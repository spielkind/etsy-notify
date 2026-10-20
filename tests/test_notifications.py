from pathlib import Path
from typing import Any

import pytest

from shop_notify.notifications import (
    AppriseNotifier,
    ConsoleNotifier,
    NotificationError,
    format_listings,
)
from tests.helpers import make_listing


def test_format_listings() -> None:
    body = format_listings([make_listing(1, "Tasse"), make_listing(2, "Schälchen")])

    assert "Schälchen 2" in body
    assert "https://www.etsy.com/listing/1" in body


def test_console_notifier(capsys: pytest.CaptureFixture[str]) -> None:
    ConsoleNotifier().notify([make_listing(3, "Vase")])
    assert capsys.readouterr().out == 'NOTIFY: listing ID 3 "Vase 3"\n'


def test_apprise_notifier_sends_to_all_urls(sent: list[dict[str, Any]]) -> None:
    notifier = AppriseNotifier(urls="shoptest://one, shoptest://two")

    notifier.notify([make_listing(1), make_listing(2)])

    assert [s["meta"]["host"] for s in sent] == ["one", "two"]
    assert sent[0]["title"] == "2 new Etsy item(s) available!"
    assert "https://www.etsy.com/listing/2" in sent[0]["body"]


def test_apprise_notifier_without_items_does_nothing(sent: list[dict[str, Any]]) -> None:
    AppriseNotifier(urls="shoptest://one").notify([])
    assert sent == []


def test_apprise_notifier_loads_yaml_config(tmp_path: Path, sent: list[dict[str, Any]]) -> None:
    config = tmp_path / "notify.yml"
    config.write_text(
        "version: 1\nurls:\n  - shoptest://family\n  - shoptest://friends:\n      - tag: friends\n"
    )
    notifier = AppriseNotifier(config=config, urls="shoptest://extra")

    notifier.notify([make_listing(1)])

    assert sorted(s["meta"]["host"] for s in sent) == ["extra", "family", "friends"]


def test_apprise_notifier_masks_credentials() -> None:
    notifier = AppriseNotifier(urls="mailtos://me:secret-pw@gmail.com?bcc=a@x.de")

    assert notifier.targets == ["mailtos://me:****@gmail.com/"]
    assert "secret-pw" not in " ".join(notifier.targets)


def test_apprise_notifier_partial_failure_is_tolerated(
    sent: list[dict[str, Any]], caplog: pytest.LogCaptureFixture
) -> None:
    AppriseNotifier(urls="shoptest://ok, shoptest://fail").notify([make_listing(1)])

    assert len(sent) == 2
    assert "Some notification targets failed" in caplog.text


def test_apprise_notifier_total_failure_raises(sent: list[dict[str, Any]]) -> None:
    with pytest.raises(NotificationError):
        AppriseNotifier(urls="shoptest://fail").notify([make_listing(1)])


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"urls": "nonsense://foo"}, "invalid notification URL"),
        ({"config": Path("/does/not/exist.yml")}, "does not exist"),
        ({}, "no valid notification targets"),
    ],
)
def test_apprise_notifier_rejects_invalid_config(kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        AppriseNotifier(**kwargs)


def test_apprise_notifier_rejects_empty_config_file(tmp_path: Path) -> None:
    config = tmp_path / "notify.yml"
    config.write_text("version: 1\nurls: []\n")
    with pytest.raises(ValueError, match="no valid notification targets"):
        AppriseNotifier(config=config)
