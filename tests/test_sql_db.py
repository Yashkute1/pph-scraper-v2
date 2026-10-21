"""The MySQL back end behaves like the MongoDB one. Needs a scratch database: PPH_TEST_MYSQL=mysql://user:pw@127.0.0.1/pph_test"""
import json
import os
from datetime import datetime, timedelta

import pytest

URL = os.environ.get("PPH_TEST_MYSQL")
pytestmark = pytest.mark.skipif(not URL, reason="PPH_TEST_MYSQL is not set")

T0 = datetime(2026, 10, 4, 3, 0)


def day(n): return T0 + timedelta(days=n)


@pytest.fixture
def db():
    from pph import sql_db
    c = sql_db.connect(URL)
    with c.cursor() as cur:
        for t in ("offers", "products", "product_facets", "product_stores", "scrape_runs", "benchmarks", "legacy_redirects", "group_redirects"):
            cur.execute(f"DROP TABLE IF EXISTS {t}")
    sql_db.ensure_indexes(c)
    yield c
    c.close()


def o(store, n, price=1000, in_stock=True, gid=None):
    return {"store": store, "url": f"https://{store}.test/p/{n}", "title": f"Part number {n} PN{n}X 1TB SSD", "price": price, "mrp": price,
            "in_stock": in_stock, "image": "", "brand": "MSI", "category": "SSD", "model_key": str(n),
            "group_id": gid or f"ssd-msi-{n}", "specs": {"capacity": "1TB"}}


def q(db, sql, *args):
    with db.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def test_first_run_writes_and_records_run(db):
    from pph.sql_db import offer_id, write_store
    run = write_store(db, "a", [o("a", 1), o("a", 2)], T0, blocked=False)
    assert (run["status"], run["fetched"], run["written"], run["previous_count"]) == ("ok", 2, 2, 0)
    assert q(db, "SELECT COUNT(*) FROM offers")[0][0] == 2 and q(db, "SELECT COUNT(*) FROM scrape_runs WHERE store='a'")[0][0] == 1
    row = q(db, "SELECT first_seen, last_seen, missed_runs, history, specs FROM offers WHERE id=%s", offer_id("a", "https://a.test/p/1"))[0]
    assert row[:3] == (T0, T0, 0)
    assert json.loads(row[3]) == [{"d": "2026-10-04", "p": 1000}] and json.loads(row[4]) == {"capacity": "1TB"}


def test_later_runs_keep_first_seen_add_history_and_age_unseen(db):
    from pph.sql_db import write_store
    write_store(db, "a", [o("a", n) for n in range(5)], day(0), blocked=False)
    write_store(db, "a", [o("a", n, 900) for n in range(4)], day(1), blocked=False)     # 4 of 5: trusted, p/4 unseen
    first, hist = q(db, "SELECT first_seen, history FROM offers WHERE url='https://a.test/p/0'")[0]
    assert first == day(0) and [h["p"] for h in json.loads(hist)] == [1000, 900]
    assert q(db, "SELECT missed_runs, in_stock FROM offers WHERE url='https://a.test/p/4'")[0] == (1, 1)
    for n in (2, 3):
        write_store(db, "a", [o("a", k) for k in range(4)], day(n), blocked=False)
    assert q(db, "SELECT missed_runs, in_stock FROM offers WHERE url='https://a.test/p/4'")[0] == (3, 0)
    write_store(db, "a", [o("a", k) for k in range(4)], day(20), blocked=False)
    assert q(db, "SELECT COUNT(*) FROM offers WHERE url='https://a.test/p/4'")[0][0] == 0      # gone after 14 days unseen


def test_untrusted_run_touches_nothing_else(db):
    from pph.sql_db import write_store
    write_store(db, "a", [o("a", n) for n in range(10)], T0, blocked=False)
    run = write_store(db, "a", [o("a", 1, 500)], day(1), blocked=False)
    assert run["status"] == "partial"
    assert q(db, "SELECT MAX(missed_runs) FROM offers")[0][0] == 0
    assert q(db, "SELECT price FROM offers WHERE url='https://a.test/p/1'")[0][0] == 500
    blocked = write_store(db, "a", [], day(2), blocked=True)
    assert blocked["status"] == "blocked" and q(db, "SELECT COUNT(*) FROM offers")[0][0] == 10


def test_out_of_stock_price_is_not_history(db):
    from pph.sql_db import write_store
    write_store(db, "a", [o("a", 1, 1000)], day(0), blocked=False)
    write_store(db, "a", [o("a", 1, 700, in_stock=False)], day(1), blocked=False)
    assert [h["p"] for h in json.loads(q(db, "SELECT history FROM offers")[0][0])] == [1000]


def test_rollup_swaps_in_products_facets_and_stores(db):
    from pph.sql_db import write_rollup, write_store
    write_store(db, "a", [o("a", 1, 1000, gid="g1"), o("a", 2, 50, gid="g2")], T0, blocked=False)
    write_store(db, "b", [o("b", 1, 900, gid="g1")], T0, blocked=False)
    with db.cursor() as cur:
        cur.execute("INSERT INTO benchmarks (bucket, `rank`, doc) VALUES ('SSD', 7, %s)",
                    (json.dumps({"bucket": "SSD", "model": "Part number 1", "score": 50.5, "percentile": 40, "rank": 7, "samples": 3}),))
    out = write_rollup(db, day(1))
    assert out["products"] == 2 and out["bytes"] > 0
    best, store, n, stores, offers, bench = q(db, "SELECT best_price, best_store, store_count, stores, offers, benchmark FROM products WHERE group_id='g1'")[0]
    assert (best, store, n, json.loads(stores)) == (900, "b", 2, ["b", "a"])
    assert json.loads(offers)[0]["checked"] == "2026-10-04T03:00:00Z" and json.loads(bench)["score"] == 50.5
    assert sorted(r[0] for r in q(db, "SELECT store FROM product_stores WHERE group_id='g1'")) == ["a", "b"]
    assert q(db, "SELECT v FROM product_facets WHERE group_id='g1' AND k='capacity'")[0][0] == "1 TB"
    with db.cursor() as cur:
        cur.execute("DELETE FROM offers WHERE group_id='g2'")
    write_rollup(db, day(2))
    assert [r[0] for r in q(db, "SELECT group_id FROM products")] == ["g1"]
    with db.cursor() as cur:
        cur.execute("DELETE FROM offers")
    assert write_rollup(db, day(3))["skipped"] is True and q(db, "SELECT COUNT(*) FROM products")[0][0] == 1


def test_stale_stores(db):
    from pph.sql_db import stale_stores, write_store
    write_store(db, "a", [o("a", 1)], T0, blocked=False)
    write_store(db, "b", [], T0, blocked=True)
    assert stale_stores(db, ["a", "b", "c"], T0 + timedelta(hours=3), 26) == ["b", "c"]


def test_run_command_uses_mysql_when_configured(db, monkeypatch, tmp_path):
    from pph import run as R
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MYSQL_URL", URL)
    monkeypatch.delenv("MONGO_URI", raising=False)
    from pph import sql_db
    sql_db.write_store(db, "a", [o("a", 1)], T0, blocked=False)
    code, out = R.rollup_cmd(now=day(1))
    assert code == 0 and out["products"] == 1


def test_copy_from_mongo_keeps_history_and_rebuilds_products(db):
    import mongomock
    from pph import store_db
    from tools.mongo_to_mysql import copy
    m = mongomock.MongoClient().pph_site
    store_db.write_store(m, "a", [o("a", 1, 1000, gid="g1"), o("a", 2, 50, gid="g2")], day(0), blocked=False)
    store_db.write_store(m, "a", [o("a", 1, 950, gid="g1"), o("a", 2, 50, gid="g2")], day(1), blocked=False)
    store_db.write_rollup(m, day(1))
    m.legacy_redirects.insert_one({"_id": "old1", "group_id": "g1"})
    m.benchmarks.insert_one({"bucket": "SSD", "model": "x", "score": 1.0, "rank": 1})
    counts = copy(m, db)
    assert (counts["offers"], counts["scrape_runs"], counts["benchmarks"], counts["legacy_redirects"], counts["products"]) == (2, 2, 1, 1, 2)
    assert [h["p"] for h in json.loads(q(db, "SELECT history FROM offers WHERE group_id='g1'")[0][0])] == [1000, 950]
    assert q(db, "SELECT first_seen FROM offers WHERE group_id='g1'")[0][0] == day(0)
    assert copy(m, db)["offers"] == 2 and q(db, "SELECT COUNT(*) FROM scrape_runs")[0][0] == 2      # running it again changes nothing


def test_a_dropped_connection_is_reopened_and_the_statement_sent_again(db, monkeypatch):
    import pymysql
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)
    real = pymysql.cursors.Cursor.execute
    calls = {"n": 0}

    def flaky(self, query, args=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise pymysql.err.OperationalError(2006, "MySQL server has gone away")
        return real(self, query, args)
    monkeypatch.setattr(pymysql.cursors.Cursor, "execute", flaky)
    with db.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone() == (1,) and calls["n"] == 2
        calls["n"] = 1                                   # a lost connection *during* a query is not retried: it may have run
        monkeypatch.setattr(pymysql.cursors.Cursor, "execute", lambda self, q, a=None: (_ for _ in ()).throw(pymysql.err.OperationalError(2013, "lost")))
        with pytest.raises(pymysql.err.OperationalError):
            cur.execute("SELECT 1")


def test_rollup_applies_current_categories_and_keeps_old_addresses(db):
    from pph.sql_db import offer_row, write_rollup
    pc = "CHIST Gaming Desktop PC – AMD Ryzen 5 5600 Processor | 32GB DDR4 3200MHz RAM | 512GB NVMe SSD | B450 Motherboard | 650W PSU"
    drone = "flyx E88 Pro 4K Drone with Smart Sensor DDR2 2 GB NVIDIA Chipset 0 bit 0 MHz Graphics Card"
    with db.cursor() as cur:
        from pph.sql_db import _upsert_offers
        _upsert_offers(cur, [
            offer_row("a" * 24, {"store": "amazon", "url": "u1", "title": pc, "price": 100000, "in_stock": True, "category": "Motherboard",
                                 "group_id": "motherboard-chist-5600-b450", "brand": "Generic", "last_seen": T0}),
            offer_row("b" * 24, {"store": "flipkart", "url": "u2", "title": drone, "price": 1600, "in_stock": True, "category": "Motherboard",
                                 "group_id": "motherboard-flyx-e88", "brand": "Generic", "last_seen": T0}),
        ])
    out = write_rollup(db, day(1))
    assert (out["recategorized"], out["removed"], out["redirects"]) == (1, 1, 1)
    assert q(db, "SELECT group_id, category FROM products") == (("desktop-pc-chist-5600-b450", "Desktop PC"),)
    assert q(db, "SELECT old_id, group_id FROM group_redirects") == (("motherboard-chist-5600-b450", "desktop-pc-chist-5600-b450"),)
    assert q(db, "SELECT category FROM offers") == (("Desktop PC",),)


def test_load_redirects_skips_live_and_missing_targets(db):
    from pph.sql_db import write_rollup, write_store
    from tools.load_redirects import load
    write_store(db, "a", [o("a", 1, gid="ssd-msi-new")], T0, blocked=False)
    write_rollup(db, day(1))
    out = load(db, [("ssd-old", "ssd-msi-new"), ("ssd-msi-new", "x"), ("ssd-gone", "nowhere")], T0)
    assert out == {"pairs": 3, "loaded": 1, "skipped": 2}
    assert q(db, "SELECT old_id, group_id FROM group_redirects") == (("ssd-old", "ssd-msi-new"),)


def test_a_statement_lost_mid_way_is_resent_only_when_running_it_twice_is_harmless(db, monkeypatch):
    import pymysql
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)
    real = pymysql.cursors.Cursor.execute
    lost = {"left": 0}

    def flaky(self, query, args=None):
        if lost["left"]:
            lost["left"] -= 1
            raise pymysql.err.OperationalError(2013, "Lost connection to MySQL server during query")
        return real(self, query, args)
    monkeypatch.setattr(pymysql.cursors.Cursor, "execute", flaky)
    with db.cursor() as cur:
        lost["left"] = 1
        cur.execute("SELECT 1")                                  # a read is resent
        assert cur.fetchone() == (1,)
        lost["left"] = 1
        with pytest.raises(pymysql.err.OperationalError):      # the run record is not: it could be written twice
            cur.execute("INSERT INTO scrape_runs (store, started, finished, status) VALUES ('a', NOW(), NOW(), 'ok')")


def test_aging_counts_a_missed_offer_once_per_run_even_if_resent(db):
    from pph.sql_db import write_store
    write_store(db, "a", [o("a", n) for n in range(5)], day(0), blocked=False)
    write_store(db, "a", [o("a", n) for n in range(4)], day(1), blocked=False)
    with db.cursor() as cur:                                    # the same aging statement sent again for the same run
        unseen = "store=%s AND (last_seen IS NULL OR last_seen<%s)"
        cur.execute(f"UPDATE offers SET missed_runs=missed_runs+1, aged_at=%s WHERE {unseen} AND (aged_at IS NULL OR aged_at<%s)", (day(1), "a", day(1), day(1)))
    assert q(db, "SELECT missed_runs FROM offers WHERE url='https://a.test/p/4'")[0][0] == 1


def test_database_errors_report_their_number_but_no_message():
    import pymysql
    from pph.run import safe_error
    assert safe_error(pymysql.err.OperationalError(2013, "Lost connection to 'secret-host'")) == "OperationalError 2013"
    assert safe_error(ValueError("x")) == "ValueError"


def test_rollup_joins_one_product_listed_under_two_titles(db):
    from pph.sql_db import _upsert_offers, offer_row, write_rollup
    with db.cursor() as cur:
        _upsert_offers(cur, [
            offer_row("c" * 24, {"store": "mdcomputers", "url": "u1", "title": "Crucial P3 Plus 1TB PCIe M.2 2280 SSD (CT1000P3PSSD8)", "price": 6200,
                                 "in_stock": True, "category": "SSD", "group_id": "ssd-crucial-1tb-2280-ct1000p3pssd8-p3-plus", "brand": "Crucial", "last_seen": T0}),
            offer_row("d" * 24, {"store": "amazon", "url": "u2", "title": "CRUCIAL P3 PLUS 1TB M.2 NVME PCIE GEN 4.0 INTERNAL SSD (CT1000P3PSSD8)", "price": 6400,
                                 "in_stock": True, "category": "SSD", "group_id": "ssd-crucial-1tb-ct1000p3pssd8-p3-plus", "brand": "Crucial", "last_seen": T0}),
        ])
    out = write_rollup(db, day(1))
    assert out["merged"] == 1
    assert q(db, "SELECT group_id, store_count, best_price FROM products") == (("ssd-crucial-1tb-ct1000p3pssd8-p3-plus", 2, 6200),)
    assert q(db, "SELECT old_id, group_id FROM group_redirects") == (("ssd-crucial-1tb-2280-ct1000p3pssd8-p3-plus", "ssd-crucial-1tb-ct1000p3pssd8-p3-plus"),)
