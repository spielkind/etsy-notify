import logging
import time
from collections.abc import Iterator
from types import TracebackType
from typing import Self

import httpx
from pydantic import BaseModel

from etsy_notify.models import Listing

log = logging.getLogger(__name__)

PAGE_SIZE = 100  # maximum allowed by the Etsy v3 API
MAX_RETRY_AFTER = 300.0


class EtsyError(Exception):
    """Raised when the Etsy API cannot be queried successfully."""


class _ListingsPage(BaseModel):
    count: int
    results: list[Listing]


class _Shop(BaseModel):
    shop_id: int
    shop_name: str


class _ShopsPage(BaseModel):
    count: int
    results: list[_Shop]


class EtsyClient:
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

    def _get(self, path: str, params: dict[str, str | int]) -> httpx.Response:
        log.debug("Etsy API: GET %s %s", path, params)
        attempt = 0
        while True:
            try:
                response = self._client.get(path, params=params)
            except httpx.HTTPError as e:
                raise EtsyError(f"Request to {path} failed: {e}") from e

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
            try:
                page = _ListingsPage.model_validate_json(response.content)
            except ValueError as e:
                raise EtsyError(f"Invalid response from Etsy API: {e}") from e

            yield from page.results
            offset += len(page.results)
            if not page.results or offset >= page.count:
                return


def _retry_after(response: httpx.Response, default: float) -> float:
    try:
        delay = float(response.headers["retry-after"])
    except KeyError, ValueError:
        delay = default
    return min(max(delay, 0.0), MAX_RETRY_AFTER)
