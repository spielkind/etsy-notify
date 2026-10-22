import argparse
import logging
import signal
import sys
import threading
import time
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from types import FrameType
from typing import TypedDict

from shop_notify import __version__
from shop_notify.config import NotifySettings, Settings
from shop_notify.db import ListingStore, SyncResult
from shop_notify.etsy import EtsyClient, EtsyError
from shop_notify.filters import FilterError, Filters
from shop_notify.filters import split as split_listings
from shop_notify.models import Listing, Money
from shop_notify.notifications import (
    AppriseNotifier,
    ConsoleNotifier,
    Message,
    MessageRenderer,
    MultiNotifier,
    NotificationError,
    Notifier,
    Sender,
)
from shop_notify.systemd import SystemdNotifier

log = logging.getLogger("shop_notify")


class ImageOptions(TypedDict):
    images: bool
    images_max: int
    images_in_summary: bool


def setup_logging(settings: Settings) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if settings.log_file:
        handlers.append(logging.FileHandler(settings.log_file, encoding="utf-8"))
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    # Apprise logs full target URLs (including credentials) at debug level
    logging.getLogger("apprise").setLevel(logging.WARNING)
    # httpx logs every request at INFO; only show that when debugging
    if logging.getLogger().getEffectiveLevel() > logging.DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)


def image_options(settings: NotifySettings) -> ImageOptions:
    return {
        "images": settings.notify_images,
        "images_max": settings.notify_images_max,
        "images_in_summary": settings.notify_images_in_summary,
    }


def build_notifier(settings: Settings) -> Notifier:
    notifiers: list[Notifier] = []
    try:
        renderer = MessageRenderer(
            settings.notify_template_dir,
            shop_name=settings.etsy_shop_name,
            language=settings.notify_language,
        )
        if settings.notify_config is not None or settings.notify_urls is not None:
            urls = settings.notify_urls.get_secret_value() if settings.notify_urls else None
            notifiers.append(
                AppriseNotifier(
                    urls=urls,
                    config=settings.notify_config,
                    renderer=renderer,
                    **image_options(settings),
                )
            )
    except ValueError as e:
        raise SystemExit(f"Invalid notification configuration: {e}") from e

    console = settings.notify_console
    if console is True or (console == "auto" and not notifiers):
        notifiers.insert(0, ConsoleNotifier(renderer))
    elif console == "auto" and not settings.notify_existing_on_first_run:
        notifiers.insert(0, ConsoleNotifier(renderer, first_run_only=True))

    notifier = notifiers[0] if len(notifiers) == 1 else MultiNotifier(notifiers)
    log.info("Notification targets: %s", ", ".join(notifier.targets) or "none (log only)")
    return notifier


def load_filters(settings: NotifySettings) -> Filters:
    try:
        filters = settings.filters()
    except FilterError as e:
        raise SystemExit(f"Invalid filter configuration: {e}") from e
    if filters.active:
        log.info("Filters: %s", "; ".join(filters.describe()))
    return filters


def resolve_shop_id(client: EtsyClient, settings: Settings) -> int:
    if settings.etsy_shop_id is not None:
        return settings.etsy_shop_id
    assert settings.etsy_shop_name
    try:
        shop_id = client.find_shop_id(settings.etsy_shop_name)
    except EtsyError as e:
        raise SystemExit(f"Could not resolve shop {settings.etsy_shop_name!r}: {e}") from e
    log.info("Watching shop %s (ID %d)", settings.etsy_shop_name, shop_id)
    return shop_id


def add_images(client: EtsyClient, listings: Sequence[Listing]) -> list[Listing]:
    """Attach main image URLs; notifications are still sent if this fails."""
    try:
        images = client.listing_images([item.listing_id for item in listings])
    except EtsyError as e:
        log.warning("Could not load listing images: %s", e)
        return list(listings)
    return [item.model_copy(update={"image_url": images.get(item.listing_id)}) for item in listings]


QUOTA_WARNING_THRESHOLD = 0.2


def check_quota(client: EtsyClient) -> None:
    """Warn early when the daily Etsy request quota is running low."""
    quota = client.quota
    if quota is None:
        return
    if quota.fraction_left < QUOTA_WARNING_THRESHOLD:
        log.warning(
            "Only %d of %d Etsy API requests left today - consider a larger POLL_INTERVAL",
            quota.remaining,
            quota.limit,
        )
    else:
        log.debug("Etsy API requests left today: %d of %d", quota.remaining, quota.limit)


INCOMPLETE_WARNING_AFTER = 3600


def listings_complete(client: EtsyClient, store: ListingStore, forget_after: float) -> bool:
    """Whether to track missing listings, given how complete Etsy's response was.

    Etsy's count of active listings is sometimes ahead of the listings it returns. Such
    a response doesn't mark anything as missing; if it persists for longer than
    ``forget_after`` seconds, it is processed anyway so that nothing is blocked forever.
    """
    if client.listings_complete:
        return True
    since = store.incomplete_since()
    duration = 0.0 if since is None else time.time() - since.timestamp()
    counts = (client.listings_received, client.listings_reported)
    if duration > forget_after:
        log.warning(
            "Etsy has returned %d of %d active listings for %.0f h - processing it anyway",
            *counts,
            duration / 3600,
        )
        return True
    if duration > INCOMPLETE_WARNING_AFTER:
        log.warning(
            "Etsy has returned %d of %d active listings for %.0f min - "
            "missing listings are not tracked meanwhile",
            *counts,
            duration / 60,
        )
    else:
        log.info(
            "Etsy returned %d of %d active listings - not tracking missing listings this time",
            *counts,
        )
    return False


def select_to_notify(
    store: ListingStore, result: SyncResult, *, notify_back: bool, filters: Filters | None
) -> list[Listing]:
    """The pending listings that are notified; the others are recorded as skipped."""
    pending = result.pending
    if not notify_back:
        skipped = [item for item in pending if item.back]
        store.mark_as_notified(skipped, sent=False)
        for item in skipped:
            log.info("Back in the shop (not notified): %s (%s)", item.title, item.url)
        pending = [item for item in pending if not item.back]
    filters = filters or Filters()
    pending, filtered = split_listings(filters, pending)
    store.mark_as_filtered(filtered)
    result.filtered = len(filtered)
    for item, reason in filtered:
        log.info("Filtered (%s): %s (%s)", reason, item.title, item.url)
    passing = [item for item in result.refilter if filters.check(item).passed]
    for item in passing:
        log.info("Now passes the filters: %s (%s)", item.title, item.url)
    return pending + passing


def run_once(
    client: EtsyClient,
    store: ListingStore,
    notifier: Notifier,
    shop_id: int,
    *,
    notify_existing: bool = False,
    notify_back: bool = True,
    forget_after_hours: float = 24,
    filters: Filters | None = None,
) -> int:
    """Poll once and notify new items and items back in the shop.

    Returns the number of notified items. On the first run (empty database) the
    existing items are only recorded unless ``notify_existing`` is set; notifiers still
    receive them flagged as ``initial``. Items that don't pass the ``filters`` are
    recorded as filtered and checked again in every poll while they are in the shop, so
    they are notified once they pass (e.g. after a title change). Every poll is
    recorded, including failed ones.
    """
    try:
        listings = list(client.active_listings(shop_id))
    except EtsyError as e:
        store.record_poll(error=str(e))
        raise
    log.debug("Fetched %d active listings from shop %s", len(listings), shop_id)
    check_quota(client)

    forget_after = forget_after_hours * 3600
    first_run = store.is_empty()
    result = store.sync(
        listings,
        complete=listings_complete(client, store, forget_after),
        forget_after=forget_after,
    )
    for item in result.gone:
        log.info("No longer in the shop: %s (%s)", item.title, item.url)
    pending = select_to_notify(store, result, notify_back=notify_back, filters=filters)

    error = None
    try:
        if pending and first_run and not notify_existing:
            notifier.notify(pending, initial=True)
            store.mark_as_notified(pending, sent=False)
            log.info(
                "First run: %d existing item(s) recorded, "
                "notifications start with the next new item",
                len(pending),
            )
            return 0
        if pending:
            notifier.notify(add_images(client, pending))
            store.mark_as_notified(pending)
            for item in pending:
                if item.back:
                    log.info(
                        "Back in the shop: %s (%s), last seen %s",
                        item.title,
                        item.url,
                        f"{item.back.last_seen.astimezone():%Y-%m-%d %H:%M}",
                    )
                else:
                    log.info("New item: %s (%s)", item.title, item.url)
            log.info("Notified %d item(s)", len(pending))
        else:
            log.info("No new items this time")
        return len(pending)
    except NotificationError as e:
        error = str(e)
        raise
    finally:
        store.record_poll(
            reported=client.listings_reported,
            received=client.listings_received,
            complete=client.listings_complete,
            result=result,
            error=error,
        )


def healthcheck(settings: Settings, now: float | None = None) -> int:
    """Return 0 if the last successful poll is recent enough, 1 otherwise."""
    path = settings.heartbeat_path
    try:
        age = (time.time() if now is None else now) - path.stat().st_mtime
    except FileNotFoundError:
        print(f"unhealthy: no heartbeat yet ({path})")
        return 1
    if age > settings.heartbeat_max_age:
        print(f"unhealthy: last successful poll {age / 60:.0f} min ago")
        return 1
    print(f"healthy: last successful poll {age:.0f} s ago")
    return 0


def _now() -> str:
    return f"{datetime.now().astimezone():%H:%M}"


def _quota_status(client: EtsyClient) -> str:
    quota = client.quota
    return f", {quota.remaining}/{quota.limit} API requests left today" if quota else ""


def wait_for_next_poll(stop: threading.Event, seconds: float, systemd: SystemdNotifier) -> None:
    """Sleep until the next poll or a stop request, pinging the systemd watchdog meanwhile."""
    remaining = float(seconds)
    while remaining > 0 and not stop.is_set():
        chunk = min(remaining, systemd.watchdog_interval or remaining)
        stop.wait(chunk)
        remaining -= chunk
        systemd.watchdog()


def run(settings: Settings) -> None:
    setup_logging(settings)
    log.info("Shop Notify %s starting", __version__)
    notifier = build_notifier(settings)
    filters = load_filters(settings)
    systemd = SystemdNotifier()

    stop = threading.Event()

    def _handle_signal(signum: int, _frame: FrameType | None) -> None:
        log.info("Received %s, shutting down", signal.Signals(signum).name)
        stop.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    store = ListingStore(settings.db_path, poll_history_days=settings.poll_history_days)
    with EtsyClient(
        api_key=settings.etsy_api_key.get_secret_value(),
        shared_secret=settings.etsy_shared_secret.get_secret_value(),
        base_url=settings.etsy_api_endpoint,
    ) as client:
        try:
            shop_id = resolve_shop_id(client, settings)
            systemd.ready(f"Watching shop {settings.etsy_shop_name or shop_id}")
            while not stop.is_set():
                try:
                    new = run_once(
                        client,
                        store,
                        notifier,
                        shop_id,
                        notify_existing=settings.notify_existing_on_first_run,
                        notify_back=settings.notify_back,
                        forget_after_hours=settings.forget_after_hours,
                        filters=filters,
                    )
                    settings.heartbeat_path.touch()
                    systemd.status(f"Last poll {_now()}: {new} new item(s){_quota_status(client)}")
                except (EtsyError, NotificationError) as e:
                    log.error("%s", e)
                    systemd.status(f"Last poll {_now()} failed: {str(e)[:200]}")
                except Exception:
                    log.exception("Unexpected error during poll")
                    systemd.status(f"Last poll {_now()} failed with an unexpected error")
                wait_for_next_poll(stop, settings.poll_interval, systemd)
        finally:
            systemd.stopping()
            store.close()


SAMPLE_IMAGE_URL = (
    "https://raw.githubusercontent.com/spielkind/shop-notify/main/docs/sample-item.png"
)
PROJECT_URL = "https://github.com/spielkind/shop-notify"


SAMPLE_TITLES = {
    "en": ('Sample: hand-thrown mug "Morning dew"', "Sample: small vase in sage green (no image)"),
    "de": (
        "Muster: handgedrehte Tasse „Morgentau“",
        "Muster: kleine Vase in Salbeigrün (ohne Bild)",
    ),
}


def sample_listings(language: str = "en") -> list[Listing]:
    now = int(time.time())
    first, second = SAMPLE_TITLES.get(language, SAMPLE_TITLES["en"])
    return [
        Listing(
            listing_id=1,
            title=first,
            url=PROJECT_URL,
            last_modified_timestamp=now,
            price=Money(amount=2450, divisor=100, currency_code="EUR"),
            image_url=SAMPLE_IMAGE_URL,
        ),
        Listing(
            listing_id=2,
            title=second,
            url=PROJECT_URL,
            last_modified_timestamp=now,
            price=Money(amount=1800, divisor=100, currency_code="EUR"),
        ),
    ]


def build_test_senders(settings: NotifySettings, url: str | None) -> tuple[list[Sender], Message]:
    """Targets of a test notification: ``url`` only, or all configured ones."""
    renderer = MessageRenderer(
        settings.notify_template_dir,
        shop_name=settings.etsy_shop_name,
        language=settings.notify_language,
    )
    senders: list[Sender] = []
    if url:
        senders.append(AppriseNotifier(urls=url, renderer=renderer, **image_options(settings)))
    else:
        if settings.has_notify_targets:
            urls = settings.notify_urls.get_secret_value() if settings.notify_urls else None
            senders.append(
                AppriseNotifier(
                    urls=urls,
                    config=settings.notify_config,
                    renderer=renderer,
                    **image_options(settings),
                )
            )
        console = settings.notify_console
        if console is True or (console == "auto" and not senders):
            senders.insert(0, ConsoleNotifier(renderer))
    if not senders:
        raise ValueError("no notification targets configured (NOTIFY_CONSOLE=false)")
    return senders, renderer.render(sample_listings(renderer.language), test=True)


def test_notify(settings: NotifySettings, url: str | None = None) -> int:
    """Send a sample notification; 0 = all targets ok, 1 = some failed, 2 = config error."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("apprise").setLevel(logging.WARNING)
    try:
        senders, message = build_test_senders(settings, url)
    except ValueError as e:
        print(f"Invalid notification configuration: {e}", file=sys.stderr)
        return 2

    print(f"Sending a test notification with {len(sample_listings())} sample items …\n")
    deliveries = [delivery for sender in senders for delivery in sender.send(message)]
    print()
    for delivery in deliveries:
        print(f"  {'✓' if delivery.ok else '✗'} {delivery.target}")
    succeeded = sum(delivery.ok for delivery in deliveries)
    print(f"\n{succeeded} of {len(deliveries)} target(s) succeeded.")
    return 0 if succeeded == len(deliveries) else 1


_SINCE_UNITS = {"m": 60, "h": 3600, "d": 86400, "w": 7 * 86400}
_TIME_DETAILS = ("since", "last_seen", "created", "renewed", "active_since", "modified")


def parse_since(value: str) -> float:
    """Parse a period like ``30m``, ``12h``, ``7d`` or ``2w`` into seconds."""
    number, unit = value[:-1], value[-1:]
    if unit not in _SINCE_UNITS or not number.isdigit():
        raise argparse.ArgumentTypeError(f"invalid period {value!r}, use e.g. 12h, 7d or 2w")
    return int(number) * _SINCE_UNITS[unit]


def _local(value: datetime) -> str:
    return f"{value.astimezone():%Y-%m-%d %H:%M}"


def _format_details(details: dict[str, object]) -> str:
    parts = []
    for key, value in details.items():
        text = str(value)
        if key in _TIME_DETAILS and isinstance(value, int):
            text = _local(datetime.fromtimestamp(value))
        elif key == "seconds" and isinstance(value, int):
            text = f"{value / 3600:.1f} h"
        parts.append(f"{key}: {text}")
    return ", ".join(parts)


def history(
    settings: NotifySettings,
    listing_id: int | None = None,
    since: float | None = None,
    *,
    polls: bool = False,
) -> int:
    """Print the recorded events (or polls) from the database."""
    if not settings.db_path.is_file():
        print(f"No database at {settings.db_path} - has Shop Notify run yet?")
        return 1
    store = ListingStore(settings.db_path)
    try:
        if polls:
            start = time.time() - (since if since is not None else 86400)
            for poll in store.polls(since=start):
                if poll.error:
                    line = f"failed: {poll.error}"
                else:
                    counts = f"{poll.received}/{poll.reported} listings"
                    line = counts + ("" if poll.complete else " (incomplete)")
                    changes = {
                        "new": poll.new,
                        "back": poll.back,
                        "missing": poll.missing,
                        "gone": poll.gone,
                        "filtered": poll.filtered,
                    }
                    line += "".join(f", {n} {k}" for k, n in changes.items() if n)
                print(f"{_local(poll.time)}  {line}")
            return 0
        default = 7 * 86400 if listing_id is None else None
        period = since if since is not None else default
        start = 0 if period is None else time.time() - period
        events = store.events(listing_id=listing_id, since=start)
        if listing_id is not None and not events:
            print(f"Listing {listing_id} is not in the database")
            return 1
        for event in events:
            details = _format_details(event.details)
            line = f"{_local(event.time)}  {event.listing_id:>11}  {event.event:<13}  {event.title}"
            print(line + (f"  ({details})" if details else ""))
        return 0
    finally:
        store.close()


def check_filters(
    settings: NotifySettings,
    title: str | None = None,
    price: Decimal | None = None,
    since: float | None = None,
) -> int:
    """Show whether a title, or the titles seen in a period, pass the configured filters."""
    try:
        filters = settings.filters()
    except FilterError as e:
        print(f"Invalid filter configuration: {e}")
        return 1
    print("Filters: " + ("; ".join(filters.describe()) or "none - every item is notified"))
    if title is not None:
        checks = [(title, price, None if price is None else str(price))]
    else:
        if not settings.db_path.is_file():
            print(f"No database at {settings.db_path} - has Shop Notify run yet?")
            return 1
        store = ListingStore(settings.db_path)
        try:
            listings = store.seen_since(time.time() - (since or 0))
        finally:
            store.close()
        checks = [
            (item.title, item.price.value, str(item.price))
            if item.price
            else (item.title, None, None)
            for item in listings
        ]
    passed = 0
    for text, value, label in checks:
        decision = filters.check_title(text, value)
        passed += decision.passed
        shown = f"{text} ({label})" if label else text
        if decision.passed:
            print(f"  notify    {shown}")
        else:
            print(f"  filtered  {shown}  <- {decision.reason}")
    if title is None:
        print(f"{passed} of {len(checks)} item(s) would be notified")
    return 0


COMMANDS = {
    "run": "poll the shop (default)",
    "healthcheck": "exit 0 if the last poll was recent",
    "test-notify": "send a sample notification to all targets",
    "history": "show the recorded history of the listings",
    "check-filters": "show which titles the configured filters let through",
}


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="shop-notify", description="Watch a shop for new listings and send notifications."
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=list(COMMANDS),
        default="run",
        help="; ".join(f"{name}: {text}" for name, text in COMMANDS.items()),
    )
    parser.add_argument(
        "argument",
        nargs="?",
        metavar="LISTING_ID | TITLE",
        help="history: show the history of this listing; check-filters: check this title",
    )
    parser.add_argument(
        "--since",
        type=parse_since,
        metavar="PERIOD",
        help=(
            "history: events of this period, e.g. 12h, 7d, 2w (default: 7d, polls: 1d); "
            "check-filters: check the titles of the listings seen in this period"
        ),
    )
    parser.add_argument(
        "--polls", action="store_true", help="history only: show the polls instead of events"
    )
    parser.add_argument(
        "--price", type=Decimal, help="check-filters only: price of the title to check"
    )
    parser.add_argument(
        "--url", help="test-notify only: send to this Apprise URL instead of the configured targets"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)
    command = args.command
    if args.url and command != "test-notify":
        parser.error("--url can only be used with test-notify")
    if args.polls and command != "history":
        parser.error("--polls can only be used with history")
    if args.price is not None and command != "check-filters":
        parser.error("--price can only be used with check-filters")
    uses_argument = args.argument is not None or args.since is not None
    if uses_argument and command not in ("history", "check-filters"):
        parser.error(
            "a listing ID, a title or --since can only be used with history or check-filters"
        )

    if command == "test-notify":
        raise SystemExit(test_notify(NotifySettings(), args.url))
    if command == "history":
        if args.polls and args.argument is not None:
            parser.error("--polls can't be combined with a listing ID")
        if args.argument is not None and not args.argument.isdigit():
            parser.error(f"invalid listing ID {args.argument!r}")
        listing_id = int(args.argument) if args.argument is not None else None
        raise SystemExit(history(NotifySettings(), listing_id, args.since, polls=args.polls))
    if command == "check-filters":
        if (args.argument is None) == (args.since is None):
            parser.error("check-filters needs either a title or --since")
        raise SystemExit(check_filters(NotifySettings(), args.argument, args.price, args.since))
    settings = Settings()
    if command == "healthcheck":
        raise SystemExit(healthcheck(settings))
    run(settings)


if __name__ == "__main__":
    main()
