import logging
import smtplib
from collections.abc import Sequence
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Protocol

from shop_notify.models import Listing

log = logging.getLogger(__name__)


class Notifier(Protocol):
    def notify(self, listings: Sequence[Listing]) -> None: ...


def format_listings(listings: Sequence[Listing]) -> str:
    lines = ["Hey, at least one new Etsy item is available:", ""]
    for item in listings:
        lines += [
            f"Date:  {item.last_modified.astimezone():%d.%m.%Y %H:%M:%S}",
            f"Title: {item.title}",
            f"URL:   {item.url}",
            "",
        ]
    return "\n".join(lines)


class ConsoleNotifier:
    """Prints notifications to stdout, useful for debugging."""

    def notify(self, listings: Sequence[Listing]) -> None:
        for item in listings:
            print(f'NOTIFY: listing ID {item.listing_id} "{item.title}"')


class GmailNotifier:
    def __init__(
        self,
        *,
        user: str,
        password: str,
        sent_from: str,
        sent_to: Sequence[str],
        host: str = "smtp.gmail.com",
        port: int = 465,
    ) -> None:
        self.user = user
        self.password = password
        self.sent_from = sent_from
        self.sent_to = list(sent_to)
        self.host = host
        self.port = port

    def build_message(self, listings: Sequence[Listing]) -> EmailMessage:
        msg = EmailMessage()
        msg["Subject"] = f"{len(listings)} new Etsy item(s) available!"
        msg["From"] = self.sent_from
        msg["To"] = ", ".join(self.sent_to)
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid()
        msg.set_content(format_listings(listings))
        return msg

    def notify(self, listings: Sequence[Listing]) -> None:
        if not listings:
            return
        msg = self.build_message(listings)
        with smtplib.SMTP_SSL(self.host, self.port, timeout=30) as server:
            server.login(self.user, self.password)
            server.send_message(msg)
        log.info("Email sent to %s", msg["To"])
