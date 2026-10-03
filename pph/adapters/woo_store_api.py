"""WooCommerce Store API (/wp-json/wc/store/v1/products): public JSON, prices in minor units."""
import html
from .common import EmptyListingError, json_page

MAX_PAGES = 400


def _money(raw, minor):
    if raw in (None, ""):
        return None
    try:
        return int(raw) / (10 ** int(minor or 0))
    except (TypeError, ValueError):
        return None


def iter_offers(cfg, fetcher):
    base = cfg["base"].rstrip("/")
    tpl = base + "/wp-json/wc/store/v1/products?per_page=100&page=%d"
    count = 0
    for n in range(1, MAX_PAGES + 1):
        items = json_page(fetcher, tpl % n, first=(n == 1))
        if not items or not isinstance(items, list):
            break
        for p in items:
            pr = p.get("prices") or {}
            price = _money(pr.get("price"), pr.get("currency_minor_unit"))
            if price is None or not p.get("permalink"):
                continue
            images = p.get("images") or []
            count += 1
            yield {"title": html.unescape(p.get("name") or ""), "price": price,
                   "mrp": _money(pr.get("regular_price"), pr.get("currency_minor_unit")),
                   "url": p["permalink"], "image": (images[0].get("src") if images else "") or "",
                   "in_stock": bool(p.get("is_in_stock", True)), "sku": p.get("sku") or ""}
    if count == 0:
        raise EmptyListingError(tpl % 1)
