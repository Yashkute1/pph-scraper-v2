"""All MongoDB access. Collections: offers, products_v2, scrape_runs (never the legacy `products`)."""
import hashlib
from datetime import timedelta

from pymongo import ReplaceOne, UpdateOne

from .benchmarks import build_lookup
from .group import rollup
from .normalize import canonical_url

GATE_RATIO = 0.60        # a run returning less than this share of the store's live offers is not trusted
MISSED_LIMIT = 3         # unseen in this many good runs -> out of stock
DELETE_AFTER = timedelta(days=14)
HISTORY_DAYS = 90
BATCH = 1000
SIZE_BUDGET = 430 * 1024 * 1024      # free tier holds 512 MB


def offer_id(store, url):
    return hashlib.sha1(f"{store}|{canonical_url(url)}".encode()).hexdigest()[:24]


def gate(fetched, previous, blocked):
    """(write?, status). Protects good data from a blocked, empty or badly truncated run."""
    if blocked:
        return False, "blocked"
    if fetched <= 0:
        return False, "failed"
    if previous and fetched < GATE_RATIO * previous:
        return False, "partial"
    return True, "ok"


def ensure_indexes(db):
    db.offers.create_index([("store", 1), ("missed_runs", 1)])
    db.offers.create_index("group_id")
    p = db.products_v2
    p.create_index([("category", 1), ("any_stock", -1), ("store_count", -1)])
    p.create_index([("category", 1), ("best_price", 1)])
    p.create_index("brand")
    p.create_index([("any_stock", -1), ("store_count", -1)])
    p.create_index([("title", "text")])
    p.create_index([("category_slug", 1), ("any_stock", -1), ("store_count", -1), ("best_price", 1)])      # site: popular
    p.create_index([("category_slug", 1), ("any_stock", -1), ("best_price", 1)])                           # site: by price
    p.create_index([("category_slug", 1), ("any_stock", -1), ("store_count", -1), ("best_price", -1)])     # site: default order
    p.create_index([("category_slug", 1), ("brand_slug", 1), ("any_stock", -1), ("store_count", -1)])      # site: brand filter
    p.create_index([("any_stock", -1), ("drop_pct", -1)])                                                  # site: deals
    p.create_index([("any_stock", -1), ("spread_pct", -1)])
    db.scrape_runs.create_index([("store", 1), ("started", -1)])


def _bulk(col, ops):
    for i in range(0, len(ops), BATCH):
        col.bulk_write(ops[i:i + BATCH], ordered=False)


def _history(old, day, price):
    h = [x for x in (old or []) if x.get("d") != day]
    h.append({"d": day, "p": price})
    return h[-HISTORY_DAYS:]


def write_store(db, store, offers, now, blocked, started=None, note="", complete=True):
    """Apply one store's run behind the sanity gate and record it. Returns the scrape_runs document.

    Trusted run (complete, not blocked, >= 60% of live offers): prices refreshed and unseen offers aged.
    Untrusted run: the offers it did fetch are refreshed (they are real prices) but nothing else is touched,
    so a blocked or truncated run can never mark products out of stock or delete them."""
    unique = {}
    for o in offers:
        oid = offer_id(store, o["url"])
        if oid not in unique or o["price"] < unique[oid]["price"]:
            unique[oid] = o
    previous = db.offers.count_documents({"store": store, "missed_runs": {"$lt": MISSED_LIMIT}})
    ok, status = gate(len(unique), previous, blocked)
    if ok and not complete:
        ok, status = False, "partial"
    run = {"store": store, "started": started or now, "finished": now, "status": status, "fetched": len(unique),
           "written": 0, "previous_count": previous, "note": note}
    if unique and status != "failed":
        existing = {d["_id"]: d for d in db.offers.find({"store": store, "_id": {"$in": list(unique)}}, {"history": 1})}
        day = now.strftime("%Y-%m-%d")
        ops = []
        for oid, o in unique.items():
            doc = dict(o, last_seen=now, missed_runs=0,
                       history=_history(existing.get(oid, {}).get("history"), day, o["price"]))
            ops.append(UpdateOne({"_id": oid}, {"$set": doc, "$setOnInsert": {"first_seen": now}}, upsert=True))
        _bulk(db.offers, ops)
        run["written"] = len(ops)
    if ok:
        unseen = {"store": store, "_id": {"$nin": list(unique)}}
        db.offers.update_many(unseen, {"$inc": {"missed_runs": 1}})
        db.offers.update_many(dict(unseen, missed_runs={"$gte": MISSED_LIMIT}), {"$set": {"in_stock": False}})
        db.offers.delete_many(dict(unseen, last_seen={"$lt": now - DELETE_AFTER}))
    db.scrape_runs.insert_one(dict(run))
    return run


def stale_stores(db, stores, now, hours):
    """Stores whose latest good run started more than `hours` ago, or that have never had one."""
    from datetime import timedelta
    cutoff = now - timedelta(hours=hours)
    out = []
    for s in stores:
        last = db.scrape_runs.find_one({"store": s, "status": "ok"}, sort=[("started", -1)])
        if not last or last["started"] < cutoff:
            out.append(s)
    return out


def write_rollup(db, now):
    """Rebuild products_v2 from current offers. Keeps the previous rows if there are no offers at all."""
    fields = {"store": 1, "url": 1, "title": 1, "price": 1, "mrp": 1, "in_stock": 1, "image": 1, "brand": 1,
              "category": 1, "group_id": 1, "specs": 1, "history": 1, "last_seen": 1}
    try:
        benchmarks = build_lookup(db.benchmarks.find({}, {"_id": 0, "bucket": 1, "type": 1, "model": 1, "score": 1,
                                                          "benchmark": 1, "percentile": 1, "rank": 1, "samples": 1}))
    except Exception:
        benchmarks = None             # scores are an extra; a roll-up without them is still a good roll-up
    rows = rollup(db.offers.find({}, fields), now, benchmarks)
    out = {"products": len(rows), "skipped": False, "bytes": None, "trimmed": False}
    if not rows:
        out["skipped"] = True
        return out
    _bulk(db.products_v2, [ReplaceOne({"_id": r["group_id"]}, dict(r, _id=r["group_id"]), upsert=True) for r in rows])
    db.products_v2.delete_many({"updated_at": {"$lt": now}})
    try:
        stats = db.command("dbstats")
        out["bytes"] = int(stats.get("dataSize", 0) + stats.get("indexSize", 0))
        if out["bytes"] > SIZE_BUDGET:
            db.offers.update_many({}, {"$push": {"history": {"$each": [], "$slice": -30}}})
            out["trimmed"] = True
    except Exception:
        pass                      # size reporting is best-effort; never fail a run over it
    return out
