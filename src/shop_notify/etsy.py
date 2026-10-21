import contextlib
import logging
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self

import httpx
from pydantic import BaseModel, ValidationError

from shop_notify.models import Listing

log = logging.getLogger(__name__)

PAGE_SIZE = 100  # maximum allowed by the Etsy v3 API
MAX_RETRY_AFTER = 300.0


class EtsyError(Exception):
    """Raised when the Etsy API cannot be queried successfully."""


class _RawPage(BaseModel):
    """A page of results that are validated one by one."""

    count: int = 0
    results: list[dict[str, Any]]


class _Shop(BaseModel):
    shop_id: int
    shop_name: str


class _ShopsPage(BaseModel):
    count: int
    results: list[_Shop]


class _ListingImage(BaseModel):
    rank: int = 0
    url_570xN: str  # noqa: N815 (Etsy field name)


class _ListingWithImages(BaseModel):
    listing_id: int
    images: list[_ListingImage] | None = None


@dataclass(frozen=True)
class Quota:
    """Daily request quota as reported by the Etsy API response headers."""

    remaining: int
    limit: int

    @property
    def fraction_left(self) -> float:
        return self.remaining / self.limit if self.limit else 1.0


class EtsyClient:
    quota: Quota | None = None
    """Daily quota from the most recent response, if Etsy reported it."""

    def __init__(
        self,
        api_key: str,
        shared_secret: str,
        base_url: str = "https://openapi.etsy.com/v3/application/",
        timeout: float = 30.0,
        retries: int = 3,
    ) -> None:
        self._retries = retries
        self._client = httpx.Client(
            base_url=base_url,
            headers={"x-api-key": f"{api_key}:{shared_secret}"},
            timeout=timeout,
            transport=httpx.HTTPTransport(retries=retries),
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _update_quota(self, response: httpx.Response) -> None:
        with contextlib.suppress(KeyError, ValueError):
            self.quota = Quota(
                remaining=int(response.headers["x-remaining-today"]),
                limit=int(response.headers["x-limit-per-day"]),
            )

    def _get(self, path: str, params: dict[str, str | int]) -> httpx.Response:
        log.debug("Etsy API: GET %s %s", path, params)
        attempt = 0
        while True:
            try:
                response = self._client.get(path, params=params)
            except httpx.HTTPError as e:
                raise EtsyError(f"Request to {path} failed: {e}") from e
            self._update_quota(response)

            if response.status_code != httpx.codes.TOO_MANY_REQUESTS or attempt >= self._retries:
                break
            delay = _retry_after(response, default=2.0**attempt)
            log.warning("Rate limited by Etsy, retrying in %.0f s", delay)
            time.sleep(delay)
            attempt += 1

        if response.is_error:
            raise EtsyError(
                f"Unexpected status {response.status_code} from {response.request.url}: "
                f"{response.text}"
            )
        return response

    def find_shop_id(self, shop_name: str) -> int:
        """Resolve a shop name (as in etsy.com/shop/<name>) to its numeric shop ID."""
        response = self._get("shops", {"shop_name": shop_name})
        try:
            page = _ShopsPage.model_validate_json(response.content)
        except ValueError as e:
            raise EtsyError(f"Invalid response from Etsy API: {e}") from e

        for shop in page.results:
            if shop.shop_name.casefold() == shop_name.casefold():
                return shop.shop_id
        raise EtsyError(f"Shop {shop_name!r} not found")

    def listing_images(self, listing_ids: Sequence[int]) -> dict[int, str]:
        """Return the URL of the main image (570px wide) for each listing that has one."""
        images: dict[int, str] = {}
        for start in range(0, len(listing_ids), PAGE_SIZE):
            chunk = listing_ids[start : start + PAGE_SIZE]
            response = self._get(
                "listings/batch",
                {"listing_ids": ",".join(map(str, chunk)), "includes": "Images"},
            )
            page = _parse_page(response)
            for listing in _validate_each(_ListingWithImages, page.results):
                if listing.images:
                    main = min(listing.images, key=lambda image: image.rank)
                    images[listing.listing_id] = main.url_570xN
        return images

    def active_listings(self, shop_id: int) -> Iterator[Listing]:
        """Yield all active listings of a shop, newest first, following pagination."""
        offset = 0
        while True:
            response = self._get(
                f"shops/{shop_id}/listings/active",
                {
                    "sort_on": "created",
                    "sort_order": "desc",
                    "limit": PAGE_SIZE,
                    "offset": offset,
                },
            )
            page = _parse_page(response)
            listings = _validate_each(Listing, page.results)
            if page.results and not listings:
                log.warning(
                    "None of the %d listings on this page could be read - "
                    "has the Etsy API changed?",
                    len(page.results),
                )
            yield from listings
            offset += len(page.results)
            if not page.results or offset >= page.count:
                return


def _retry_after(response: httpx.Response, default: float) -> float:
    try:
        delay = float(response.headers["retry-after"])
    except KeyError, ValueError:
        delay = default
    return min(max(delay, 0.0), MAX_RETRY_AFTER)


def _parse_page(response: httpx.Response) -> _RawPage:
    try:
        return _RawPage.model_validate_json(response.content)
    except ValueError as e:
        raise EtsyError(f"Invalid response from Etsy API: {e}") from e


def _validate_each[M: BaseModel](model: type[M], items: list[dict[str, Any]]) -> list[M]:
    """Validate items individually; skip (and log) the ones that don't fit."""
    valid = []
    for item in items:
        try:
            valid.append(model.model_validate(item))
        except ValidationError as e:
            log.warning(
                "Skipping malformed entry %s from the Etsy API: %s",
                item.get("listing_id", "without listing_id"),
                "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()),
            )
    return valid
