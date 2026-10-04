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


def main(argv=None):
    path = (argv or sys.argv[1:] or ["sample.json"])[0]
    uri = os.environ.get("MONGO_URI")
    if not uri:
        raise SystemExit("MONGO_URI is not set")
    out = export(MongoClient(uri, serverSelectionTimeoutMS=20000)[DB_NAME])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print({k: len(v) for k, v in out.items() if isinstance(v, list)})


if __name__ == "__main__":
    main()
