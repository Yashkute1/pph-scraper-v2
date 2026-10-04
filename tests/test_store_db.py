from datetime import datetime, timedelta, timezone

import mongomock
import pytest

from pph.store_db import gate, write_store, write_rollup, ensure_indexes, offer_id

T0 = datetime(2026, 10, 4, 3, 0)          # naive UTC, as MongoDB returns it


def day(n): return T0 + timedelta(days=n)


@pytest.fixture
def db(): return mongomock.MongoClient().pph_site


def o(store, n, price=1000, in_stock=True, gid=None):
    return {"store": store, "url": f"https://{store}.test/p/{n}", "title": f"Part number {n}", "price": price, "mrp": price,
            "in_stock": in_stock, "image": "", "brand": "MSI", "category": "SSD", "model_key": str(n),
            "group_id": gid or f"ssd-msi-{n}", "specs": {}}


@pytest.mark.parametrize("fetched,previous,blocked,ok,status", [
    (100, 0, False, True, "ok"), (60, 100, False, True, "ok"), (59, 100, False, False, "partial"),
    (0, 100, False, False, "failed"), (0, 0, False, False, "failed"), (500, 100, True, False, "blocked")])
def test_gate(fetched, previous, blocked, ok, status):
    assert gate(fetched, previous, blocked) == (ok, status)


def test_first_run_writes_and_records_run(db):
    run = write_store(db, "a", [o("a", 1), o("a", 2)], T0, blocked=False)
    assert (run["status"], run["fetched"], run["written"], run["previous_count"]) == ("ok", 2, 2, 0)
    assert db.offers.count_documents({}) == 2 and db.scrape_runs.count_documents({"store": "a"}) == 1
    doc = db.offers.find_one({"_id": offer_id("a", "https://a.test/p/1")})
    assert (doc["first_seen"], doc["last_seen"], doc["missed_runs"], doc["history"]) == (T0, T0, 0, [{"d": "2026-10-04", "p": 1000}])


def test_untrusted_run_refreshes_what_it_saw_and_touches_nothing_else(db):
    write_store(db, "a", [o("a", n) for n in range(10)], T0, blocked=False)
    run = write_store(db, "a", [o("a", 1, price=950)], day(1), blocked=False)          # 1 of 10 = partial
    assert (run["status"], run["written"]) == ("partial", 1)
    run = write_store(db, "a", [o("a", 2, price=940)], day(2), blocked=True)
    assert (run["status"], run["written"]) == ("blocked", 1)
    docs = {d["url"][-1]: d for d in db.offers.find()}
    assert (docs["1"]["price"], docs["1"]["last_seen"], docs["2"]["price"]) == (950, day(1), 940)
    others = [d for k, d in docs.items() if k not in "12"]
    assert len(others) == 8 and all((d["missed_runs"], d["in_stock"], d["last_seen"], d["price"]) == (0, True, T0, 1000) for d in others)
    assert db.scrape_runs.count_documents({}) == 3


def test_empty_run_writes_nothing(db):
    write_store(db, "a", [o("a", n) for n in range(3)], T0, blocked=False)
    before = list(db.offers.find().sort("_id"))
    run = write_store(db, "a", [], day(1), blocked=False)
    assert (run["status"], run["written"]) == ("failed", 0) and list(db.offers.find().sort("_id")) == before


def test_incomplete_run_is_never_trusted_as_full(db):
    write_store(db, "a", [o("a", n) for n in range(10)], T0, blocked=False)
    run = write_store(db, "a", [o("a", n) for n in range(9)], day(1), blocked=False, complete=False)
    assert run["status"] == "partial" and db.offers.find_one({"url": "https://a.test/p/9"})["missed_runs"] == 0


def test_upsert_keeps_first_seen_and_one_history_point_per_day(db):
    write_store(db, "a", [o("a", 1, price=1000)], T0, False)
    write_store(db, "a", [o("a", 1, price=950)], T0 + timedelta(hours=6), False)   # same day: point replaced
    write_store(db, "a", [o("a", 1, price=900)], day(1), False)
    doc = db.offers.find_one()
    assert doc["first_seen"] == T0 and doc["last_seen"] == day(1) and doc["price"] == 900
    assert doc["history"] == [{"d": "2026-10-04", "p": 950}, {"d": "2026-10-05", "p": 900}]


def test_history_trimmed_to_90_days(db):
    for n in range(95):
        write_store(db, "a", [o("a", 1, price=1000 + n)], day(n), False)
    h = db.offers.find_one()["history"]
    assert len(h) == 90 and h[-1]["p"] == 1094 and h[0]["p"] == 1005


def test_unseen_offer_goes_out_of_stock_at_three_missed_runs(db):
    both = [o("a", 1), o("a", 2), o("a", 3)]
    write_store(db, "a", both, T0, False)
    for n in (1, 2):
        write_store(db, "a", both[:2], day(n), False)
        gone = db.offers.find_one({"url": "https://a.test/p/3"})
        assert (gone["missed_runs"], gone["in_stock"]) == (n, True)
    write_store(db, "a", both[:2], day(3), False)
    gone = db.offers.find_one({"url": "https://a.test/p/3"})
    assert (gone["missed_runs"], gone["in_stock"]) == (3, False)


def test_seen_again_resets_missed_runs(db):
    write_store(db, "a", [o("a", 1), o("a", 2)], T0, False)
    write_store(db, "a", [o("a", 1)], day(1), False)
    write_store(db, "a", [o("a", 1), o("a", 2)], day(2), False)
    assert db.offers.find_one({"url": "https://a.test/p/2"})["missed_runs"] == 0


def test_unseen_for_14_days_is_deleted(db):
    keep = [o("a", n) for n in range(4)]
    write_store(db, "a", keep + [o("a", 9)], T0, False)
    write_store(db, "a", keep, day(13), False)
    assert db.offers.count_documents({}) == 5
    write_store(db, "a", keep, day(15), False)
    assert db.offers.count_documents({}) == 4 and db.offers.find_one({"url": "https://a.test/p/9"}) is None


def test_other_stores_untouched(db):
    write_store(db, "a", [o("a", 1)], T0, False)
    write_store(db, "b", [o("b", 1), o("b", 2)], T0, False)
    for n in (1, 2, 3, 4):
        write_store(db, "b", [o("b", 1)], day(n), False)
    a = db.offers.find_one({"store": "a"})
    assert (a["missed_runs"], a["in_stock"], a["last_seen"]) == (0, True, T0)


def test_duplicate_urls_in_one_run_write_one_offer(db):
    run = write_store(db, "a", [o("a", 1, price=500), o("a", 1, price=450)], T0, False)
    assert db.offers.count_documents({}) == 1 and run["written"] == 1 and db.offers.find_one()["price"] == 450


def test_previous_count_ignores_long_gone_offers(db):
    write_store(db, "a", [o("a", n) for n in range(10)], T0, False)
    for n in (1, 2, 3):
        write_store(db, "a", [o("a", k) for k in range(6)], day(n), False)       # 4 offers now out of stock
    run = write_store(db, "a", [o("a", k) for k in range(4)], day(4), False)     # 4 of 6 live = 67%: ok
    assert (run["status"], run["previous_count"]) == ("ok", 6)


def test_write_rollup_replaces_products_and_drops_vanished_groups(db):
    ensure_indexes(db)
    write_store(db, "a", [o("a", 1, 900, gid="g1"), o("a", 2, gid="g2")], T0, False)
    write_store(db, "b", [o("b", 1, 800, gid="g1")], T0, False)
    out = write_rollup(db, T0)
    assert out["products"] == 2
    g1 = db.products_v2.find_one({"group_id": "g1"})
    assert (g1["best_price"], g1["best_store"], g1["store_count"]) == (800, "b", 2)
    db.offers.delete_many({"group_id": "g2"})
    assert write_rollup(db, day(1))["products"] == 1
    assert [d["group_id"] for d in db.products_v2.find()] == ["g1"]


def test_rollup_keeps_last_products_when_there_are_no_offers(db):
    write_store(db, "a", [o("a", 1, gid="g1")], T0, False)
    write_rollup(db, T0)
    db.offers.delete_many({})
    out = write_rollup(db, day(1))
    assert out["products"] == 0 and out["skipped"] is True and db.products_v2.count_documents({}) == 1


def test_write_rollup_attaches_benchmarks_and_site_fields(db):
    ensure_indexes(db)
    db.benchmarks.insert_one({"bucket": "SSD", "brand": "MSI", "model": "Part number 1", "score": 50.5, "percentile": 40, "rank": 7, "samples": 3})
    write_store(db, "a", [o("a", 1, 900, gid="g1")], T0, False)
    write_rollup(db, T0)
    g1 = db.products_v2.find_one({"group_id": "g1"})
    assert g1["benchmark"]["score"] == 50.5 and g1["category_slug"] == "ssd" and g1["brand_slug"] == "msi"
    assert g1["offers"][0]["id"] == offer_id("a", "https://a.test/p/1") and g1["offers"][0]["checked"] == T0
    assert (g1["drop_pct"], g1["spread_pct"]) == (0, 0)


def test_indexes_for_the_site(db):
    ensure_indexes(db)
    keys = [tuple(i["key"]) for i in db.products_v2.index_information().values()]
    for want in [(("category_slug", 1), ("any_stock", -1), ("store_count", -1), ("best_price", 1)),
                 (("category_slug", 1), ("any_stock", -1), ("best_price", 1)),
                 (("category_slug", 1), ("brand_slug", 1), ("any_stock", -1), ("store_count", -1)),
                 (("any_stock", -1), ("drop_pct", -1)), (("any_stock", -1), ("spread_pct", -1))]:
        assert want in keys, want
