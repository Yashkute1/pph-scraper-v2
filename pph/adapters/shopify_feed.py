"""Shopify stores publish their catalogue at /products.json - no HTML parsing needed."""
from .common import EmptyListingError, json_page

MAX_PAGES = 400


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
    seen = set()
    for n in range(1, MAX_PAGES + 1):
        url = f"{base}/products.json?limit=250&page={n}"
        data = json_page(fetcher, url, first=(n == 1))
        products = (data.get("products") if isinstance(data, dict) else None) or []
        if not products:
            break
        for p in products:
            o = _offer(base, p)
            if o and p["handle"] not in seen:
                seen.add(p["handle"])
                yield o
    if not seen:
        raise EmptyListingError(base + "/products.json")
