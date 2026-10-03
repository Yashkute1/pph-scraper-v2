"""Shopify stores publish their catalogue at /products.json - no HTML parsing needed."""
from .common import EmptyListingError, json_page

FEED_CAP = 5000          # /products.json stops serving beyond roughly this many products
MAX_PAGES = 200


def _pages(fetcher, url_tpl, key):
    for n in range(1, MAX_PAGES + 1):
        items = (json_page(fetcher, url_tpl % n, first=(n == 1)) or {}).get(key) or []
        if not items:
            return
        yield from items


def _offer(base, p):
    variants = p.get("variants") or []
    if not variants or not p.get("handle"):
        return None
    live = [v for v in variants if v.get("available")]
    best = min(live or variants, key=lambda v: float(v.get("price") or 0) or float("inf"))
    images = p.get("images") or []
    return {"title": p.get("title") or "", "price": best.get("price"), "mrp": best.get("compare_at_price") or None,
            "url": f"{base}/products/{p['handle']}", "image": (images[0].get("src") if images else "") or "",
            "in_stock": bool(live), "sku": best.get("sku") or "", "brand": p.get("vendor") or ""}


def iter_offers(cfg, fetcher):
    base = cfg["base"].rstrip("/")
    seen, count = set(), 0
    def emit(products):
        for p in products:
            h = p.get("handle")
            if h in seen:
                continue
            o = _offer(base, p)
            if o:
                seen.add(h)
                yield o
    for o in emit(_pages(fetcher, base + "/products.json?limit=250&page=%d", "products")):
        count += 1
        yield o
    if count == 0:
        raise EmptyListingError(base + "/products.json")
    if count >= cfg.get("feed_cap", FEED_CAP):
        # the main feed was truncated: sweep every collection for the remainder
        for c in _pages(fetcher, base + "/collections.json?limit=250&page=%d", "collections"):
            yield from emit(_pages(fetcher, f"{base}/collections/{c['handle']}/products.json?limit=250&page=%d", "products"))
