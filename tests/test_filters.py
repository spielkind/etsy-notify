from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from shop_notify.filters import FilterError, Filters, Rule, split
from shop_notify.models import Listing, Money
from tests.helpers import make_listing


def titled(title: str, price: str | None = None) -> Listing:
    listing = make_listing(1).model_copy(update={"title": title})
    if price is not None:
        amount = int(Decimal(price) * 100)
        listing = listing.model_copy(
            update={"price": Money(amount=amount, divisor=100, currency_code="EUR")}
        )
    return listing


def test_no_filters_pass_everything() -> None:
    filters = Filters()
    assert not filters.active
    assert filters.check_title("anything").passed
    assert filters.describe() == []


def test_keyword_is_a_case_insensitive_substring() -> None:
    rule = Rule.keyword("  Gift Card ")
    assert rule.pattern == "Gift Card"
    assert rule.matches("Digital GIFT CARD for you")
    assert not rule.matches("Gift for card players")
    assert Rule.keyword("a.b").matches("A.B") and not Rule.keyword("a.b").matches("axb")
    assert str(rule) == "keyword 'Gift Card'"


def test_regex_is_case_insensitive_and_searches() -> None:
    rule = Rule.regex(r"^reserved\b")
    assert rule.matches("Reserved listing for Martin")
    assert not rule.matches("Unreserved joy")
    assert not rule.matches("Mug - reserved edition")
    assert str(rule) == r"regex '^reserved\b'"


@pytest.mark.parametrize(
    ("factory", "value", "message"),
    [
        (Rule.keyword, " ", "empty keyword"),
        (Rule.regex, "", "empty regular expression"),
        (Rule.regex, "(unclosed", "invalid regular expression '(unclosed'"),
        (Rule.regex, "\x08mug\x08", "single quotes"),
    ],
)
def test_invalid_rules(factory: object, value: str, message: str) -> None:
    with pytest.raises(FilterError, match=message.replace("(", r"\(")):
        factory(value)  # type: ignore[operator]


def test_exclude_wins_over_include() -> None:
    filters = Filters(include=(Rule.keyword("print"),), exclude=(Rule.regex(r"^reserved\b"),))
    assert filters.check_title("Mini art print").passed
    decision = filters.check_title("Reserved: mini art print")
    assert decision == type(decision)(False, r"exclude regex '^reserved\b'")
    assert filters.check_title("Original painting").reason == "no include filter matched"


def test_any_include_rule_is_enough() -> None:
    filters = Filters(include=(Rule.keyword("mug"), Rule.regex(r"\bvases?\b")))
    assert filters.check_title("Big mug").passed
    assert filters.check_title("Two vases").passed
    assert not filters.check_title("Bowl").passed


def test_price_limits() -> None:
    filters = Filters(min_price=Decimal(10), max_price=Decimal(50))
    assert filters.has_price_limits
    assert filters.check(titled("Mug", "10.00")).passed
    assert filters.check(titled("Mug", "50.00")).passed
    assert filters.check(titled("Mug", "9.99")).reason == "price 9.99 below minimum 10"
    assert filters.check(titled("Mug", "50.01")).reason == "price 50.01 above maximum 50"
    assert filters.check(titled("Mug")).passed  # no price: notified, so nothing is missed
    assert filters.describe() == ["price >= 10", "price <= 50"]


def test_min_price_above_max_price() -> None:
    with pytest.raises(FilterError, match="minimum price 20 is higher than maximum price 10"):
        Filters(min_price=Decimal(20), max_price=Decimal(10))


def test_split() -> None:
    filters = Filters(exclude=(Rule.keyword("reserved"),))
    keep, drop = split(filters, [titled("Mug"), titled("Reserved mug")])
    assert [item.title for item in keep] == ["Mug"]
    assert [(item.title, reason) for item, reason in drop] == [
        ("Reserved mug", "exclude keyword 'reserved'")
    ]


def test_from_settings_merges_environment_and_file(tmp_path: Path) -> None:
    config = tmp_path / "filters.yml"
    config.write_text(
        """
exclude:
  - keyword: gift card
  - regex: '\\bcustom order\\b'
include:
  - regex: '\\b(mug|vase)s?\\b'
price:
  max: 150
""",
        encoding="utf-8",
    )
    filters = Filters.from_settings(
        include="bowl",
        exclude="reserved, , sold out",
        exclude_regex=r"^hold\b",
        min_price=Decimal(10),
        max_price=Decimal(500),
        config=config,
    )
    assert filters.describe() == [
        "exclude keyword 'reserved'",
        "exclude keyword 'sold out'",
        r"exclude regex '^hold\b'",
        "exclude keyword 'gift card'",
        r"exclude regex '\bcustom order\b'",
        "include keyword 'bowl'",
        r"include regex '\b(mug|vase)s?\b'",
        "price >= 10",
        "price <= 150",
    ]
    assert Filters.from_settings(include_regex=" ").describe() == []


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("exclude:\n  - regex: '(unclosed'\n", r"exclude\[0\]: invalid regular expression"),
        ("include:\n  - keyword: a\n    regex: b\n", "exactly one of 'keyword' or 'regex'"),
        ("include:\n  - {}\n", "exactly one of 'keyword' or 'regex'"),
        ("includes:\n  - keyword: a\n", "includes: Extra inputs are not permitted"),
        ("price:\n  min: 20\n  max: 10\n", "minimum price 20 is higher than maximum price 10"),
        ("price:\n  min: cheap\n", "price.min"),
        ("- just a list\n", "top level"),
        ("exclude: [\n", "invalid YAML"),
    ],
)
def test_invalid_filter_file(tmp_path: Path, content: str, message: str) -> None:
    config = tmp_path / "filters.yml"
    config.write_text(content, encoding="utf-8")
    with pytest.raises(FilterError, match=message) as error:
        Filters.from_file(config)
    assert str(error.value).startswith(str(config))


def test_missing_filter_file(tmp_path: Path) -> None:
    with pytest.raises(FilterError, match="No such file"):
        Filters.from_file(tmp_path / "missing.yml")


def test_empty_filter_file(tmp_path: Path) -> None:
    config = tmp_path / "filters.yml"
    config.write_text("# nothing yet\n", encoding="utf-8")
    assert not Filters.from_file(config).active


def test_invalid_environment_filters() -> None:
    with pytest.raises(FilterError, match=r"^environment: invalid regular expression"):
        Filters.from_settings(exclude_regex="(")


@given(st.text(max_size=60), st.text(min_size=1, max_size=10).filter(str.strip))
def test_exclude_always_wins(title: str, word: str) -> None:
    filters = Filters(include=(Rule.regex(".*"),), exclude=(Rule.keyword(word),))
    decision = filters.check_title(f"{title}{word}{title}")
    assert not decision.passed
