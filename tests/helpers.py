from etsy_notify.models import Listing


def make_listing(listing_id: int, title: str = "Item") -> Listing:
    return Listing(
        listing_id=listing_id,
        title=f"{title} {listing_id}",
        url=f"https://www.etsy.com/listing/{listing_id}",
        last_modified_timestamp=1_700_000_000,
    )
