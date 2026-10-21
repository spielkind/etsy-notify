"""Property-based tests: invariants that must hold for arbitrary input."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from hypothesis import given
from hypothesis import strategies as st
from markupsafe import escape

from shop_notify.etsy import _validate_each
from shop_notify.models import Listing, Money
from shop_notify.notifications import (
    CURRENCY_SYMBOLS,
    LANGUAGES,
    MessageRenderer,
    format_datetime,
    format_money,
)

languages = st.sampled_from(LANGUAGES)
money = st.builds(
    Money,
    amount=st.integers(min_value=0, max_value=10**12),
    divisor=st.sampled_from([1, 10, 100, 1000]),
    currency_code=st.sampled_from([*CURRENCY_SYMBOLS, "CHF", "JPY", "SEK"]),
)


def _parse(text: str, language: str, currency_code: str) -> Decimal:
    """Turn a formatted price back into a number."""
    for token in (CURRENCY_SYMBOLS.get(currency_code, ""), currency_code):
        if token:
            text = text.replace(token, "")
    text = text.strip()
    thousands, decimal = (".", ",") if language == "de" else (",", ".")
    return Decimal(text.replace(thousands, "").replace(decimal, "."))


@given(money, languages)
def test_format_money_keeps_the_value(value: Money, language: str) -> None:
    formatted = format_money(value, language)

    assert _parse(formatted, language, value.currency_code) == value.value.quantize(Decimal("0.01"))
    symbol = CURRENCY_SYMBOLS.get(value.currency_code)
    assert (symbol or value.currency_code) in formatted


@given(st.datetimes(timezones=st.just(UTC)), languages)
def test_format_datetime_never_fails(value: datetime, language: str) -> None:
    formatted = format_datetime(value, language)

    assert str(value.astimezone().year) in formatted


@given(st.text(min_size=1, max_size=200), languages)
def test_titles_are_always_escaped_in_html(title: str, language: str) -> None:
    listing = Listing(
        listing_id=1, title=title, url="https://example.com/1", last_modified_timestamp=0
    )

    message = MessageRenderer(language=language).render([listing])

    assert str(escape(title)) in message.html
    if "<" in title:
        assert title not in message.html
    # the text message is stripped, so leading/trailing whitespace may disappear
    assert title.strip() in message.text


json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(),
    lambda children: (
        st.lists(children, max_size=3) | st.dictionaries(st.text(max_size=10), children, max_size=3)
    ),
    max_leaves=10,
)
listing_like = st.fixed_dictionaries(
    {},
    optional={
        "listing_id": st.integers() | st.text(),
        "title": st.text() | st.integers(),
        "url": st.text(),
        "last_modified_timestamp": st.integers() | st.text(),
        "price": json_values,
    },
)


@given(st.lists(listing_like | st.dictionaries(st.text(), json_values), max_size=10))
def test_malformed_etsy_entries_never_break_a_poll(items: list[dict[str, Any]]) -> None:
    listings = _validate_each(Listing, items)

    assert all(isinstance(item, Listing) for item in listings)
    assert len(listings) <= len(items)
