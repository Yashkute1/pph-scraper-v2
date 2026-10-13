"""Write a small, real sample of the site's data to sample.json for the website's tests.

    MONGO_URI=... python -m tools.export_sample sample.json

Only product and price data is exported. Nothing is printed except counts."""
import json
import os
import sys
from datetime import datetime

from pymongo import MongoClient

from pph import DB_NAME

PER_CATEGORY = 20
EXTRA = 5
BENCHMARKS = 200


def _plain(v):
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items() if k != "_id"}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return v


def export(db, per_category=PER_CATEGORY):
    p = db.products_v2
    picked = {}

    def take(cursor):
        for d in cursor:
            picked.setdefault(d["group_id"], d)

    for cat in sorted(c for c in p.distinct("category_slug") if c):
        take(p.find({"category_slug": cat}).sort([("any_stock", -1), ("store_count", -1), ("best_price", 1)]).limit(per_category))
    take(p.find({"store_count": 1, "any_stock": True}).limit(EXTRA))
    take(p.find({"any_stock": False}).limit(EXTRA))
    take(p.find({}).sort("best_price", -1).limit(2))
    longest = max(p.find({}, {"group_id": 1, "title": 1}), key=lambda d: len(d.get("title") or ""), default=None)
    if longest:
        take(p.find({"group_id": longest["group_id"]}))
    ids = list(picked)
    offers = []
    for d in db.offers.find({"group_id": {"$in": ids}}):
        offers.append(dict(_plain(d), id=d["_id"]))
    runs = []
    for store in sorted(db.scrape_runs.distinct("store")):
        last = db.scrape_runs.find({"store": store}).sort("started", -1).limit(1)
        runs.extend(_plain(r) for r in last)
    bench = [_plain(b) for b in db.benchmarks.find({}).sort([("bucket", 1), ("rank", 1)]).limit(BENCHMARKS)]
    return {"exported": _plain(datetime.utcnow()), "products": [_plain(d) for d in picked.values()],
            "offers": offers, "runs": runs, "benchmarks": bench}


def export_sql(db, per_category=PER_CATEGORY):
    """The same sample from the MySQL database."""
    from pph.sql_db import JSON_PRODUCT, _rows
    with db.cursor() as cur:
        def prods(where, args=(), order="any_stock DESC, store_count DESC, best_price ASC", limit=per_category):
            return _rows(cur, f"SELECT * FROM products WHERE {where} ORDER BY {order} LIMIT {int(limit)}", args)
        picked = {}
        cur.execute("SELECT DISTINCT category_slug FROM products WHERE category_slug <> '' ORDER BY category_slug")
        for (cat,) in cur.fetchall():
            for d in prods("category_slug=%s", (cat,)):
                picked.setdefault(d["group_id"], d)
        for d in prods("store_count=1 AND any_stock=1", limit=EXTRA) + prods("any_stock=0", limit=EXTRA) + \
                prods("1=1", order="best_price DESC", limit=2) + prods("1=1", order="CHAR_LENGTH(title) DESC", limit=1):
            picked.setdefault(d["group_id"], d)
        for d in picked.values():
            for k in JSON_PRODUCT:
                d[k] = json.loads(d[k]) if d.get(k) else ({} if k != "stores" and k != "offers" else [])
            d["any_stock"] = bool(d["any_stock"])
            if not d["benchmark"]:
                d["benchmark"] = None
        ids = list(picked)
        offers = []
        if ids:
            marks = ",".join(["%s"] * len(ids))
            for r in _rows(cur, f"SELECT * FROM offers WHERE group_id IN ({marks})", ids):
                r["in_stock"] = bool(r["in_stock"])
                r["specs"] = json.loads(r["specs"] or "{}")
                r["history"] = json.loads(r["history"] or "[]")
                offers.append(_plain(r))
        runs = [_plain(r) for r in _rows(cur, "SELECT store, started, finished, status, fetched, written, previous_count, note FROM scrape_runs r "
                                               "WHERE started = (SELECT MAX(started) FROM scrape_runs x WHERE x.store = r.store) ORDER BY store")]
        bench = [json.loads(r["doc"]) for r in _rows(cur, f"SELECT doc FROM benchmarks ORDER BY bucket, `rank` LIMIT {BENCHMARKS}")]
    return {"exported": _plain(datetime.utcnow()), "products": [_plain(d) for d in picked.values()],
            "offers": offers, "runs": runs, "benchmarks": bench}


def main(argv=None):
    path = (argv or sys.argv[1:] or ["sample.json"])[0]
    if os.environ.get("MYSQL_URL"):
        from pph import sql_db
        out = export_sql(sql_db.connect(os.environ["MYSQL_URL"]))
    else:
        uri = os.environ.get("MONGO_URI")
        if not uri:
            raise SystemExit("Neither MYSQL_URL nor MONGO_URI is set")
        out = export(MongoClient(uri, serverSelectionTimeoutMS=20000)[DB_NAME])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print({k: len(v) for k, v in out.items() if isinstance(v, list)})


if __name__ == "__main__":
    main()
