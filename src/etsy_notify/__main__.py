import logging
import signal
import threading
from types import FrameType
from typing import assert_never

from etsy_notify.config import NotifierType, Settings
from etsy_notify.db import ListingStore
from etsy_notify.etsy import EtsyClient, EtsyError
from etsy_notify.notifications import ConsoleNotifier, GmailNotifier, Notifier

log = logging.getLogger("etsy_notify")


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


def build_notifier(settings: Settings) -> Notifier:
    match settings.notifier:
        case NotifierType.CONSOLE:
            return ConsoleNotifier()
        case NotifierType.GMAIL:
            if not (settings.gmail_user and settings.gmail_password and settings.mail_to):
                raise SystemExit("GMAIL_USER, GMAIL_PASSWORD and MAIL_TO must be set for gmail")
            return GmailNotifier(
                user=settings.gmail_user,
                password=settings.gmail_password.get_secret_value(),
                sent_from=settings.mail_from or settings.gmail_user,
                sent_to=settings.mail_to,
            )
        case _:
            assert_never(settings.notifier)


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


def run_once(client: EtsyClient, store: ListingStore, notifier: Notifier, shop_id: int) -> int:
    listings = list(client.active_listings(shop_id))
    log.debug("Fetched %d active listings from shop %s", len(listings), shop_id)

    new_items = store.sync(listings)
    if new_items:
        notifier.notify(new_items)
        store.mark_as_notified(new_items)
        log.info("Notified %d new item(s)", len(new_items))
    else:
        log.info("No new items this time")
    return len(new_items)


def main() -> None:
    settings = Settings()
    setup_logging(settings)
    notifier = build_notifier(settings)

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
            while not stop.is_set():
                try:
                    run_once(client, store, notifier, shop_id)
                except EtsyError as e:
                    log.error("%s", e)
                except Exception:
                    log.exception("Unexpected error during poll")
                stop.wait(settings.poll_interval)
        finally:
            store.close()


if __name__ == "__main__":
    main()
