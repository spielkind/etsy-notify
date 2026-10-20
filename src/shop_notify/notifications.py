import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

import apprise
import jinja2
from apprise.plugins.email import NotifyEmail

from shop_notify.models import Listing

log = logging.getLogger(__name__)

TEMPLATE_NAMES = ("subject.txt.j2", "body.txt.j2", "body.html.j2")


class Notifier(Protocol):
    @property
    def targets(self) -> list[str]:
        """Human-readable targets with credentials masked."""
        ...

    def notify(self, listings: Sequence[Listing], *, initial: bool = False) -> None:
        """Send ``listings``; ``initial`` marks the existing items found on the first run."""
        ...


class NotificationError(Exception):
    """Raised when no notification target could be reached."""


@dataclass(frozen=True)
class Message:
    subject: str
    text: str
    html: str


def _localtime(value: datetime) -> str:
    return f"{value.astimezone():%d.%m.%Y %H:%M}"


class MessageRenderer:
    """Renders notification messages from Jinja2 templates.

    Templates in ``template_dir`` override the built-in ones of the same name.
    HTML templates (``*.html.j2``) are auto-escaped.
    """

    def __init__(self, template_dir: Path | None = None, shop_name: str | None = None) -> None:
        loaders: list[jinja2.BaseLoader] = []
        if template_dir is not None:
            if not template_dir.is_dir():
                raise ValueError(f"template directory {template_dir} does not exist")
            loaders.append(jinja2.FileSystemLoader(template_dir))
        loaders.append(jinja2.PackageLoader("shop_notify", "templates"))
        self._env = jinja2.Environment(
            loader=jinja2.ChoiceLoader(loaders),
            autoescape=lambda name: name is not None and name.endswith(".html.j2"),
            undefined=jinja2.StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._env.filters["localtime"] = _localtime
        self._shop_name = shop_name
        try:
            for name in TEMPLATE_NAMES:
                self._env.get_template(name)
        except jinja2.TemplateError as e:
            raise ValueError(f"invalid template: {e}") from e

    def render(self, listings: Sequence[Listing], *, initial: bool = False) -> Message:
        context = {"listings": listings, "shop_name": self._shop_name, "initial": initial}
        subject = self._env.get_template("subject.txt.j2").render(context).strip()
        return Message(
            subject=subject,
            text=self._env.get_template("body.txt.j2").render(context).strip(),
            html=self._env.get_template("body.html.j2").render(context, subject=subject),
        )


class ConsoleNotifier:
    """Prints notifications to stdout.

    With ``first_run_only`` it only prints the existing items found on the first run,
    so you can see what was recorded while the real targets stay quiet.
    """

    def __init__(
        self, renderer: MessageRenderer | None = None, *, first_run_only: bool = False
    ) -> None:
        self._renderer = renderer or MessageRenderer()
        self._first_run_only = first_run_only

    @property
    def targets(self) -> list[str]:
        return ["console (first run only)" if self._first_run_only else "console"]

    def notify(self, listings: Sequence[Listing], *, initial: bool = False) -> None:
        if self._first_run_only and not initial:
            return
        message = self._renderer.render(listings, initial=initial)
        print(f"{message.subject}\n\n{message.text}\n")


class MultiNotifier:
    """Forwards notifications to several notifiers, e.g. console and Apprise."""

    def __init__(self, notifiers: Sequence[Notifier]) -> None:
        self._notifiers = list(notifiers)

    @property
    def targets(self) -> list[str]:
        return [target for notifier in self._notifiers for target in notifier.targets]

    def notify(self, listings: Sequence[Listing], *, initial: bool = False) -> None:
        for notifier in self._notifiers:
            notifier.notify(listings, initial=initial)


class AppriseNotifier:
    """Sends notifications to any service supported by Apprise.

    E-mail targets get the HTML message, all other services the plain text one.
    """

    def __init__(
        self,
        *,
        urls: str | None = None,
        config: Path | None = None,
        renderer: MessageRenderer | None = None,
    ) -> None:
        self._renderer = renderer or MessageRenderer()
        targets = apprise.Apprise()
        if config is not None:
            if not config.is_file():
                raise ValueError(f"notification config {config} does not exist")
            apprise_config = apprise.AppriseConfig()
            apprise_config.add(str(config))
            targets.add(apprise_config)
        if urls and not targets.add(urls):
            raise ValueError("NOTIFY_URLS contains an invalid notification URL")
        if len(targets) == 0:
            raise ValueError("no valid notification targets configured")

        self._services = list(targets)
        self._html_targets = apprise.Apprise()
        self._text_targets = apprise.Apprise()
        for service in self._services:
            group = self._html_targets if isinstance(service, NotifyEmail) else self._text_targets
            group.add(service)

    @property
    def targets(self) -> list[str]:
        """Configured targets with credentials masked, safe for logging."""
        return [
            service.url(privacy=True).split("?", 1)[0]  # type: ignore[no-untyped-call]
            for service in self._services
        ]

    def notify(self, listings: Sequence[Listing], *, initial: bool = False) -> None:
        if not listings or initial:
            return
        message = self._renderer.render(listings)
        results = []
        if len(self._html_targets):
            results.append(
                self._html_targets.notify(
                    title=message.subject,
                    body=message.html,
                    body_format=apprise.NotifyFormat.HTML,
                )
            )
        if len(self._text_targets):
            results.append(
                self._text_targets.notify(
                    title=message.subject,
                    body=message.text,
                    body_format=apprise.NotifyFormat.TEXT,
                )
            )

        succeeded = sum(r.success_count for r in results)
        failed = sum(r.failed_count + r.timeout_count for r in results)
        if not succeeded:
            raise NotificationError(f"Sending notifications failed: {results}")
        if failed:
            log.warning("%d of %d notification targets failed", failed, failed + succeeded)
        else:
            log.info("Notified %d target(s)", succeeded)
