from unittest.mock import patch

import httpx
import pytest
import respx

from shop_notify.etsy import EtsyClient, EtsyError

BASE = "https://openapi.etsy.com/v3/application/"


def _listing(i: int) -> dict[str, object]:
    return {
        "listing_id": i,
        "title": f"Item {i}",
        "url": f"https://etsy.com/listing/{i}",
        "last_modified_timestamp": 1_700_000_000,
        "price": {"amount": 100},
    }


@respx.mock
def test_active_listings_paginates_and_sends_api_key() -> None:
    route = respx.get(f"{BASE}shops/42/listings/active").mock(
        side_effect=[
            httpx.Response(200, json={"count": 150, "results": [_listing(i) for i in range(100)]}),
            httpx.Response(
                200, json={"count": 150, "results": [_listing(i) for i in range(100, 150)]}
            ),
        ]
    )
    with EtsyClient("key", "secret", base_url=BASE) as client:
        listings = list(client.active_listings(42))

    assert len(listings) == 150
    assert route.call_count == 2
    assert route.calls[0].request.headers["x-api-key"] == "key:secret"
    assert route.calls[1].request.url.params["offset"] == "100"


@respx.mock
def test_find_shop_id() -> None:
    respx.get(f"{BASE}shops", params={"shop_name": "someshop"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 2,
                "results": [
                    {"shop_id": 1, "shop_name": "someshopX"},
                    {"shop_id": 42, "shop_name": "SomeShop"},
                ],
            },
        )
    )
    with EtsyClient("key", "secret", base_url=BASE) as client:
        assert client.find_shop_id("someshop") == 42


@respx.mock
def test_find_shop_id_not_found() -> None:
    respx.get(f"{BASE}shops").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )
    with EtsyClient("key", "secret", base_url=BASE) as client, pytest.raises(EtsyError):
        client.find_shop_id("nope")


@respx.mock
def test_rate_limit_is_retried_after_delay() -> None:
    route = respx.get(f"{BASE}shops/42/listings/active").mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "7"}),
            httpx.Response(200, json={"count": 1, "results": [_listing(1)]}),
        ]
    )
    with (
        patch("shop_notify.etsy.time.sleep") as sleep,
        EtsyClient("key", "secret", base_url=BASE) as client,
    ):
        assert len(list(client.active_listings(42))) == 1

    sleep.assert_called_once_with(7.0)
    assert route.call_count == 2


@respx.mock
def test_network_error_raises_etsy_error() -> None:
    respx.get(f"{BASE}shops/42/listings/active").mock(side_effect=httpx.ConnectError("down"))
    with EtsyClient("key", "secret", base_url=BASE) as client, pytest.raises(EtsyError):
        list(client.active_listings(42))


@respx.mock
def test_invalid_shop_response_raises_etsy_error() -> None:
    respx.get(f"{BASE}shops").mock(return_value=httpx.Response(200, json={"oops": True}))
    with EtsyClient("key", "secret", base_url=BASE) as client, pytest.raises(EtsyError):
        client.find_shop_id("someshop")


@respx.mock
def test_rate_limit_without_valid_retry_after_uses_backoff() -> None:
    route = respx.get(f"{BASE}shops/42/listings/active").mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "soon"}),
            httpx.Response(429),
            httpx.Response(200, json={"count": 0, "results": []}),
        ]
    )
    with (
        patch("shop_notify.etsy.time.sleep") as sleep,
        EtsyClient("key", "secret", base_url=BASE) as client,
    ):
        assert list(client.active_listings(42)) == []

    assert [c.args[0] for c in sleep.call_args_list] == [1.0, 2.0]
    assert route.call_count == 3


@respx.mock
def test_rate_limit_gives_up_after_retries() -> None:
    respx.get(f"{BASE}shops/42/listings/active").mock(return_value=httpx.Response(429))
    with (
        patch("shop_notify.etsy.time.sleep"),
        EtsyClient("key", "secret", base_url=BASE, retries=1) as client,
        pytest.raises(EtsyError, match="429"),
    ):
        list(client.active_listings(42))


@respx.mock
def test_http_error_raises_etsy_error() -> None:
    respx.get(f"{BASE}shops/42/listings/active").mock(return_value=httpx.Response(403))
    with EtsyClient("key", "secret", base_url=BASE) as client, pytest.raises(EtsyError):
        list(client.active_listings(42))


@respx.mock
def test_invalid_json_raises_etsy_error() -> None:
    respx.get(f"{BASE}shops/42/listings/active").mock(return_value=httpx.Response(200, text="nope"))
    with EtsyClient("key", "secret", base_url=BASE) as client, pytest.raises(EtsyError):
        list(client.active_listings(42))
