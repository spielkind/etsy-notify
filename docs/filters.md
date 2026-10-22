# Filters

Filters decide which new items you are notified about – for example to skip
*reserved listings* that a shop owner creates for a single buyer, or to watch only
certain products or a price range. Without filters, every new item is notified.

- [Quick start](#quick-start)
- [How filters work](#how-filters-work)
- [Setting filters in `.env`](#setting-filters-in-env)
- [Setting filters in `filters.yml`](#setting-filters-in-filtersyml)
- [Keyword or regular expression?](#keyword-or-regular-expression)
- [Regular expressions in a nutshell](#regular-expressions-in-a-nutshell)
- [Examples](#examples)
- [Testing filters](#testing-filters)
- [What happens to filtered items](#what-happens-to-filtered-items)
- [Troubleshooting](#troubleshooting)

## Quick start

Skip reserved listings such as *"Reserved listing for Martin"* – add this line to your
`.env` and restart Shop Notify:

```sh
NOTIFY_EXCLUDE_REGEX='^reserved\b'
```

Check it before restarting:

```sh
shop-notify check-filters "Reserved listing for Martin"
# Filters: exclude regex '^reserved\b'
#   filtered  Reserved listing for Martin  <- exclude regex '^reserved\b'
```

In Docker: `docker compose exec shop-notify shop-notify check-filters "…"` (after
changing `.env`, run `docker compose up -d` so that the container picks it up).

## How filters work

A filter checks the **title** of an item (and optionally its **price**). There are two
kinds of rules:

- **Keyword:** the title contains this text, e.g. `gift card`.
- **Regular expression (regex):** the title matches this pattern, e.g. `^reserved\b`
  ("starts with the word *reserved*").

Rules are used in two ways:

- **exclude:** items matching **any** exclude rule are **not** notified.
- **include:** if there are include rules, an item must match **at least one** of them
  to be notified. Without include rules, every item that isn't excluded is notified.

And:

- **Exclude wins:** an item that matches an exclude rule is skipped, even if it also
  matches an include rule.
- **Upper and lower case don't matter:** `reserved` also matches *Reserved* and
  *RESERVED*.
- **Price limits** (`min`, `max`) are inclusive and compare the price in the shop's
  currency (`10` means €10.00 in a euro shop, $10.00 in a dollar shop). Items without a
  price are notified, so that nothing is missed.

## Setting filters in `.env`

For a few rules, set them in `.env` (or as environment variables):

| Setting | Meaning | Example |
|---|---|---|
| `NOTIFY_EXCLUDE` | Keywords, comma-separated | `gift card, custom order` |
| `NOTIFY_INCLUDE` | Keywords, comma-separated | `mug, vase` |
| `NOTIFY_EXCLUDE_REGEX` | **One** regular expression (combine with `\|`) | `'^reserved\b\|\bsold out\b'` |
| `NOTIFY_INCLUDE_REGEX` | **One** regular expression | `'\bmini (art )?print\b'` |
| `NOTIFY_MIN_PRICE` | Lowest price | `10` |
| `NOTIFY_MAX_PRICE` | Highest price | `150` |
| `FILTER_CONFIG` | Path of a [`filters.yml`](#setting-filters-in-filtersyml) | `filters.yml` |

```sh
NOTIFY_EXCLUDE=gift card, custom order
NOTIFY_EXCLUDE_REGEX='^reserved\b'
NOTIFY_MAX_PRICE=150
```

> [!IMPORTANT]
> Put regular expressions in **single quotes** (`'^reserved\b'`). In double quotes,
> `\b` and similar are turned into control characters, and the filter would never
> match – Shop Notify refuses to start in that case and tells you why.

## Setting filters in `filters.yml`

For more rules, put them in a YAML file – one rule per line, with comments – and point
`FILTER_CONFIG` at it. Start from [`filters.example.yml`](../filters.example.yml):

```yaml
exclude:
  - regex: '^reserved\b'        # "Reserved listing for Martin"
  - keyword: gift card
include:
  - regex: '\bmini (art )?print\b'
  - keyword: plate
price:
  min: 10
  max: 150
```

| Title | Price | Notified |
|---|---|---|
| Reserved listing for Martin | 24.99 | no |
| Mermaid Dreams - 5 x 7 Mini Art Print | 24.99 | yes |
| Tanith Toile Dinner Plate | 39 | yes |
| Tanith Toile Dinner Plate | 180 | no |
| Digital gift card | 25 | no |
| Big original painting | 120 | no |

- Every entry has either `keyword:` or `regex:`. Write regular expressions in **single
  quotes**, so that YAML keeps the backslashes as they are.
- `include`, `exclude` and `price` are all optional.
- Rules from `.env` and `filters.yml` are **combined**. For price limits, the file wins.

In Docker, mount the file like `notify.yml` – in `compose.yaml`:

```yaml
    volumes:
      - ./data:/data
      - ./filters.yml:/config/filters.yml:ro
```

and set `FILTER_CONFIG=/config/filters.yml` in `.env`.

## Keyword or regular expression?

Use a **keyword** when the text can appear anywhere in the title. Use a **regex** when
the position matters or when you need alternatives or variants:

| Goal | Keyword | Regex |
|---|---|---|
| Title contains *gift card* | `gift card` | – |
| Title **starts** with *Reserved* | – (would also match "… unreserved …") | `^reserved\b` |
| *mug* or *mugs*, but not *smuggler* | – | `\bmugs?\b` |
| *5x7*, *5 x 7* or *5 X 7* | – | `\b5\s*x\s*7\b` |

## Regular expressions in a nutshell

Shop Notify uses [Python's regular expressions](https://docs.python.org/3/library/re.html),
case-insensitive, and searches anywhere in the title (use `^` and `$` to anchor).

| Pattern | Meaning | Matches | Doesn't match |
|---|---|---|---|
| `^reserved` | starts with | *Reserved for Anna* | *Unreserved* |
| `print$` | ends with | *Mini art print* | *Print set* |
| `\bmug\b` | whole word | *A mug*, *Mug, blue* | *Smuggler* |
| `mugs?` | `s` is optional | *mug*, *mugs* | – |
| `mug\|vase` | either | *mug*, *vase* | *bowl* |
| `(mini\|small) print` | group of alternatives | *mini print*, *small print* | *big print* |
| `\d+ ?cm` | number, optional space | *20cm*, *20 cm* | *cm* |
| `\s*` | any whitespace, also none | *5x7*, *5 x 7* | – |
| `.*` | anything | – | – |
| `\.` `\(` `\+` | the character itself (`.`, `(`, `+`) | *No. 5* (`No\. 5`) | – |

[regex101.com](https://regex101.com) (flavor *Python*) is a good place to try
patterns; in Shop Notify, use [`check-filters`](#testing-filters).

## Examples

Each example shows a `filters.yml` and what it does with some titles. The same rules can
be set in `.env` – see the first example.

### Skip reserved listings

```yaml
exclude:
  - regex: '^reserved\b'
  - regex: '\breserved for\b'
```

| Title | Notified |
|---|---|
| Reserved listing for Martin | no |
| RESERVED - custom portrait | no |
| Mini print - reserved for Anna | no |
| Unreserved joy - mini print | yes |
| Mermaid Dreams - 5 x 7 Mini Art Print | yes |

In `.env`: `NOTIFY_EXCLUDE_REGEX='^reserved\b|\breserved for\b'`.

### Skip custom orders, gift cards and digital downloads

```yaml
exclude:
  - keyword: custom order
  - keyword: gift card
  - regex: '\b(digital|printable|instant) download\b'
```

| Title | Notified |
|---|---|
| Custom order for Lisa | no |
| Gift Card - 50 EUR | no |
| Coloring page - instant download | no |
| Hand-thrown mug | yes |

### Only certain products

```yaml
include:
  - regex: '\b(mug|vase|bowl)s?\b'
```

| Title | Notified |
|---|---|
| Hand-thrown mug "Morning dew" | yes |
| Set of two vases | yes |
| Smuggler's map print | no |
| Wall plate | no |

### Originals, not prints

```yaml
include:
  - keyword: original
exclude:
  - regex: '\b(art )?prints?\b'
```

| Title | Notified |
|---|---|
| Original painting on canvas | yes |
| Original art print | no |
| Mini art print | no |

### A certain size

```yaml
include:
  - regex: '\b5\s*x\s*7\b'
```

| Title | Notified |
|---|---|
| Mermaid Dreams - 5 x 7 Mini Art Print | yes |
| Beloved - 5x7 print | yes |
| 8 x 10 print | no |

### A price range

```yaml
price:
  min: 20
  max: 100
```

| Title | Price | Notified |
|---|---|---|
| Mini art print | 24.99 | yes |
| Sticker | 4.50 | no |
| Original painting | 450 | no |
| Item without a price | | yes |

### Keywords and a price limit combined

```yaml
include:
  - keyword: plate
  - keyword: mug
exclude:
  - regex: '^reserved\b'
price:
  max: 60
```

| Title | Price | Notified |
|---|---|---|
| Tanith Toile Dinner Plate | 39 | yes |
| Hand-thrown mug | 75 | no |
| Reserved: plate for Martin | 39 | no |
| Mini art print | 24.99 | no |

## Testing filters

`shop-notify check-filters` shows what the current filters (`.env` and `filters.yml`)
would do – without notifying anything:

```sh
shop-notify check-filters "Reserved listing for Martin"   # one title
shop-notify check-filters "Hand-thrown mug" --price 75    # with a price
shop-notify check-filters --since 30d                     # the items of the last 30 days
```

```text
Filters: exclude regex '^reserved\b'; include keyword 'mug'; price <= 60
  notify    Hand-thrown mug "Morning dew" (24.50 EUR)
  filtered  Reserved listing for Martin (25.00 USD)  <- exclude regex '^reserved\b'
  filtered  Big original painting (450.00 EUR)  <- no include filter matched
1 of 3 item(s) would be notified
```

`--since` uses the items in your database – a good way to try new filters against real
titles from your shop before you switch them on.

## What happens to filtered items

- They are **recorded**, not notified. The log says why:
  `Filtered (exclude regex '^reserved\b'): Reserved listing for Martin (https://…)`.
- The [history](../README.md#history) shows them as `filtered` with the rule, and
  `shop-notify history --polls` counts them.
- While a filtered item is in the shop, it is **checked again on every poll**. If it
  passes later – the shop owner changed the title from *"Reserved listing for Martin"*
  to *"Mermaid Dreams – Mini Art Print"*, or you changed your filters – it is notified
  then (log: `Now passes the filters: …`).
  If you remove a filter, items it held back that are still in the shop are therefore
  notified at the next poll.
- Filters also apply to items that are [back in the shop](../README.md#how-it-works)
  and to the first run with `NOTIFY_EXISTING_ON_FIRST_RUN=true`.

## Troubleshooting

**Shop Notify doesn't start: "Invalid filter configuration: …"** – the message names
the setting or the entry, e.g. `filters.yml: exclude[2]: invalid regular expression
'(unclosed': missing ), unterminated subpattern`. Fix it and start again.

**"… contains a control character"** – a regular expression in `.env` is in double
quotes. Use single quotes: `NOTIFY_EXCLUDE_REGEX='^reserved\b'`.

**An item wasn't notified** – find it in the history and check the reason:

```sh
shop-notify history --since 1d
# 2026-10-22 14:02   4602381177  filtered  Reserved listing for Martin  (reason: exclude regex '^reserved\b')
```

**A filter doesn't match** – try the title with `check-filters`. Remember that a regex
is searched anywhere in the title unless you use `^`/`$`, and that `.` `(` `)` `+` `?`
`*` have a special meaning (write `\.` for a literal dot).
