import json
from pph.adapters.woo_store_api import iter_offers
from .helpers import FakeFetcher

B = "https://woo.test"
U = B + "/wp-json/wc/store/v1/products?per_page=100&page=%d"


def p(name, price, regular, minor=2, stock=True, img="https://i.test/x.jpg"):
    return {"name": name, "permalink": B + "/product/" + name.lower().replace(" ", "-") + "/", "sku": "K",
            "prices": {"price": price, "regular_price": regular, "currency_minor_unit": minor},
            "images": [{"src": img}] if img else [], "is_in_stock": stock}


def test_minor_units_converted():
    f = FakeFetcher({U % 1: json.dumps([p("ASUS ROG Thor 1600W", "7650000", "8000000"), p("Zero Minor", "4999", "5999", minor=0)])}, default="[]")
    a, b = list(iter_offers({"base": B}, f))
    assert (a["price"], a["mrp"], a["title"], a["in_stock"], a["image"]) == (76500.0, 80000.0, "ASUS ROG Thor 1600W", True, "https://i.test/x.jpg")
    assert a["url"] == B + "/product/asus-rog-thor-1600w/"
    assert (b["price"], b["mrp"]) == (4999.0, 5999.0)


def test_out_of_stock_missing_image_and_html_entities_in_name():
    f = FakeFetcher({U % 1: json.dumps([p("Corsair 4000D &#8211; Black &amp; White", "850000", "", stock=False, img=None)])}, default="[]")
    o, = list(iter_offers({"base": B}, f))
    assert (o["in_stock"], o["image"], o["mrp"], o["title"]) == (False, "", None, "Corsair 4000D – Black & White")


def test_pages_until_empty_list():
    f = FakeFetcher({U % 1: json.dumps([p("A one", "100", "100")]), U % 2: json.dumps([p("B two", "200", "200")])}, default="[]")
    assert [o["title"] for o in iter_offers({"base": B}, f)] == ["A one", "B two"]
    assert f.calls == [U % 1, U % 2, U % 3]


def test_empty_or_non_json_first_page_raises():
    import pytest
    from pph.adapters.common import EmptyListingError
    with pytest.raises(EmptyListingError): list(iter_offers({"base": B}, FakeFetcher({}, default="[]")))
    with pytest.raises(EmptyListingError): list(iter_offers({"base": B}, FakeFetcher({}, default="<html>x</html>")))
