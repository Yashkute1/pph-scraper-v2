"""Shopify stores publish their catalogue at /products.json - no HTML parsing needed."""
import json

from .common import EmptyListingError

MAX_PAGES = 400


def _feed(fetcher, url_tpl, key, state):
    """Yield items page by page. Sets state['cut'] when the feed stops on an error rather than an empty page."""
    for n in range(1, MAX_PAGES + 1):
        page = fetcher.get(url_tpl % n)
        try:
            items = (json.loads(page.text) or {}).get(key) if page.status == 200 else None
        except (ValueError, AttributeError):
            items = None
        if items is None:
            state["cut"] = True
            return
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
    seen, state, count = set(), {"cut": False}, 0

    def emit(products):
        for p in products:
            h = p.get("handle")
            if h in seen:
                continue
            o = _offer(base, p)
            if o:
                seen.add(h)
                yield o

    for o in emit(_feed(fetcher, base + "/products.json?limit=250&page=%d", "products", state)):
        count += 1
        yield o
    if count == 0:
        raise EmptyListingError(base + "/products.json")
    if state["cut"]:
        # the store stopped serving the main feed part-way: sweep the collections for the remainder
        for c in list(_feed(fetcher, base + "/collections.json?limit=250&page=%d", "collections", {})):
            yield from emit(_feed(fetcher, f"{base}/collections/{c['handle']}/products.json?limit=250&page=%d", "products", {}))
