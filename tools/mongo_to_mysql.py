"""Copy everything from MongoDB to the MySQL database once, then rebuild the products there.

    MONGO_URI=... MYSQL_URL=... python -m tools.mongo_to_mysql

Safe to run again: offers, benchmarks and redirects are replaced, runs are copied only if the MySQL table is empty.
Prints counts only."""
import json
import os
import sys
from datetime import datetime, timezone

from pph import DB_NAME, sql_db


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def copy(mongo, my, batch=2000):
    sql_db.ensure_indexes(my)
    counts = {}
    with my.cursor() as cur:
        rows, n = [], 0
        for d in mongo.offers.find({}):
            rows.append(sql_db.offer_row(d["_id"], d))
            if len(rows) >= batch:
                sql_db._upsert_offers(cur, rows); n += len(rows); rows = []
        if rows:
            sql_db._upsert_offers(cur, rows); n += len(rows)
        counts["offers"] = n

        cur.execute("SELECT COUNT(*) FROM scrape_runs")
        if cur.fetchone()[0] == 0:
            runs = [(r["store"], r["started"], r.get("finished"), r.get("status", ""), int(r.get("fetched") or 0), int(r.get("written") or 0),
                     int(r.get("previous_count") or 0), str(r.get("note") or "")[:255])
                    for r in mongo.scrape_runs.find({}).sort("started", 1) if r.get("store") and r.get("started")]
            sql_db._many(cur, "INSERT INTO scrape_runs (store, started, finished, status, fetched, written, previous_count, note) "
                              "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", runs)
            counts["scrape_runs"] = len(runs)

        bench = [((d.get("bucket") or d.get("type")), d.get("rank"), json.dumps({k: v for k, v in d.items() if k != "_id"}, default=str))
                 for d in mongo.benchmarks.find({})]
        if bench:
            cur.execute("DELETE FROM benchmarks")
            sql_db._many(cur, "INSERT INTO benchmarks (bucket, `rank`, doc) VALUES (%s,%s,%s)", bench)
        counts["benchmarks"] = len(bench)

        redirects = [(str(d["_id"])[:64], d["group_id"]) for d in mongo.legacy_redirects.find({}) if d.get("group_id")]
        sql_db._many(cur, "REPLACE INTO legacy_redirects (old_id, group_id) VALUES (%s,%s)", redirects)
        counts["legacy_redirects"] = len(redirects)

    out = sql_db.write_rollup(my, _now())
    counts["products"] = out["products"]
    counts["mysql_mb"] = round((out["bytes"] or 0) / 1024 / 1024, 1)
    counts["mongo_products"] = mongo.products_v2.estimated_document_count()
    return counts


def main():
    from pymongo import MongoClient
    if not os.environ.get("MONGO_URI") or not os.environ.get("MYSQL_URL"):
        raise SystemExit("Both MONGO_URI and MYSQL_URL must be set")
    mongo = MongoClient(os.environ["MONGO_URI"], serverSelectionTimeoutMS=20000)[DB_NAME]
    counts = copy(mongo, sql_db.connect(os.environ["MYSQL_URL"]))
    print(json.dumps(counts))
    with open(os.environ.get("GITHUB_STEP_SUMMARY") or os.devnull, "a") as f:
        f.write("| table | rows |\n|---|---|\n" + "".join(f"| {k} | {v} |\n" for k, v in counts.items()))
    # The copy is good only if the products came out at least 95% as many as MongoDB has.
    return 0 if counts["products"] >= 0.95 * counts["mongo_products"] else 1


if __name__ == "__main__":
    sys.exit(main())
