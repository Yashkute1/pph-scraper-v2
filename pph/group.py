"""Collapse per-store offers into one ready-to-serve row per part. Pure, no I/O."""
from collections import defaultdict

MAX_DISCOUNT = 0.85      # a bigger "discount" is almost always a mismatched or fake MRP


def _rank(o):
    return (0 if o.get("in_stock") else 1, o["price"])


def _row(gid, members, now):
    per_store = {}
    for o in members:                                   # cheapest in-stock offer per store
        cur = per_store.get(o["store"])
        if cur is None or _rank(o) < _rank(cur):
            per_store[o["store"]] = o
    offers = sorted(per_store.values(), key=_rank)
    best = offers[0]
    mrp = best.get("mrp") or 0
    if not (mrp > best["price"] and 1 - best["price"] / mrp <= MAX_DISCOUNT):
        mrp = None
    points = [h["p"] for o in members for h in (o.get("history") or []) if h.get("p")]
    return {
        "group_id": gid, "title": best["title"], "brand": best.get("brand"), "category": best.get("category"),
        "image": best.get("image") or next((o["image"] for o in offers + members if o.get("image")), ""),
        "best_price": best["price"], "best_store": best["store"], "best_url": best["url"], "mrp": mrp,
        "any_stock": any(o.get("in_stock") for o in offers), "store_count": len(offers),
        "stores": [o["store"] for o in offers],
        "offers": [{"store": o["store"], "price": o["price"], "in_stock": bool(o.get("in_stock")), "url": o["url"]} for o in offers],
        "low_90d": min(points + [o["price"] for o in members]), "updated_at": now, "specs": best.get("specs") or {},
    }


def rollup(offers, now):
    groups = defaultdict(list)
    for o in offers:
        if o.get("group_id") and o.get("price"):
            groups[o["group_id"]].append(o)
    return [_row(g, m, now) for g, m in groups.items()]
