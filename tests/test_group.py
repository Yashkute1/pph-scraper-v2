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
    assert set(row["offers"][0]) == {"id", "store", "price", "in_stock", "url", "checked"}
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


def hist(prices, end_day=4):
    """One point per day ending 2026-10-<end_day>, oldest first."""
    from datetime import date, timedelta
    end = date(2026, 10, end_day)
    return [{"d": (end - timedelta(days=len(prices) - 1 - i)).isoformat(), "p": p} for i, p in enumerate(prices)]


def test_offers_carry_id_and_checked_time():
    seen = datetime(2026, 10, 4, 1, tzinfo=timezone.utc)
    row, = rollup([offer("a", 100, _id="abc123", last_seen=seen)], NOW)
    assert row["offers"][0] == {"id": "abc123", "store": "a", "price": 100, "in_stock": True, "url": "https://a.test/p", "checked": seen}


def test_slugs():
    row, = rollup([offer("a", 100, brand="Cooler Master", category="PC Case/Chassis")], NOW)
    assert (row["category_slug"], row["brand_slug"]) == ("pc-case-chassis", "cooler-master")
    row, = rollup([offer("a", 100, brand=None)], NOW)
    assert row["brand_slug"] == ""


def test_drop_pct_needs_seven_days():
    row, = rollup([offer("a", 900, history=hist([1000] * 5 + [900]))], NOW)
    assert row["drop_pct"] == 0


def test_drop_pct_against_30_day_median():
    row, = rollup([offer("a", 900, history=hist([1000] * 9 + [900]))], NOW)
    assert row["drop_pct"] == 10.0
    row, = rollup([offer("a", 1100, history=hist([1000] * 9 + [1100]))], NOW)
    assert row["drop_pct"] == 0          # a rise is never negative


def test_drop_pct_uses_lowest_price_per_day_across_stores_and_ignores_old_points():
    a = offer("a", 800, history=hist([5000] * 40 + [1000] * 29 + [800]))      # the 5000s are older than 30 days
    b = offer("b", 1200, history=hist([1200] * 10))
    row, = rollup([a, b], NOW)
    assert row["drop_pct"] == 20.0


def test_drop_pct_zero_when_nothing_in_stock():
    row, = rollup([offer("a", 900, in_stock=False, history=hist([1000] * 9 + [900]))], NOW)
    assert row["drop_pct"] == 0


def test_spread_pct():
    assert rollup([offer("a", 900)], NOW)[0]["spread_pct"] == 0
    row, = rollup([offer("a", 900), offer("b", 1000), offer("c", 1100)], NOW)
    assert row["spread_pct"] == 14.3      # 900 against the median of the other two, 1050
    row, = rollup([offer("a", 900), offer("b", 1000, in_stock=False)], NOW)
    assert row["spread_pct"] == 0        # only in-stock offers are compared


def test_spread_over_sixty_percent_is_treated_as_a_mismatch():
    assert rollup([offer("a", 300), offer("b", 1000)], NOW)[0]["spread_pct"] == 0


def test_benchmark_attached_when_lookup_given():
    from pph.benchmarks import build_lookup
    look = build_lookup([{"bucket": "CPU", "brand": "AMD", "model": "Ryzen 5 5600", "score": 88.4, "percentile": 71, "rank": 60, "samples": 9}])
    row, = rollup([offer("a", 100)], NOW, look)
    assert row["benchmark"] == {"score": 88.4, "percentile": 71, "rank": 60, "total": 1, "model": "Ryzen 5 5600", "bucket": "CPU"}
    assert rollup([offer("a", 100)], NOW)[0]["benchmark"] is None
