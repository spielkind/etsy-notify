import email
from email.message import Message as EmailMessage
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from shop_notify.models import Listing, Money
from shop_notify.notifications import (
    AppriseNotifier,
    ConsoleNotifier,
    MessageRenderer,
    NotificationError,
)
from tests.helpers import make_listing


def _rich_listing(listing_id: int = 1, title: str = "Tasse") -> Listing:
    return make_listing(listing_id, title).model_copy(
        update={
            "price": Money(amount=1250, divisor=100, currency_code="EUR"),
            "image_url": f"https://i.etsystatic.com/{listing_id}.jpg",
        }
    )


# --- rendering ---------------------------------------------------------------


def test_render_subject_with_shop_name() -> None:
    renderer = MessageRenderer(shop_name="someshop")

    assert renderer.render([make_listing(1)]).subject == "1 new item in someshop"
    assert renderer.render([make_listing(1), make_listing(2)]).subject == "2 new items in someshop"
    assert MessageRenderer().render([make_listing(1)]).subject == "1 new item in the shop"


def test_render_text_body() -> None:
    message = MessageRenderer().render([_rich_listing(1), make_listing(2, "Vase")])

    assert message.text.startswith("Tasse 1\n12.50 EUR · ")
    assert "https://www.etsy.com/listing/1" in message.text
    assert "\n\nVase 2\n" in message.text
    assert "EUR" not in message.text.split("Vase 2")[1]


def test_render_html_body() -> None:
    html = MessageRenderer().render([_rich_listing(1), make_listing(2, "Vase")]).html

    assert '<img src="https://i.etsystatic.com/1.jpg"' in html
    assert "12.50 EUR" in html
    assert 'href="https://www.etsy.com/listing/2"' in html
    assert html.count("<img") == 1


def test_html_escapes_listing_data() -> None:
    evil = make_listing(1, '<script>alert("x")</script>')

    message = MessageRenderer().render([evil])

    assert "<script>" not in message.html
    assert "&lt;script&gt;" in message.html
    assert "<script>" in message.text


def test_custom_template_dir_overrides_builtin(tmp_path: Path) -> None:
    (tmp_path / "subject.txt.j2").write_text("Neu: {{ listings | length }}")

    message = MessageRenderer(tmp_path).render([make_listing(1)])

    assert message.subject == "Neu: 1"
    assert "https://www.etsy.com/listing/1" in message.text


def test_invalid_templates_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        MessageRenderer(tmp_path / "missing")

    (tmp_path / "body.txt.j2").write_text("{% for x in %}")
    with pytest.raises(ValueError, match="invalid template"):
        MessageRenderer(tmp_path)


# --- notifiers ---------------------------------------------------------------


def test_console_notifier(capsys: pytest.CaptureFixture[str]) -> None:
    ConsoleNotifier().notify([make_listing(3, "Vase")])

    out = capsys.readouterr().out
    assert out.startswith("1 new item in the shop\n\nVase 3\n")


def test_apprise_notifier_sends_text_to_non_email_targets(sent: list[dict[str, Any]]) -> None:
    notifier = AppriseNotifier(urls="shoptest://one, shoptest://two")

    notifier.notify([make_listing(1), make_listing(2)])

    assert [s["meta"]["host"] for s in sent] == ["one", "two"]
    assert sent[0]["title"] == "2 new items in the shop"
    assert "https://www.etsy.com/listing/2" in sent[0]["body"]
    assert "<html" not in sent[0]["body"]


def _sent_mail(smtp: MagicMock) -> tuple[list[str], EmailMessage]:
    (_, to_addrs, raw), _ = smtp.return_value.sendmail.call_args
    return to_addrs, email.message_from_string(raw)


def _html_part(mail: EmailMessage) -> str:
    part = next(p for p in mail.walk() if p.get_content_type() == "text/html")
    payload = part.get_payload(decode=True)
    assert isinstance(payload, bytes)
    return payload.decode()


def test_apprise_notifier_sends_html_mail_with_bcc(sent: list[dict[str, Any]]) -> None:
    notifier = AppriseNotifier(urls="mailtos://me:pw@gmail.com?bcc=a@x.de,b@y.de, shoptest://push")
    with patch("smtplib.SMTP") as smtp:
        smtp.return_value.sendmail.return_value = {}
        notifier.notify([_rich_listing(1)])

    to_addrs, mail = _sent_mail(smtp)
    assert {"a@x.de", "b@y.de"} <= set(to_addrs)
    assert "a@x.de" not in mail.get("To", "")
    assert mail["Subject"] == "1 new item in the shop"
    assert "https://i.etsystatic.com/1.jpg" in _html_part(mail)
    assert len(sent) == 1
    assert "<html" not in sent[0]["body"]


def test_apprise_notifier_email_only() -> None:
    notifier = AppriseNotifier(urls="mailtos://me:pw@gmail.com")
    with patch("smtplib.SMTP") as smtp:
        smtp.return_value.sendmail.return_value = {}
        notifier.notify([make_listing(1)])

    smtp.return_value.sendmail.assert_called_once()


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


def test_apprise_notifier_partial_failure_is_tolerated(
    sent: list[dict[str, Any]], caplog: pytest.LogCaptureFixture
) -> None:
    AppriseNotifier(urls="shoptest://ok, shoptest://fail").notify([make_listing(1)])

    assert len(sent) == 2
    assert "1 of 2 notification targets failed" in caplog.text


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
