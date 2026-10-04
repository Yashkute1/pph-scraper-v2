import json
from datetime import datetime

import mongomock

from pph.store_db import ensure_indexes, write_rollup, write_store
from tools.export_sample import export

T0 = datetime(2026, 10, 4, 3, 0)


def o(store, n, price=1000, in_stock=True, cat="SSD", title=None):
    return {"store": store, "url": f"https://{store}.test/p/{n}", "title": title or f"Part number {n}", "price": price, "mrp": price,
            "in_stock": in_stock, "image": "", "brand": "MSI", "category": cat, "model_key": str(n),
            "group_id": f"{cat.lower()}-msi-{n}", "specs": {}}


def seeded():
    db = mongomock.MongoClient().pph_site
    ensure_indexes(db)
    write_store(db, "a", [o("a", n) for n in range(30)] + [o("a", 99, cat="HDD", in_stock=False)]
                + [o("a", 500, price=1250000, title="X" * 200)], T0, False)
    write_store(db, "b", [o("b", n, 900) for n in range(3)], T0, False)
    db.benchmarks.insert_many([{"bucket": "SSD", "model": f"m{i}", "score": float(i), "rank": i, "percentile": 1, "samples": 1}
                               for i in range(300)])
    write_rollup(db, T0)
    return db


def test_export_shape_and_selection():
    out = export(seeded(), per_category=5)
    assert set(out) == {"products", "offers", "runs", "benchmarks", "exported"}
    ids = [p["group_id"] for p in out["products"]]
    assert len(ids) == len(set(ids))
    top = [p for p in out["products"] if p["category"] == "SSD"][:3]
    assert all(p["store_count"] == 2 for p in top)                    # most-stocked parts come first
    assert "hdd-msi-99" in ids                                        # an all-out-of-stock part is included
    assert "ssd-msi-500" in ids                                       # so are the longest title and the highest price
    assert {x["group_id"] for x in out["offers"]} == set(ids)
    assert {r["store"] for r in out["runs"]} == {"a", "b"} and len(out["runs"]) == 2
    assert len(out["benchmarks"]) == 200
    assert all("_id" not in p for p in out["products"])


def test_export_is_plain_json_with_iso_dates():
    text = json.dumps(export(seeded(), per_category=2))
    assert "2026-10-04T03:00:00Z" in text
