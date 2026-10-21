from unittest.mock import patch

import httpx
import pytest
import respx

from shop_notify.etsy import EtsyClient, EtsyError, Quota

BASE = "https://openapi.etsy.com/v3/application/"


def _listing(i: int) -> dict[str, object]:
    return {
        "listing_id": i,
        "title": f"Item {i}",
        "url": f"https://etsy.com/listing/{i}",
        "last_modified_timestamp": 1_700_000_000,
        "price": {"amount": 100, "divisor": 100, "currency_code": "EUR"},
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
def test_listing_images_picks_main_image_in_batches() -> None:
    route = respx.get(f"{BASE}listings/batch").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "count": 2,
                    "results": [
                        {
                            "listing_id": 1,
                            "images": [
                                {"rank": 2, "url_570xN": "https://img/1b.jpg"},
                                {"rank": 1, "url_570xN": "https://img/1a.jpg"},
                            ],
                        },
                        {"listing_id": 2, "images": []},
                    ],
                },
            ),
            httpx.Response(200, json={"count": 1, "results": [{"listing_id": 150}]}),
        ]
    )
    with EtsyClient("key", "secret", base_url=BASE) as client:
        images = client.listing_images(list(range(1, 151)))

    assert images == {1: "https://img/1a.jpg"}
    assert route.call_count == 2
    params = route.calls[0].request.url.params
    assert params["includes"] == "Images"
    assert params["listing_ids"].split(",")[:3] == ["1", "2", "3"]
    assert len(params["listing_ids"].split(",")) == 100


@respx.mock
def test_listing_images_invalid_response() -> None:
    respx.get(f"{BASE}listings/batch").mock(return_value=httpx.Response(200, json={"x": 1}))
    with EtsyClient("key", "secret", base_url=BASE) as client, pytest.raises(EtsyError):
        client.listing_images([1])


@respx.mock
def test_quota_is_read_from_response_headers() -> None:
    respx.get(f"{BASE}shops/42/listings/active").mock(
        side_effect=[
            httpx.Response(200, json={"count": 0, "results": []}),
            httpx.Response(
                200,
                json={"count": 0, "results": []},
                headers={"x-remaining-today": "4711", "x-limit-per-day": "5000"},
            ),
            httpx.Response(
                200, json={"count": 0, "results": []}, headers={"x-remaining-today": "n/a"}
            ),
        ]
    )
    with EtsyClient("key", "secret", base_url=BASE) as client:
        list(client.active_listings(42))
        assert client.quota is None
        list(client.active_listings(42))
        assert client.quota == Quota(remaining=4711, limit=5000)
        assert client.quota is not None
        assert client.quota.fraction_left == pytest.approx(0.9422)
        list(client.active_listings(42))
        assert client.quota == Quota(remaining=4711, limit=5000)

    assert Quota(remaining=0, limit=0).fraction_left == 1.0


@respx.mock
def test_malformed_listings_are_skipped(caplog: pytest.LogCaptureFixture) -> None:
    broken_price = {**_listing(2), "price": {"amount": "lots"}}
    no_divisor = {**_listing(3), "price": {"amount": 500, "divisor": 0, "currency_code": "EUR"}}
    no_title = {k: v for k, v in _listing(4).items() if k != "title"}
    route = respx.get(f"{BASE}shops/42/listings/active").mock(
        side_effect=[
            httpx.Response(
                200,
                json={"count": 6, "results": [_listing(1), broken_price, no_title]},
            ),
            httpx.Response(200, json={"count": 6, "results": [no_divisor, {"oops": 1}, {}]}),
        ]
    )
    with EtsyClient("key", "secret", base_url=BASE) as client:
        listings = list(client.active_listings(42))

    assert [item.listing_id for item in listings] == [1, 2, 3]
    assert listings[1].price is None
    assert str(listings[2].price) == "500.00 EUR"
    assert route.call_count == 2
    assert route.calls[1].request.url.params["offset"] == "3"
    assert "Skipping malformed entry 4 from the Etsy API: title: Field required" in caplog.text
    assert "Skipping malformed entry without listing_id" in caplog.text


@respx.mock
def test_warns_if_no_listing_on_a_page_can_be_read(caplog: pytest.LogCaptureFixture) -> None:
    respx.get(f"{BASE}shops/42/listings/active").mock(
        return_value=httpx.Response(200, json={"count": 2, "results": [{"a": 1}, {"b": 2}]})
    )
    with EtsyClient("key", "secret", base_url=BASE) as client:
        assert list(client.active_listings(42)) == []

    assert "None of the 2 listings on this page could be read" in caplog.text


@respx.mock
def test_malformed_image_entries_are_skipped() -> None:
    respx.get(f"{BASE}listings/batch").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 2,
                "results": [
                    {"listing_id": 1, "images": [{"rank": 1}]},
                    {"listing_id": 2, "images": [{"rank": 1, "url_570xN": "https://img/2.jpg"}]},
                ],
            },
        )
    )
    with EtsyClient("key", "secret", base_url=BASE) as client:
        assert client.listing_images([1, 2]) == {2: "https://img/2.jpg"}


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
