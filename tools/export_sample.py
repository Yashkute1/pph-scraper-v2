"""Write a small, real sample of the site's data to sample.json for the website's tests.

    MONGO_URI=... python -m tools.export_sample sample.json

Only product and price data is exported. Nothing is printed except counts."""
import json
import os
import sys
from datetime import datetime

from pymongo import MongoClient

from pph import DB_NAME
from pph.group import AMAZON
from tools import public_data

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


def _pick(rows, per_category):
    """A few parts of every kind the site's tests need: the most stocked of each category, and the awkward ones."""
    picked = {}

    def take(some):
        for d in some:
            picked.setdefault(d["group_id"], d)

    ranked = sorted(rows, key=lambda d: (not d["any_stock"], -d["store_count"], d["best_price"], d["group_id"]))
    for cat in sorted({d["category_slug"] for d in rows if d["category_slug"]}):
        take([d for d in ranked if d["category_slug"] == cat][:per_category])
    take([d for d in ranked if d["store_count"] == 1 and d["any_stock"]][:EXTRA])
    take([d for d in ranked if not d["any_stock"]][:EXTRA])
    take(sorted(rows, key=lambda d: (-d["best_price"], d["group_id"]))[:2])
    take(sorted(rows, key=lambda d: (-len(d.get("title") or ""), d["group_id"]))[:1])
    return picked


def export(db, per_category=PER_CATEGORY):
    everything = list(db.offers.find({}))
    bench = list(db.benchmarks.find({}, {"_id": 0}))
    picked = _pick(public_data.products(everything, bench), per_category)
    offers = [dict(_plain(d), id=d["_id"]) for d in public_data.public_offers(everything) if d.get("group_id") in picked]
    runs = []
    for store in sorted(s for s in db.scrape_runs.distinct("store") if s != AMAZON):
        last = db.scrape_runs.find({"store": store}).sort("started", -1).limit(1)
        runs.extend(_plain(r) for r in last)
    bench = sorted(bench, key=lambda b: (str(b.get("bucket")), b.get("rank") or 0))[:BENCHMARKS]
    return {"exported": _plain(datetime.utcnow()), "products": [_plain(d) for d in picked.values()],
            "offers": offers, "runs": runs, "benchmarks": [_plain(b) for b in bench]}


def export_sql(db, per_category=PER_CATEGORY):
    """The same sample from the MySQL database."""
    from pph.sql_db import _rows
    picked = _pick(public_data.sql_products(db), per_category)
    with db.cursor() as cur:
        offers = []
        ids = list(picked)
        if ids:
            marks = ",".join(["%s"] * len(ids))
            for r in _rows(cur, f"SELECT * FROM offers WHERE store <> %s AND group_id IN ({marks})", [AMAZON, *ids]):
                r["in_stock"] = bool(r["in_stock"])
                r["specs"] = json.loads(r["specs"] or "{}")
                r["history"] = json.loads(r["history"] or "[]")
                offers.append(_plain(r))
        runs = [_plain(r) for r in _rows(cur, "SELECT store, started, finished, status, fetched, written, previous_count, note FROM scrape_runs r "
                                               "WHERE store <> %s AND started = (SELECT MAX(started) FROM scrape_runs x WHERE x.store = r.store) ORDER BY store", (AMAZON,))]
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
