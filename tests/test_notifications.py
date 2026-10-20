from unittest.mock import MagicMock, patch

import pytest

from etsy_notify.notifications import ConsoleNotifier, GmailNotifier
from tests.helpers import make_listing


def _notifier() -> GmailNotifier:
    return GmailNotifier(
        user="me@gmail.com",
        password="pw",
        sent_from="Me <me@gmail.com>",
        sent_to=["a@x.de", "b@y.de"],
    )


def test_build_message() -> None:
    msg = _notifier().build_message([make_listing(1, "Tasse"), make_listing(2, "Schälchen")])

    assert msg["To"] == "a@x.de, b@y.de"
    assert msg["Subject"] == "2 new Etsy item(s) available!"
    body = msg.get_content()
    assert "Schälchen 2" in body
    assert "https://www.etsy.com/listing/1" in body


def test_notify_sends_via_smtp() -> None:
    with patch("etsy_notify.notifications.smtplib.SMTP_SSL") as smtp_cls:
        server = MagicMock()
        smtp_cls.return_value.__enter__.return_value = server
        _notifier().notify([make_listing(1)])

    server.login.assert_called_once_with("me@gmail.com", "pw")
    server.send_message.assert_called_once()


def test_notify_without_items_does_nothing() -> None:
    with patch("etsy_notify.notifications.smtplib.SMTP_SSL") as smtp_cls:
        _notifier().notify([])
    smtp_cls.assert_not_called()


def test_console_notifier(capsys: pytest.CaptureFixture[str]) -> None:
    ConsoleNotifier().notify([make_listing(3, "Vase")])
    assert capsys.readouterr().out == 'NOTIFY: listing ID 3 "Vase 3"\n'
