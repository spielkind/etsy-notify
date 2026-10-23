import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

import apprise
import jinja2
from apprise.plugins.email import NotifyEmail

from shop_notify.models import EVENTS, Listing, Money

log = logging.getLogger(__name__)

TEMPLATE_NAMES = (
    "subject.txt.j2",
    "body.txt.j2",
    "body.html.j2",
    "item_subject.txt.j2",
    "item_body.txt.j2",
)
# Telegram albums hold at most 10 photos
MAX_SUMMARY_IMAGES = 10


class Notifier(Protocol):
    @property
    def targets(self) -> list[str]:
        """Human-readable targets with credentials masked."""
        ...

    def notify(self, listings: Sequence[Listing], *, initial: bool = False) -> None:
        """Send ``listings``; ``initial`` marks the existing items found on the first run."""
        ...


class Sender(Protocol):
    """Sends an already rendered message, reporting the result per target."""

    def send(self, message: Message) -> list[Delivery]: ...


class NotificationError(Exception):
    """Raised when no notification target could be reached."""


@dataclass(frozen=True)
class Delivery:
    """Result of sending a notification to one target."""

    target: str
    ok: bool


@dataclass(frozen=True)
class _Target:
    name: str
    apprise: apprise.Apprise
    html: bool
    attachments: bool


@dataclass(frozen=True)
class ItemMessage:
    """Message about a single listing, sent with its image to push/chat services."""

    subject: str
    text: str
    image_url: str | None


@dataclass(frozen=True)
class Message:
    subject: str
    text: str
    html: str
    items: tuple[ItemMessage, ...] = ()


LANGUAGES = ("en", "de")
CURRENCY_SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£"}


def format_datetime(value: datetime, language: str) -> str:
    local = value.astimezone()
    if language == "de":
        return f"{local:%d.%m.%Y, %H:%M} Uhr"
    return f"{local:%b} {local.day}, {local:%Y, %H:%M}"


_UNITS = {
    "minute": ("minute", "minutes", "Minute", "Minuten", "Minuten"),
    "hour": ("hour", "hours", "Stunde", "Stunden", "Stunden"),
    "day": ("day", "days", "Tag", "Tage", "Tagen"),
    "week": ("week", "weeks", "Woche", "Wochen", "Wochen"),
}


def _rough(seconds: float) -> tuple[int, tuple[str, ...]]:
    minutes = max(round(seconds / 60), 0)
    hours, days = round(seconds / 3600), round(seconds / 86400)
    if minutes < 90:
        return minutes, _UNITS["minute"]
    if hours < 48:
        return hours, _UNITS["hour"]
    if days < 14:
        return days, _UNITS["day"]
    return round(days / 7), _UNITS["week"]


def format_ago(seconds: float, language: str) -> str:
    """Rough age, e.g. "3 days ago" / "vor 3 Tagen"."""
    value, unit = _rough(seconds)
    if language == "de":
        return f"vor {value} {unit[2] if value == 1 else unit[4]}"
    return f"{value} {unit[0] if value == 1 else unit[1]} ago"


def format_duration(seconds: float, language: str) -> str:
    """Rough duration, e.g. "3 days" / "3 Tage"."""
    value, unit = _rough(seconds)
    if language == "de":
        return f"{value} {unit[2] if value == 1 else unit[3]}"
    return f"{value} {unit[0] if value == 1 else unit[1]}"


# Per event: label in messages, item subject prefix, and the parts of the summary
TEXTS: dict[str, dict[str, dict[str, str]]] = {
    "en": {
        "label": {
            "back": "Back in the shop",
            "restocked": "Back in stock",
            "price_drop": "Price drop",
            "price_rise": "Price increase",
            "sold_out": "Sold out",
            "low_stock": "Almost sold out",
        },
        "subject": {
            "new": "New in",
            "back": "Back in",
            "restocked": "Back in stock in",
            "price_drop": "Price drop in",
            "price_rise": "Price increase in",
            "sold_out": "Sold out in",
            "low_stock": "Almost sold out in",
        },
        "summary": {
            "new": "{n} new",
            "back": "{n} back",
            "restocked": "{n} back in stock",
            "price_drop": "{n} price drop{s}",
            "price_rise": "{n} price increase{s}",
            "sold_out": "{n} sold out",
            "low_stock": "{n} almost sold out",
        },
        "words": {
            "and": "and",
            "was": "was",
            "last_seen": "last seen {date} ({ago})",
            "sold_out_for": "sold out for {duration}",
            "in_shop_since": "in the shop since {date}",
            "left": "only {n} left",
        },
    },
    "de": {
        "label": {
            "back": "Wieder im Shop",
            "restocked": "Wieder verfügbar",
            "price_drop": "Preissenkung",
            "price_rise": "Preiserhöhung",
            "sold_out": "Ausverkauft",
            "low_stock": "Fast ausverkauft",
        },
        "subject": {
            "new": "Neu in",
            "back": "Wieder in",
            "restocked": "Wieder verfügbar in",
            "price_drop": "Preissenkung in",
            "price_rise": "Preiserhöhung in",
            "sold_out": "Ausverkauft in",
            "low_stock": "Fast ausverkauft in",
        },
        "summary": {
            "new": "{n} neu",
            "back": "{n} wieder da",
            "restocked": "{n} wieder verfügbar",
            "price_drop": "{n} Preissenkung{en}",
            "price_rise": "{n} Preiserhöhung{en}",
            "sold_out": "{n} ausverkauft",
            "low_stock": "{n} fast ausverkauft",
        },
        "words": {
            "and": "und",
            "was": "vorher",
            "last_seen": "zuletzt gesehen {date} ({ago})",
            "sold_out_for": "{duration} ausverkauft",
            "in_shop_since": "im Shop seit {date}",
            "left": "nur noch {n}",
        },
    },
}


def _summary_up_to_1_2(new: int, back: int, language: str) -> str:
    """The wording of versions up to 1.2, for new items and items back in the shop."""
    if language == "de":
        items = f"{new} neue{'r' if new == 1 else ''} Artikel"
        if not back:
            return items
        return f"{items} und {back} wieder" if new else f"{back} Artikel wieder"
    items = f"{new} new item{'' if new == 1 else 's'}"
    if not back:
        return items
    return f"{items} and {back} back" if new else f"{back} item{'' if back == 1 else 's'} back"


def summarize(listings: Sequence[Listing], language: str) -> str:
    """E.g. "2 new items", "1 new item and 1 back", "1 back in stock and 2 price drops"."""
    counts: dict[str, int] = {}
    for item in listings:
        counts[item.kind] = counts.get(item.kind, 0) + 1
    if set(counts) <= {"new", "back"}:
        return _summary_up_to_1_2(counts.get("new", 0), counts.get("back", 0), language)
    texts = TEXTS[language]
    parts = [
        texts["summary"][kind].format(n=n, s="" if n == 1 else "s", en="" if n == 1 else "en")
        for kind in EVENTS
        if (n := counts.get(kind, 0))
    ]
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + f" {texts['words']['and']} " + parts[-1]


def price_note(item: Listing, language: str) -> str:
    """The earlier price, e.g. " (was €24.99)" or " (was €24.99, -20%)" for price changes."""
    notice = item.event
    if notice is None or notice.previous_price is None or item.price is None:
        return ""
    note = f"{TEXTS[language]['words']['was']} {format_money(notice.previous_price, language)}"
    old = notice.previous_price
    if item.kind in ("price_drop", "price_rise") and old.currency_code == item.price.currency_code:
        percent = round((item.price.value - old.value) / old.value * 100)
        sign = "+" if percent > 0 else "\u2212"
        note += f", {sign}{abs(percent)}{' ' if language == 'de' else ''}%"
    return f" ({note})"


def when(item: Listing, language: str) -> str:
    """The time information of an item, e.g. its listing date or "last seen …"."""
    words = TEXTS[language]["words"]
    notice = item.event
    if notice is not None and notice.kind == "back" and notice.last_seen:
        text = words["last_seen"].format(
            date=format_datetime(notice.last_seen, language),
            ago=format_ago(notice.gone_for, language),
        )
    elif notice is not None and notice.kind == "restocked" and notice.sold_out_since:
        text = words["sold_out_for"].format(duration=format_duration(notice.gone_for, language))
    elif notice is not None and notice.kind == "sold_out" and notice.first_seen:
        text = words["in_shop_since"].format(date=format_datetime(notice.first_seen, language))
    else:
        text = format_datetime(item.listed, language)
    if notice is not None and notice.quantity is not None:
        text += " · " + words["left"].format(n=notice.quantity)
    return text


def format_money(value: Money, language: str) -> str:
    symbol = CURRENCY_SYMBOLS.get(value.currency_code)
    number = f"{value.value:,.2f}"
    if language == "de":
        number = number.replace(",", "_").replace(".", ",").replace("_", ".")
        return f"{number} {symbol or value.currency_code}"
    return f"{symbol}{number}" if symbol else f"{number} {value.currency_code}"


class MessageRenderer:
    """Renders notification messages from Jinja2 templates.

    Templates in ``template_dir`` override the built-in ones of the same name; the
    built-in templates exist per language, with English as fallback.
    HTML templates (``*.html.j2``) are auto-escaped.
    """

    def __init__(
        self,
        template_dir: Path | None = None,
        shop_name: str | None = None,
        language: str = "en",
    ) -> None:
        if language not in LANGUAGES:
            raise ValueError(f"unsupported language {language!r}, use one of {LANGUAGES}")
        self.language = language
        loaders: list[jinja2.BaseLoader] = []
        if template_dir is not None:
            if not template_dir.is_dir():
                raise ValueError(f"template directory {template_dir} does not exist")
            loaders.append(jinja2.FileSystemLoader(template_dir))
        for lang in dict.fromkeys((language, "en")):
            loaders.append(jinja2.PackageLoader("shop_notify", f"templates/{lang}"))
        self._env = jinja2.Environment(
            loader=jinja2.ChoiceLoader(loaders),
            autoescape=lambda name: name is not None and name.endswith(".html.j2"),
            undefined=jinja2.StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._env.filters["localtime"] = lambda value: format_datetime(value, language)
        self._env.filters["money"] = lambda value: format_money(value, language)
        self._env.filters["ago"] = lambda value: format_ago(value, language)
        self._env.filters["duration"] = lambda value: format_duration(value, language)
        self._env.filters["summary"] = lambda value: summarize(value, language)
        self._env.filters["event_label"] = lambda item: TEXTS[language]["label"].get(item.kind, "")
        self._env.filters["subject_prefix"] = lambda item: TEXTS[language]["subject"][item.kind]
        self._env.filters["price_note"] = lambda item: price_note(item, language)
        self._env.filters["when"] = lambda item: when(item, language)
        self._shop_name = shop_name
        try:
            for name in TEMPLATE_NAMES:
                self._env.get_template(name)
        except jinja2.TemplateError as e:
            raise ValueError(f"invalid template: {e}") from e

    def render(
        self, listings: Sequence[Listing], *, initial: bool = False, test: bool = False
    ) -> Message:
        context = {
            "listings": listings,
            "shop_name": self._shop_name,
            "initial": initial,
            "test": test,
        }
        subject = self._env.get_template("subject.txt.j2").render(context).strip()
        items = tuple(
            ItemMessage(
                subject=self._env.get_template("item_subject.txt.j2")
                .render(context, item=item)
                .strip(),
                text=self._env.get_template("item_body.txt.j2").render(context, item=item).strip(),
                image_url=item.image_url,
            )
            for item in listings
        )
        return Message(
            subject=subject,
            text=self._env.get_template("body.txt.j2").render(context).strip(),
            html=self._env.get_template("body.html.j2").render(context, subject=subject),
            items=items,
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
        self.send(self._renderer.render(listings, initial=initial))

    def send(self, message: Message) -> list[Delivery]:
        print(f"{message.subject}\n\n{message.text}\n")
        return [Delivery("console", ok=True)]


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

    Every target is notified separately, so failures can be reported per target.
    E-mail targets get one HTML message with all items. Services that support
    attachments (ntfy, Telegram, …) get one message per item with its image, up to
    ``images_max`` items; above that, or for other services, one plain text message.
    """

    def __init__(
        self,
        *,
        urls: str | None = None,
        config: Path | None = None,
        renderer: MessageRenderer | None = None,
        images: bool = True,
        images_max: int = 5,
        images_in_summary: bool = False,
    ) -> None:
        self._renderer = renderer or MessageRenderer()
        self._images = images
        self._images_max = images_max
        self._images_in_summary = images_in_summary
        services = apprise.Apprise()
        if config is not None:
            if not config.is_file():
                raise ValueError(f"notification config {config} does not exist")
            apprise_config = apprise.AppriseConfig()
            apprise_config.add(str(config))
            services.add(apprise_config)
        if urls and not services.add(urls):
            raise ValueError("NOTIFY_URLS contains an invalid notification URL")
        if len(services) == 0:
            raise ValueError("no valid notification targets configured")

        self._targets: list[_Target] = []
        for service in services:
            single = apprise.Apprise()
            single.add(service)
            name = service.url(privacy=True).split("?", 1)[0]  # type: ignore[no-untyped-call]
            is_email = isinstance(service, NotifyEmail)
            self._targets.append(
                _Target(
                    name,
                    single,
                    html=is_email,
                    attachments=not is_email and bool(service.attachment_support),
                )
            )

    @property
    def targets(self) -> list[str]:
        """Configured targets with credentials masked, safe for logging."""
        return [target.name for target in self._targets]

    def send(self, message: Message) -> list[Delivery]:
        """Send a rendered message to every target and report the result per target."""
        images = _ImageCache()
        per_item = self._images and 0 < len(message.items) <= self._images_max
        deliveries = []
        for target in self._targets:
            if target.html:
                ok = self._notify(target, message.subject, message.html, html=True)
            elif target.attachments and per_item:
                results = [
                    self._notify(target, item.subject, item.text, attach=images.get(item.image_url))
                    for item in message.items
                ]
                ok = all(results)
            else:
                attach = None
                if target.attachments and self._images and self._images_in_summary:
                    attach = images.combined(
                        [item.image_url for item in message.items], MAX_SUMMARY_IMAGES
                    )
                ok = self._notify(target, message.subject, message.text, attach=attach)
            deliveries.append(Delivery(target.name, ok=ok))
        return deliveries

    @staticmethod
    def _notify(
        target: _Target,
        title: str,
        body: str,
        *,
        html: bool = False,
        attach: apprise.AppriseAttachment | None = None,
    ) -> bool:
        return bool(
            target.apprise.notify(
                title=title,
                body=body,
                body_format=apprise.NotifyFormat.HTML if html else apprise.NotifyFormat.TEXT,
                attach=attach,
            )
        )

    def notify(self, listings: Sequence[Listing], *, initial: bool = False) -> None:
        if not listings or initial:
            return
        deliveries = self.send(self._renderer.render(listings))
        failed = [d.target for d in deliveries if not d.ok]
        if len(failed) == len(deliveries):
            raise NotificationError(f"Sending notifications failed for all targets: {failed}")
        if failed:
            log.warning(
                "%d of %d notification targets failed: %s",
                len(failed),
                len(deliveries),
                ", ".join(failed),
            )
        else:
            log.info("Notified %d target(s)", len(deliveries))


class _ImageCache:
    """Loads each image once per notification; unavailable images are left out."""

    def __init__(self) -> None:
        self._cache: dict[str, apprise.AppriseAttachment | None] = {}

    def get(self, url: str | None) -> apprise.AppriseAttachment | None:
        if not url:
            return None
        if url not in self._cache:
            attachment = apprise.AppriseAttachment(url)
            # Accessing the attachment downloads it; send without image if that fails
            if attachment and all(attachment):
                self._cache[url] = attachment
            else:
                log.warning("Could not load image %s, sending without it", url)
                self._cache[url] = None
        return self._cache[url]

    def combined(self, urls: Sequence[str | None], limit: int) -> apprise.AppriseAttachment | None:
        combined = apprise.AppriseAttachment()
        for url in urls:
            if len(combined) >= limit:
                break
            attachment = self.get(url)
            if attachment is not None:
                combined.add(list(attachment))
        return combined if len(combined) else None
