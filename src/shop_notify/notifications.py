import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import apprise

from shop_notify.models import Listing

log = logging.getLogger(__name__)


class Notifier(Protocol):
    def notify(self, listings: Sequence[Listing]) -> None: ...


class NotificationError(Exception):
    """Raised when no notification target could be reached."""


def format_subject(listings: Sequence[Listing]) -> str:
    return f"{len(listings)} new Etsy item(s) available!"


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


class AppriseNotifier:
    """Sends notifications to any service supported by Apprise."""

    def __init__(self, *, urls: str | None = None, config: Path | None = None) -> None:
        self._apprise = apprise.Apprise()
        if config is not None:
            if not config.is_file():
                raise ValueError(f"notification config {config} does not exist")
            apprise_config = apprise.AppriseConfig()
            apprise_config.add(str(config))
            self._apprise.add(apprise_config)
        if urls and not self._apprise.add(urls):
            raise ValueError("NOTIFY_URLS contains an invalid notification URL")
        if len(self._apprise) == 0:
            raise ValueError("no valid notification targets configured")

    @property
    def targets(self) -> list[str]:
        """Configured targets with credentials masked, safe for logging."""
        return [
            service.url(privacy=True).split("?", 1)[0]  # type: ignore[no-untyped-call]
            for service in self._apprise
        ]

    def notify(self, listings: Sequence[Listing]) -> None:
        if not listings:
            return
        result = self._apprise.notify(
            title=format_subject(listings),
            body=format_listings(listings),
            body_format=apprise.NotifyFormat.TEXT,
        )
        if result.status == apprise.AppriseResultStatus.PARTIAL:
            log.warning("Some notification targets failed: %s", result)
        elif not result:
            raise NotificationError(f"Sending notifications failed: {result}")
        else:
            log.info("Notified %d target(s)", len(self._apprise))
