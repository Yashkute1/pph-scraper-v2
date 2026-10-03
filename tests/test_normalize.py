import pytest
from pph.normalize import normalize, parse_price, brand_of, canonical_url


def test_golden_parity(titles, golden):
    bad = []
    for row, want in zip(titles, golden):
        got = normalize(dict(title=row["title"], price=row["price"], mrp=row["mrp"], url="https://x.test/p"), row["store"])
        if want["rejected"]:
            if got is not None: bad.append((row["title"], "should be rejected", got["category"]))
            continue
        if got is None:
            bad.append((row["title"], "wrongly rejected", want["category"])); continue
        for k in ("title", "price", "mrp", "brand", "category", "model_key", "group_id", "specs"):
            if got[k] != want[k]: bad.append((row["title"], k, got[k], want[k]))
    assert not bad, f"{len(bad)} mismatches, first 15: {bad[:15]}"


@pytest.mark.parametrize("raw,want", [("₹1,23,499.00", 123499), ("Rs 4,999/-", 4999), (8999, 8999),
    ("call for price", 0), ("₹26,370 ₹43,349", 26370), ("99999", 0), (None, 0), (12999.5, 13000)])
def test_parse_price(raw, want): assert parse_price(raw) == want


def test_price_above_category_cap_is_rejected():
    assert normalize({"title": "Logitech G102 Gaming Mouse 8000 DPI", "price": "160024003200", "url": "u"}, "s") is None


def test_brand_is_canonical():
    assert brand_of("Asus Dual RTX 5060") == brand_of("ASUS DUAL RTX 5060") == "ASUS"
    assert brand_of("Zotac Gaming RTX 5070") == brand_of("ZOTAC GAMING RTX 5070") == "ZOTAC"


def test_store_supplied_brand_is_canonicalised():
    a = normalize({"title": "Zotac Gaming GeForce RTX 5070 Twin Edge", "price": 60000, "url": "u", "brand": "Zotac"}, "s")
    b = normalize({"title": "ZOTAC GAMING GeForce RTX 5070 Twin Edge", "price": 61000, "url": "u2", "brand": "ZOTAC"}, "s")
    assert a["brand"] == b["brand"] == "ZOTAC" and a["group_id"] == b["group_id"]


@pytest.mark.parametrize("a,b", [
    ("https://www.amazon.in/Some-Name/dp/B0ABCDEFGH/ref=sr_1_3?crid=1&qid=2", "https://www.amazon.in/dp/B0ABCDEFGH"),
    ("https://elitehubs.com/products/x?variant=1&utm_source=a", "https://elitehubs.com/products/x"),
    ("https://www.flipkart.com/n/p/itm123?pid=ABC&lid=Z&marketplace=F", "https://www.flipkart.com/n/p/itm123?pid=ABC"),
    ("HTTPS://MDComputers.in/product/abc#reviews", "https://mdcomputers.in/product/abc"),
    ("https://www.theitdepot.com/index.php?route=product/product&product_id=55&x=1", "https://www.theitdepot.com/index.php?route=product/product&product_id=55")])
def test_canonical_url(a, b): assert canonical_url(a) == b


def test_rejects_titleless_and_priceless():
    assert normalize({"price": 100, "url": "u"}, "s") is None
    assert normalize({"title": "AMD Ryzen 5 5600 Processor", "price": "call", "url": "u"}, "s") is None
    assert normalize({"title": "AMD Ryzen 5 5600 Processor", "price": 9999}, "s") is None  # no url


def test_output_shape():
    n = normalize({"title": "AMD Ryzen 5 5600 Processor", "price": "₹12,999", "mrp": "₹16,999", "url": "https://a.test/p?x=1", "image": "i"}, "elitehubs")
    assert set(n) == {"store", "url", "title", "price", "mrp", "in_stock", "image", "brand", "category", "model_key", "group_id", "specs"}
    assert (n["store"], n["price"], n["mrp"], n["category"], n["in_stock"], n["url"]) == ("elitehubs", 12999, 16999, "Processor/CPU", True, "https://a.test/p")
