"""What one Creators API item means for a scraped Amazon offer."""
from pph.amazon_api import apply, asin_of, classify


def item(type_, amount=None, buybox=True):
    return {"asin": "B0TEST0001", "offersV2": {"listings": [
        {"availability": {"type": type_}, "isBuyBoxWinner": buybox, "price": {"money": {"amount": amount}}}]}}


def test_asin_of():
    assert asin_of("https://www.amazon.in/dp/B0CJJKF2Q2") == "B0CJJKF2Q2"
    assert asin_of("https://x.test/p/1") is None


def test_classify_kinds():
    assert classify(item("IN_STOCK", 1499.0)) == ("in_stock", 1499.0)
    assert classify(item("OUT_OF_STOCK"))[0] == "out_of_stock"
    assert classify(item("PREORDER"))[0] == "preorder"
    assert classify(item("AVAILABLE_DATE"))[0] == "other"


def test_missing_item_or_listing():
    assert classify(None) == ("missing", None)
    assert classify({"asin": "B0X"}) == ("missing", None)
    assert classify({"asin": "B0X", "offersV2": {"listings": []}}) == ("missing", None)


def test_buy_box_listing_wins():
    it = item("IN_STOCK", 1000.0, buybox=False)
    it["offersV2"]["listings"].append(
        {"availability": {"type": "IN_STOCK"}, "isBuyBoxWinner": True, "price": {"money": {"amount": 900.0}}})
    assert classify(it) == ("in_stock", 900.0)


def test_a_bad_price_is_never_used():
    for amount in (None, 0, -5):
        assert classify(item("IN_STOCK", amount)) == ("in_stock", None)


def test_apply_rules():
    base = {"price": 1000, "mrp": 1200, "in_stock": True}
    got = apply(base, "in_stock", 1499.0)
    assert (got["price"], got["mrp"], got["in_stock"]) == (1499, 1499, True)
    assert base == {"price": 1000, "mrp": 1200, "in_stock": True}
    for kind in ("out_of_stock", "missing", "preorder"):
        got = apply(base, kind, None)
        assert (got["price"], got["in_stock"]) == (1000, False)
    for stock in (True, False):
        got = apply({**base, "in_stock": stock}, "other", 1100.0)
        assert (got["price"], got["in_stock"]) == (1100, stock)
    got = apply(base, "in_stock", None)
    assert (got["price"], got["in_stock"]) == (1000, True)
