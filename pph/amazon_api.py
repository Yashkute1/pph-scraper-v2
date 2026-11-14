"""What Amazon's Creators API says about a product, and what that means for a scraped offer. Pure, no I/O."""
import re

_ASIN = re.compile(r"/dp/([A-Z0-9]{10})")


def asin_of(url):
    """The 10-character product id in an Amazon product link, or None."""
    m = _ASIN.search(url or "")
    return m.group(1) if m else None


def classify(item):
    """(kind, price) for one API item. Kind is in_stock, out_of_stock, preorder, other, or missing (no offer known).
    The price is the buy-box listing's (else the first listing's), None when absent or not above 0."""
    listings = ((item or {}).get("offersV2") or {}).get("listings") or []
    if not listings:
        return "missing", None
    listing = next((l for l in listings if l.get("isBuyBoxWinner")), listings[0])
    amount = ((listing.get("price") or {}).get("money") or {}).get("amount")
    price = round(amount) if isinstance(amount, (int, float)) and amount > 0 else None
    kind = {"IN_STOCK": "in_stock", "OUT_OF_STOCK": "out_of_stock", "PREORDER": "preorder"}.get(
        (listing.get("availability") or {}).get("type"), "other")
    return kind, price


def apply(offer, kind, price):
    """A corrected copy of the offer. Out of stock, preorder and missing mean not in stock; in stock means in stock;
    other leaves stock as it was. A usable price replaces the scraped one, and the mrp never ends up below it."""
    out = dict(offer)
    if kind in ("out_of_stock", "preorder", "missing"):
        out["in_stock"] = False
    elif kind == "in_stock":
        out["in_stock"] = True
    if price is not None and price > 0 and kind in ("in_stock", "other"):
        out["price"] = round(price)
        out["mrp"] = max(out.get("mrp") or 0, out["price"])
    return out
