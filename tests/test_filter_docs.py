"""The examples in docs/filters.md and filters.example.yml must stay correct."""

import re
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from shop_notify.filters import Filters

ROOT = Path(__file__).parent.parent
DOC = (ROOT / "docs" / "filters.md").read_text(encoding="utf-8")

# A ```yaml block, followed by a table whose header starts with "| Title |"
EXAMPLE = re.compile(
    r"```yaml\n(?P<yaml>(?:(?!```).)*)```\n+(?P<table>\| Title \|.*?)(?:\n\n|\Z)", re.S
)


def _examples() -> list[tuple[str, str, Decimal | None, bool]]:
    cases = []
    for match in EXAMPLE.finditer(DOC):
        header, _, *rows = match["table"].strip().splitlines()
        columns = [cell.strip() for cell in header.strip("|").split("|")]
        for row in rows:
            cells = dict(zip(columns, (c.strip() for c in row.strip("|").split("|")), strict=True))
            price = Decimal(cells["Price"]) if cells.get("Price") else None
            notified = {"yes": True, "no": False}[cells["Notified"]]
            cases.append((match["yaml"], cells["Title"], price, notified))
    return cases


EXAMPLES = _examples()


def test_examples_are_found() -> None:
    assert len(EXAMPLES) >= 30
    assert len({spec for spec, *_ in EXAMPLES}) == len(EXAMPLE.findall(DOC)) >= 8


@pytest.mark.parametrize(("spec", "title", "price", "notified"), EXAMPLES)
def test_documented_example(spec: str, title: str, price: Decimal | None, notified: bool) -> None:
    filters = Filters.from_dict(yaml.safe_load(spec))
    assert filters.check_title(title, price).passed is notified


def test_every_yaml_block_in_the_documentation_is_valid() -> None:
    for spec in re.findall(r"```yaml\n(.*?)```", DOC, re.S):
        data = yaml.safe_load(spec)
        if isinstance(data, dict) and "volumes" in data:
            continue  # compose.yaml snippet
        Filters.from_dict(data)


def test_example_file() -> None:
    filters = Filters.from_file(ROOT / "filters.example.yml")
    assert not filters.check_title("Reserved listing for Martin").passed
    assert not filters.check_title("Mini print - reserved for Anna").passed
    assert not filters.check_title("Gift card").passed
    assert filters.check_title("Mermaid Dreams - 5 x 7 Mini Art Print").passed
