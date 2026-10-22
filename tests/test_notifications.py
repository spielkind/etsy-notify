import email
from datetime import UTC, datetime, timedelta
from email.message import Message as EmailMessage
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from shop_notify.models import Back, Listing, Money
from shop_notify.notifications import (
    AppriseNotifier,
    ConsoleNotifier,
    MessageRenderer,
    NotificationError,
    format_ago,
    format_datetime,
    format_money,
)
from tests.conftest import SAMPLE_IMAGE
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

    assert message.text.startswith("Tasse 1\n€12.50 · ")
    assert "https://www.etsy.com/listing/1" in message.text
    assert "\n\nVase 2\n" in message.text
    assert "€" not in message.text.split("Vase 2")[1]


def _back(listing: Listing, *, days: int = 30, previous: int | None = 2499) -> Listing:
    previous_price = Money(amount=previous, divisor=100, currency_code="EUR") if previous else None
    return listing.model_copy(
        update={
            "back": Back(
                last_seen=datetime.now(UTC) - timedelta(days=days),
                previous_price=previous_price,
            )
        }
    )


@pytest.mark.parametrize(
    ("language", "subjects", "line"),
    [
        (
            "en",
            ("1 item back in someshop", "1 new item and 1 back in someshop", "Back in someshop"),
            "Back in the shop · €12.50 (was €24.99) · last seen ",
        ),
        (
            "de",
            ("1 Artikel wieder in someshop", "1 neuer Artikel und 1 wieder in someshop", "Wieder"),
            "Wieder im Shop · 12,50 € (vorher 24,99 €) · zuletzt gesehen ",
        ),
    ],
)
def test_render_items_back_in_the_shop(
    language: str, subjects: tuple[str, str, str], line: str
) -> None:
    renderer = MessageRenderer(shop_name="someshop", language=language)
    back = _back(_rich_listing(1))

    message = renderer.render([back])
    assert message.subject == subjects[0]
    assert line in message.text
    assert message.items[0].subject.startswith(subjects[2])
    assert line in message.items[0].text
    assert "line-through" in message.html
    assert renderer.render([make_listing(2), back]).subject == subjects[1]


def test_render_item_back_without_price_change() -> None:
    message = MessageRenderer().render([_back(_rich_listing(1), previous=None, days=2)])
    assert "Back in the shop · €12.50 · last seen " in message.text
    assert "(2 days ago)" in message.text
    assert "line-through" not in message.html


@pytest.mark.parametrize(
    ("seconds", "en", "de"),
    [
        (-5, "0 minutes ago", "vor 0 Minuten"),
        (60, "1 minute ago", "vor 1 Minute"),
        (89 * 60, "89 minutes ago", "vor 89 Minuten"),
        (3 * 3600, "3 hours ago", "vor 3 Stunden"),
        (47 * 3600, "47 hours ago", "vor 47 Stunden"),
        (2 * 86400, "2 days ago", "vor 2 Tagen"),
        (86400 * 13, "13 days ago", "vor 13 Tagen"),
        (86400 * 14, "2 weeks ago", "vor 2 Wochen"),
        (86400 * 7 * 30, "30 weeks ago", "vor 30 Wochen"),
    ],
)
def test_format_ago(seconds: float, en: str, de: str) -> None:
    assert format_ago(seconds, "en") == en
    assert format_ago(seconds, "de") == de


def test_render_html_body() -> None:
    html = MessageRenderer().render([_rich_listing(1), make_listing(2, "Vase")]).html

    assert '<img src="https://i.etsystatic.com/1.jpg"' in html
    assert "€12.50" in html
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
    notifier = AppriseNotifier(urls="shoptest://one, shoptest://two", images=False)

    notifier.notify([make_listing(1), make_listing(2)])

    assert sorted(s["meta"]["host"] for s in sent) == ["one", "two"]
    assert sent[0]["title"] == "2 new items in the shop"
    assert "https://www.etsy.com/listing/2" in sent[0]["body"]
    assert "<html" not in sent[0]["body"]
    assert sent[0]["attach"] == []


# --- images ------------------------------------------------------------------


def _with_image(listing_id: int, image: Path | str | None = SAMPLE_IMAGE) -> Listing:
    return make_listing(listing_id).model_copy(update={"image_url": str(image) if image else None})


def test_one_message_per_item_with_image(sent: list[dict[str, Any]]) -> None:
    notifier = AppriseNotifier(urls="shoptest://push")

    notifier.notify([_with_image(1), _with_image(2, image=None)])

    assert [s["title"] for s in sent] == ["New in the shop: Item 1", "New in the shop: Item 2"]
    assert sent[0]["body"] == f"Item 1\n{sent[0]['body'].splitlines()[1]}\n" + (
        "https://www.etsy.com/listing/1"
    )
    assert sent[0]["attach"] == ["sample-item.png"]
    assert sent[1]["attach"] == []


def test_email_still_gets_one_html_message(sent: list[dict[str, Any]]) -> None:
    notifier = AppriseNotifier(urls="mailtos://me:pw@gmail.com, shoptest://push")
    with patch("smtplib.SMTP") as smtp:
        smtp.return_value.sendmail.return_value = {}
        notifier.notify([_with_image(1), _with_image(2)])

    smtp.return_value.sendmail.assert_called_once()
    assert len(sent) == 2


def test_unavailable_image_is_left_out(
    sent: list[dict[str, Any]], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    AppriseNotifier(urls="shoptest://push").notify([_with_image(1, tmp_path / "missing.jpg")])

    assert len(sent) == 1
    assert sent[0]["attach"] == []
    assert "Could not load image" in caplog.text


def test_summary_above_images_max(sent: list[dict[str, Any]]) -> None:
    notifier = AppriseNotifier(urls="shoptest://push", images_max=2)

    notifier.notify([_with_image(1), _with_image(2), _with_image(3)])

    assert len(sent) == 1
    assert sent[0]["title"] == "3 new items in the shop"
    assert sent[0]["attach"] == []


def test_summary_with_images(sent: list[dict[str, Any]], tmp_path: Path) -> None:
    images = []
    for n in range(12):
        image = tmp_path / f"img{n}.png"
        image.write_bytes(SAMPLE_IMAGE.read_bytes())
        images.append(_with_image(n, image))
    notifier = AppriseNotifier(urls="shoptest://push", images_max=2, images_in_summary=True)

    notifier.notify([_with_image(99, None), *images])

    assert len(sent) == 1
    assert sent[0]["attach"] == [f"img{n}.png" for n in range(10)]


def test_summary_with_images_but_none_available(sent: list[dict[str, Any]]) -> None:
    notifier = AppriseNotifier(urls="shoptest://push", images_max=1, images_in_summary=True)

    notifier.notify([_with_image(1, None), _with_image(2, None)])

    assert sent[0]["attach"] == []


def test_per_item_failure_marks_target_failed(sent: list[dict[str, Any]]) -> None:
    deliveries = AppriseNotifier(urls="shoptest://fail").send(
        MessageRenderer().render([_with_image(1), _with_image(2)])
    )

    assert len(sent) == 2
    assert [d.ok for d in deliveries] == [False]


def test_german_item_messages() -> None:
    message = MessageRenderer(shop_name="mabgraves", language="de").render(
        [_rich_listing(1)], test=True
    )

    assert message.items[0].subject == "[Test] Neu in mabgraves: Tasse 1"
    assert "12,50 €" in message.items[0].text


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
    assert "1 of 2 notification targets failed: shoptest://" in caplog.text


def test_apprise_notifier_send_reports_per_target(sent: list[dict[str, Any]]) -> None:
    notifier = AppriseNotifier(urls="shoptest://ok, shoptest://fail")

    deliveries = notifier.send(MessageRenderer().render([make_listing(1)]))

    assert sorted((d.target, d.ok) for d in deliveries) == [
        ("shoptest://", False),
        ("shoptest://", True),
    ]
    assert {s["meta"]["host"] for s in sent} == {"ok", "fail"}


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


# --- languages ---------------------------------------------------------------


def test_german_subjects() -> None:
    renderer = MessageRenderer(shop_name="mabgraves", language="de")
    one, two = [make_listing(1)], [make_listing(1), make_listing(2)]

    assert renderer.render(one).subject == "1 neuer Artikel in mabgraves"
    assert renderer.render(two).subject == "2 neue Artikel in mabgraves"
    assert renderer.render(two, test=True).subject == "[Test] 2 neue Artikel in mabgraves"
    assert renderer.render(two, initial=True).subject == (
        "Erster Lauf: 2 Artikel aktuell in mabgraves (gespeichert, nicht gemeldet)"
    )
    assert MessageRenderer(language="de").render(one).subject == "1 neuer Artikel in dem Shop"


def test_german_bodies() -> None:
    message = MessageRenderer(language="de").render([_rich_listing(1)])

    assert "12,50 €" in message.text
    assert " Uhr\n" in message.text
    assert '<html lang="de">' in message.html
    assert ">Ansehen<" in message.html
    assert "Gesendet von Shop Notify" in message.html


@pytest.mark.parametrize(
    ("language", "money", "expected"),
    [
        ("en", Money(amount=123456, divisor=100, currency_code="EUR"), "€1,234.56"),
        ("en", Money(amount=1800, divisor=100, currency_code="USD"), "$18.00"),
        ("en", Money(amount=990, divisor=100, currency_code="CHF"), "9.90 CHF"),
        ("de", Money(amount=123456, divisor=100, currency_code="EUR"), "1.234,56 €"),
        ("de", Money(amount=990, divisor=100, currency_code="CHF"), "9,90 CHF"),
    ],
)
def test_format_money(language: str, money: Money, expected: str) -> None:
    assert format_money(money, language) == expected


def test_format_datetime() -> None:
    value = datetime(2026, 10, 4, 7, 5, tzinfo=UTC).astimezone()
    local = value.astimezone()

    assert format_datetime(value, "en") == f"Oct {local.day}, 2026, {local:%H:%M}"
    assert format_datetime(value, "de") == f"{local:%d}.10.2026, {local:%H:%M} Uhr"


def test_unknown_language_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported language"):
        MessageRenderer(language="fr")


def test_custom_template_overrides_language_template(tmp_path: Path) -> None:
    (tmp_path / "subject.txt.j2").write_text("Eigener Betreff")

    message = MessageRenderer(tmp_path, language="de").render([_rich_listing(1)])

    assert message.subject == "Eigener Betreff"
    assert "12,50 €" in message.text
