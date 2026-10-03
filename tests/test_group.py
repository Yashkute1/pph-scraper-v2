from datetime import datetime, timezone
from pph.group import rollup

NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)


def offer(store, price, group_id="cpu-amd-5600", in_stock=True, mrp=None, image="", history=None, url=None, **kw):
    return dict({"store": store, "url": url or f"https://{store}.test/p", "title": f"AMD Ryzen 5 5600 ({store})", "price": price,
                 "mrp": mrp if mrp is not None else price, "in_stock": in_stock, "image": image, "brand": "AMD",
                 "category": "Processor/CPU", "model_key": "5600", "group_id": group_id, "specs": {"socket": "AM4"},
                 "history": history or [{"d": "2026-10-04", "p": price}]}, **kw)


def test_three_stores_one_row():
    row, = rollup([offer("mdcomputers", 13499), offer("primeabgb", 12999, mrp=16999), offer("vedantcomputers", 13299)], NOW)
    assert (row["group_id"], row["best_price"], row["best_store"], row["store_count"], row["any_stock"]) == \
           ("cpu-amd-5600", 12999, "primeabgb", 3, True)
    assert row["best_url"] == "https://primeabgb.test/p" and row["mrp"] == 16999
    assert [o["price"] for o in row["offers"]] == [12999, 13299, 13499]
    assert set(row["offers"][0]) == {"store", "price", "in_stock", "url"}
    assert row["stores"] == ["primeabgb", "vedantcomputers", "mdcomputers"]
    assert (row["title"], row["brand"], row["category"], row["specs"], row["updated_at"]) == \
           ("AMD Ryzen 5 5600 (primeabgb)", "AMD", "Processor/CPU", {"socket": "AM4"}, NOW)


def test_in_stock_beats_cheaper_out_of_stock():
    row, = rollup([offer("a", 12000, in_stock=False), offer("b", 13299)], NOW)
    assert (row["best_price"], row["best_store"], row["any_stock"]) == (13299, "b", True)
    assert [o["store"] for o in row["offers"]] == ["b", "a"]


def test_mrp_comes_from_the_best_offer_only():
    row, = rollup([offer("a", 12999, mrp=12999), offer("b", 13500, mrp=29999)], NOW)
    assert row["mrp"] is None        # best offer has no discount; another store's mrp must not be borrowed


def test_mrp_dropped_when_implausible():
    assert rollup([offer("a", 1000, mrp=900)], NOW)[0]["mrp"] is None
    assert rollup([offer("a", 1000, mrp=7999)], NOW)[0]["mrp"] is None      # 87% "discount"
    assert rollup([offer("a", 1000, mrp=4000)], NOW)[0]["mrp"] == 4000      # 75% is allowed


def test_image_falls_back_to_any_member():
    row, = rollup([offer("a", 100), offer("b", 200, image="https://i.test/b.jpg")], NOW)
    assert row["image"] == "https://i.test/b.jpg"


def test_low_90d_is_min_of_all_history_points():
    h = [{"d": "2026-09-01", "p": 11000}, {"d": "2026-10-04", "p": 13000}]
    row, = rollup([offer("a", 13000, history=h), offer("b", 12500)], NOW)
    assert row["low_90d"] == 11000


def test_two_offers_same_store_count_once_and_keep_cheapest():
    row, = rollup([offer("a", 500, url="https://a.test/1"), offer("a", 450, url="https://a.test/2"), offer("b", 600)], NOW)
    assert row["store_count"] == 2
    assert [(o["store"], o["price"]) for o in row["offers"]] == [("a", 450), ("b", 600)]


def test_all_out_of_stock():
    row, = rollup([offer("a", 900, in_stock=False), offer("b", 800, in_stock=False)], NOW)
    assert (row["any_stock"], row["best_price"], row["best_store"]) == (False, 800, "b")


def test_separate_groups_and_empty_input():
    rows = rollup([offer("a", 1), offer("b", 2, group_id="other")], NOW)
    assert sorted(r["group_id"] for r in rows) == ["cpu-amd-5600", "other"]
    assert rollup([], NOW) == []
