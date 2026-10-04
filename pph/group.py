"""Collapse per-store offers into one ready-to-serve row per part. Pure, no I/O."""
import re
from collections import defaultdict
from datetime import timedelta
from statistics import median

from .benchmarks import match as match_benchmark
from .facets import facets_of

MAX_DISCOUNT = 0.85      # a bigger "discount" is almost always a mismatched or fake MRP
DROP_MIN_DAYS = 7        # no "price dropped" claim until a week of history exists
DROP_WINDOW = 30
MAX_SPREAD = 60          # stores further apart than this are almost always two different parts grouped together


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s or "").lower()).strip("-")


def _drop_pct(members, best, now):
    if not best.get("in_stock"):
        return 0
    since = (now - timedelta(days=DROP_WINDOW)).strftime("%Y-%m-%d")
    per_day = {}
    for o in members:
        for h in o.get("history") or []:
            if h.get("p") and h.get("d", "") > since:
                per_day[h["d"]] = min(h["p"], per_day.get(h["d"], h["p"]))
    if len(per_day) < DROP_MIN_DAYS:
        return 0
    mid = median(per_day.values())
    return max(0, round((mid - best["price"]) / mid * 100, 1))


def _spread_pct(offers):
    live = [o["price"] for o in offers if o.get("in_stock")]
    if len(live) < 2:
        return 0
    mid = median(live[1:])                               # offers are sorted, so live[0] is the best price
    pct = round((mid - live[0]) / mid * 100, 1)
    return pct if 0 < pct <= MAX_SPREAD else 0


def _rank(o):
    return (0 if o.get("in_stock") else 1, o["price"])


def _row(gid, members, now, benchmarks=None):
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
        "offers": [{"id": o.get("_id"), "store": o["store"], "price": o["price"], "in_stock": bool(o.get("in_stock")),
                    "url": o["url"], "checked": o.get("last_seen")} for o in offers],
        "low_90d": min(points + [o["price"] for o in members]), "updated_at": now, "specs": best.get("specs") or {},
        "category_slug": slug(best.get("category")), "brand_slug": slug(best.get("brand")),
        "drop_pct": _drop_pct(members, best, now), "spread_pct": _spread_pct(offers),
        "benchmark": match_benchmark(best["title"], best.get("category"), benchmarks),
        "facets": facets_of(best["title"], best.get("category"), best.get("specs")),
    }


def rollup(offers, now, benchmarks=None):
    groups = defaultdict(list)
    for o in offers:
        if o.get("group_id") and o.get("price"):
            groups[o["group_id"]].append(o)
    return [_row(g, m, now, benchmarks) for g, m in groups.items()]
