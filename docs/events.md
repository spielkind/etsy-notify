# Events

Besides new items, Shop Notify can tell you when something happens to the items of a
shop – an item is back in stock, its price drops, it sells out or only one is left.
Choose the events with `NOTIFY_EVENTS`; by default you get **new items** and items
**back in the shop**.

```sh
NOTIFY_EVENTS=new,back,restocked      # e.g. also when a sold-out item is available again
```

## The events

| Event | When | Message (example) | Default |
|---|---|---|---|
| `new` | an item appears in the shop for the first time | *Mermaid Dreams* – $24.99 · Oct 21, 2026 | on |
| `back` | an item comes back after it was gone for longer than `FORGET_AFTER_HOURS` (24 h) | **Back in the shop** · $19.99 (was $24.99) · last seen Nov 3 (4 weeks ago) | on |
| `restocked` | a **sold-out** item is available again – right away, without waiting for `FORGET_AFTER_HOURS` | **Back in stock** · $24.99 · sold out for 11 hours · only 1 left | off |
| `price_drop` | the price drops by at least `NOTIFY_PRICE_CHANGE_PERCENT` (5 %) | **Price drop** · $19.99 (was $24.99, −20%) | off |
| `price_rise` | the price rises by at least `NOTIFY_PRICE_CHANGE_PERCENT` | **Price increase** · $29.99 (was $24.99, +20%) | off |
| `sold_out` | an item sells out | **Sold out** · $24.99 · in the shop since Oct 20 | off |
| `low_stock` | the quantity drops to `NOTIFY_LOW_STOCK` (1) or below | **Almost sold out** · $24.99 · only 1 left | off |

All events of a poll go out together: e-mails get **one** message, e.g. *"1 new, 1 back
in stock and 2 price drops in mabgraves"*; push and chat services get one message per
item with its picture, e.g. *"Back in stock in mabgraves: Mermaid Dreams"*.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `NOTIFY_EVENTS` | `new,back` | Events to notify, comma-separated (see the table above) |
| `NOTIFY_PRICE_CHANGE_PERCENT` | `5` | Minimum change for `price_drop` and `price_rise`, in percent |
| `NOTIFY_LOW_STOCK` | `1` | `low_stock` when the quantity drops to this value or below |
| `FORGET_AFTER_HOURS` | `24` | An item that is missing this long counts as gone (`back` when it returns) |
| `NOTIFY_BACK` | `true` | Up to version 1.2: `false` removes `back` from `NOTIFY_EVENTS` |

Examples:

```sh
# Collectors: new items, and sold-out items that are available again
NOTIFY_EVENTS=new,back,restocked

# Bargain hunters: also price drops of at least 10 %
NOTIFY_EVENTS=new,back,price_drop
NOTIFY_PRICE_CHANGE_PERCENT=10

# Everything, and "almost sold out" when 2 or fewer are left
NOTIFY_EVENTS=new,back,restocked,price_drop,price_rise,sold_out,low_stock
NOTIFY_LOW_STOCK=2
```

[Filters](filters.md) apply to every event: an item you filtered out doesn't cause a
price drop or back-in-stock message either.

## How Shop Notify finds out

Shop Notify reads the **active** listings of the shop. An item that sells out, is
deactivated or deleted simply disappears from that list. For items that disappear,
Shop Notify asks Etsy for their state – one request for up to 100 items, only when
something disappeared:

| State | Meaning | Recorded as |
|---|---|---|
| `sold_out` | sold out, still in the shop but not available | `sold_out` (→ `restocked` when it's available again) |
| `inactive` | deactivated by the shop owner | `inactive` |
| `expired` | not renewed | `expired` |
| deleted | Etsy doesn't know the item anymore | `removed` |
| `active` | still active – a gap in Etsy's listing index | nothing; the item is just missing for a while |

A sold-out item that comes back is notified as `restocked` immediately. Any other item
that comes back within `FORGET_AFTER_HOURS` isn't notified (it was most likely a gap in
Etsy's index); after that it's `back`.

## Avoiding notification floods

- **Price drops** are measured from the **lowest price you were notified about**. If a
  price flips between $25 and $20, you hear about the first drop to $20 only – and again
  when it drops below $20.
- **Price increases** are measured from the previous price.
- **Low stock** is notified once; again only after the quantity went above
  `NOTIFY_LOW_STOCK` and dropped again.
- If several things happen to an item before it was notified, the most important one is
  sent: new → back in stock → back → price drop → low stock → price increase → sold out.
  A new item that drops in price before it was notified is still sent as *new*, with
  the current price.

## In the history

Every event is recorded, whether it is notified or not – also `inactive`, `expired` and
`removed`, and the price and title changes:

```sh
shop-notify history 4588823944
```

```text
2026-10-21 11:07   4588823944  imported       Enchanted series mini print set …
2026-10-22 06:54   4588823944  sold_out       Enchanted series mini print set …
2026-10-22 18:16   4588823944  title_changed  Last ONE Enchanted series …  (old: Enchanted series …)
2026-10-22 18:16   4588823944  restocked      Last ONE Enchanted series …  (sold_out_since: 2026-10-22 06:54)
2026-10-22 18:16   4588823944  low_stock      Last ONE Enchanted series …  (quantity: 1)
2026-10-22 18:16   4588823944  notified       Last ONE Enchanted series …  (kind: restocked)
```

`shop-notify history --polls` counts the items that sold out and were restocked per poll.

## Custom templates

Templates get the event of each item as `item.kind` (`new`, `back`, `restocked`, …) and
its details as `item.event` (`last_seen`, `sold_out_since`, `first_seen`,
`previous_price`, `quantity`, `gone_for`). The filters `summary`, `event_label`,
`subject_prefix`, `price_note` and `when` produce the texts of the built-in templates –
see [notifications.md](notifications.md#message-templates). Templates from version 1.1
and 1.2 keep working: `item.back` is set for items back in the shop.
