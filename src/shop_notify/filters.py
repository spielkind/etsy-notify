"""Filters that decide which new listings are notified.

Rules come from the environment (``NOTIFY_INCLUDE``, ``NOTIFY_EXCLUDE``,
``NOTIFY_INCLUDE_REGEX``, ``NOTIFY_EXCLUDE_REGEX``, ``NOTIFY_MIN_PRICE``,
``NOTIFY_MAX_PRICE``) and an optional YAML file (``FILTER_CONFIG``); both are merged.
See ``docs/filters.md``.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from shop_notify.models import Listing


class FilterError(ValueError):
    """Raised for invalid filter settings, with a message that names the culprit."""


@dataclass(frozen=True)
class Rule:
    """A keyword (case-insensitive substring) or a regular expression (case-insensitive)."""

    kind: Literal["keyword", "regex"]
    pattern: str
    _regex: re.Pattern[str] = field(repr=False, compare=False)

    @classmethod
    def keyword(cls, word: str) -> Self:
        if not word.strip():
            raise FilterError("empty keyword")
        word = word.strip()
        return cls("keyword", word, re.compile(re.escape(word), re.IGNORECASE))

    @classmethod
    def regex(cls, pattern: str) -> Self:
        if not pattern.strip():
            raise FilterError("empty regular expression")
        if any(ord(char) < 32 for char in pattern):
            raise FilterError(
                f"regular expression {pattern!r} contains a control character - in .env, "
                "put regular expressions in single quotes ('...'), as double quotes turn "
                "\\b and similar into control characters"
            )
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            raise FilterError(f"invalid regular expression {pattern!r}: {e}") from e
        return cls("regex", pattern, compiled)

    def matches(self, title: str) -> bool:
        return self._regex.search(title) is not None

    def __str__(self) -> str:
        return f"{self.kind} '{self.pattern}'"


@dataclass(frozen=True)
class Decision:
    passed: bool
    reason: str | None = None
    """Why the listing was filtered out (``None`` if it passed)."""


@dataclass(frozen=True)
class Filters:
    include: tuple[Rule, ...] = ()
    exclude: tuple[Rule, ...] = ()
    min_price: Decimal | None = None
    max_price: Decimal | None = None

    def __post_init__(self) -> None:
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise FilterError(
                f"minimum price {self.min_price} is higher than maximum price {self.max_price}"
            )

    @property
    def active(self) -> bool:
        return bool(self.include or self.exclude) or self.has_price_limits

    @property
    def has_price_limits(self) -> bool:
        return self.min_price is not None or self.max_price is not None

    def check(self, listing: Listing) -> Decision:
        """Decide whether ``listing`` is notified; excluding rules always win."""
        return self.check_title(listing.title, listing.price.value if listing.price else None)

    def check_title(self, title: str, price: Decimal | None = None) -> Decision:
        for rule in self.exclude:
            if rule.matches(title):
                return Decision(False, f"exclude {rule}")
        if self.include and not any(rule.matches(title) for rule in self.include):
            return Decision(False, "no include filter matched")
        # Listings without a (readable) price pass, so that nothing is missed
        if price is not None:
            if self.min_price is not None and price < self.min_price:
                return Decision(False, f"price {price} below minimum {self.min_price}")
            if self.max_price is not None and price > self.max_price:
                return Decision(False, f"price {price} above maximum {self.max_price}")
        return Decision(True)

    def describe(self) -> list[str]:
        """Human-readable summary of the active rules."""
        parts = [f"exclude {rule}" for rule in self.exclude]
        parts += [f"include {rule}" for rule in self.include]
        if self.min_price is not None:
            parts.append(f"price >= {self.min_price}")
        if self.max_price is not None:
            parts.append(f"price <= {self.max_price}")
        return parts

    def merge(self, other: Filters) -> Filters:
        """Combine two sets of filters; price limits of ``other`` take precedence."""
        return Filters(
            include=self.include + other.include,
            exclude=self.exclude + other.exclude,
            min_price=other.min_price if other.min_price is not None else self.min_price,
            max_price=other.max_price if other.max_price is not None else self.max_price,
        )

    @classmethod
    def from_settings(
        cls,
        *,
        include: str | None = None,
        exclude: str | None = None,
        include_regex: str | None = None,
        exclude_regex: str | None = None,
        min_price: Decimal | None = None,
        max_price: Decimal | None = None,
        config: Path | None = None,
    ) -> Filters:
        """Build the filters from the environment settings and the optional YAML file."""
        try:
            env = cls(
                include=_keywords(include) + _regex(include_regex),
                exclude=_keywords(exclude) + _regex(exclude_regex),
                min_price=min_price,
                max_price=max_price,
            )
        except FilterError as e:
            raise FilterError(f"environment: {e}") from e
        return env if config is None else env.merge(cls.from_file(config))

    @classmethod
    def from_file(cls, path: Path) -> Filters:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except OSError as e:
            raise FilterError(f"{path}: {e.strerror or e}") from e
        except yaml.YAMLError as e:
            raise FilterError(f"{path}: invalid YAML: {e}") from e
        return cls.from_dict(data or {}, source=str(path))

    @classmethod
    def from_dict(cls, data: object, *, source: str = "filters") -> Filters:
        try:
            spec = _FileSpec.model_validate(data)
        except ValidationError as e:
            problems = "; ".join(
                f"{'.'.join(map(str, err['loc'])) or 'top level'}: {err['msg']}"
                for err in e.errors()
            )
            raise FilterError(f"{source}: {problems}") from e

        def rules(section: str, specs: Sequence[_RuleSpec]) -> tuple[Rule, ...]:
            result = []
            for index, rule in enumerate(specs):
                try:
                    result.append(rule.to_rule())
                except FilterError as e:
                    raise FilterError(f"{source}: {section}[{index}]: {e}") from e
            return tuple(result)

        price = spec.price or _PriceSpec()
        try:
            return cls(
                include=rules("include", spec.include),
                exclude=rules("exclude", spec.exclude),
                min_price=price.min,
                max_price=price.max,
            )
        except FilterError as e:
            if str(e).startswith(source):
                raise
            raise FilterError(f"{source}: {e}") from e


def _keywords(value: str | None) -> tuple[Rule, ...]:
    if not value:
        return ()
    return tuple(Rule.keyword(word) for word in value.split(",") if word.strip())


def _regex(value: str | None) -> tuple[Rule, ...]:
    return (Rule.regex(value),) if value and value.strip() else ()


class _RuleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keyword: str | None = None
    regex: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        if (self.keyword is None) == (self.regex is None):
            raise ValueError("each entry needs exactly one of 'keyword' or 'regex'")
        return self

    def to_rule(self) -> Rule:
        return (
            Rule.keyword(self.keyword) if self.keyword is not None else Rule.regex(self.regex or "")
        )


class _PriceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: Decimal | None = None
    max: Decimal | None = None


class _FileSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include: list[_RuleSpec] = []
    exclude: list[_RuleSpec] = []
    price: _PriceSpec | None = None


def split(
    filters: Filters, listings: Iterable[Listing]
) -> tuple[list[Listing], list[tuple[Listing, str]]]:
    """Split listings into those that pass and those filtered out (with the reason)."""
    passed, filtered = [], []
    for item in listings:
        decision = filters.check(item)
        if decision.passed:
            passed.append(item)
        else:
            filtered.append((item, decision.reason or "filtered"))
    return passed, filtered
