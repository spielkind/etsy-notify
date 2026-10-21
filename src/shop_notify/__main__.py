import argparse
import logging
import signal
import sys
import threading
import time
from collections.abc import Sequence
from datetime import datetime
from types import FrameType

from shop_notify import __version__
from shop_notify.config import NotifySettings, Settings
from shop_notify.db import ListingStore
from shop_notify.etsy import EtsyClient, EtsyError
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
                AppriseNotifier(urls=urls, config=settings.notify_config, renderer=renderer)
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


def run_once(
    client: EtsyClient,
    store: ListingStore,
    notifier: Notifier,
    shop_id: int,
    *,
    notify_existing: bool = False,
) -> int:
    """Poll once and notify new items; returns the number of notified items.

    On the first run (empty database) the existing items are only recorded unless
    ``notify_existing`` is set; notifiers still receive them flagged as ``initial``.
    """
    listings = list(client.active_listings(shop_id))
    log.debug("Fetched %d active listings from shop %s", len(listings), shop_id)
    check_quota(client)

    first_run = store.is_empty()
    new_items = store.sync(listings)
    if new_items and first_run and not notify_existing:
        notifier.notify(new_items, initial=True)
        store.mark_as_notified(new_items)
        log.info(
            "First run: %d existing item(s) recorded, notifications start with the next new item",
            len(new_items),
        )
        return 0
    if new_items:
        notifier.notify(add_images(client, new_items))
        store.mark_as_notified(new_items)
        for item in new_items:
            log.info("New item: %s (%s)", item.title, item.url)
        log.info("Notified %d new item(s)", len(new_items))
    else:
        log.info("No new items this time")
    return len(new_items)


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
    systemd = SystemdNotifier()

    stop = threading.Event()

    def _handle_signal(signum: int, _frame: FrameType | None) -> None:
        log.info("Received %s, shutting down", signal.Signals(signum).name)
        stop.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    store = ListingStore(settings.db_path)
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
        senders.append(AppriseNotifier(urls=url, renderer=renderer))
    else:
        if settings.has_notify_targets:
            urls = settings.notify_urls.get_secret_value() if settings.notify_urls else None
            senders.append(
                AppriseNotifier(urls=urls, config=settings.notify_config, renderer=renderer)
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


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="shop-notify", description="Watch a shop for new listings and send notifications."
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["run", "healthcheck", "test-notify"],
        default="run",
        help=(
            "run: poll the shop (default); healthcheck: exit 0 if the last poll was recent; "
            "test-notify: send a sample notification to all targets"
        ),
    )
    parser.add_argument(
        "--url", help="test-notify only: send to this Apprise URL instead of the configured targets"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)
    if args.url and args.command != "test-notify":
        parser.error("--url can only be used with test-notify")

    if args.command == "test-notify":
        raise SystemExit(test_notify(NotifySettings(), args.url))
    settings = Settings()
    if args.command == "healthcheck":
        raise SystemExit(healthcheck(settings))
    run(settings)


if __name__ == "__main__":
    main()
