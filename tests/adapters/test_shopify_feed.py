import json
from pph.adapters.shopify_feed import iter_offers
from .helpers import FakeFetcher

B = "https://shop.test"
CFG = {"base": B}


def prod(handle, variants, image="https://cdn.test/a.jpg", title=None):
    return {"handle": handle, "title": title or handle.upper(), "vendor": "MSI",
            "variants": variants, "images": [{"src": image}] if image else []}


def v(price, compare=None, available=True, sku="S"):
    return {"price": price, "compare_at_price": compare, "available": available, "sku": sku}


def feed(*products): return json.dumps({"products": list(products)})


def test_one_offer_per_product_cheapest_available_variant():
    f = FakeFetcher({B + "/products.json?limit=250&page=1": feed(
        prod("gpu-a", [v("30000.00", "35000.00"), v("28000.00", "33000.00"), v("1000.00", available=False)]),
        prod("gpu-b", [v("500.00", available=False)], image=None))}, default=feed())
    a, b = list(iter_offers(CFG, f))
    assert (a["title"], a["price"], a["mrp"], a["url"], a["image"], a["in_stock"]) == \
           ("GPU-A", "28000.00", "33000.00", B + "/products/gpu-a", "https://cdn.test/a.jpg", True)
    assert (b["in_stock"], b["image"], b["price"], b["mrp"]) == (False, "", "500.00", None)


def test_pages_until_empty():
    f = FakeFetcher({B + "/products.json?limit=250&page=1": feed(prod("a", [v("1")])),
                     B + "/products.json?limit=250&page=2": feed(prod("b", [v("2")]))}, default=feed())
    assert [o["url"][-1] for o in iter_offers(CFG, f)] == ["a", "b"]
    assert f.calls[-1].endswith("page=3")


def test_product_without_variants_is_skipped():
    f = FakeFetcher({B + "/products.json?limit=250&page=1": feed(prod("a", []), prod("b", [v("2")]))}, default=feed())
    assert [o["url"] for o in iter_offers(CFG, f)] == [B + "/products/b"]


def test_walks_collections_when_main_feed_hits_cap_and_never_repeats():
    routes = {B + "/products.json?limit=250&page=1": feed(prod("a", [v("1")]), prod("b", [v("2")])),
              B + "/collections.json?limit=250&page=1": json.dumps({"collections": [{"handle": "gpus"}, {"handle": "cpus"}]}),
              B + "/collections/gpus/products.json?limit=250&page=1": feed(prod("a", [v("1")]), prod("c", [v("3")])),
              B + "/collections/cpus/products.json?limit=250&page=1": feed(prod("d", [v("4")]))}
    f = FakeFetcher(routes, default=json.dumps({"products": [], "collections": []}))
    urls = [o["url"].rsplit("/", 1)[1] for o in iter_offers(dict(CFG, feed_cap=2), f)]
    assert urls == ["a", "b", "c", "d"]


def test_no_collection_walk_below_cap():
    f = FakeFetcher({B + "/products.json?limit=250&page=1": feed(prod("a", [v("1")]))}, default=feed())
    list(iter_offers(CFG, f))
    assert not any("collections" in c for c in f.calls)


def test_empty_or_missing_feed_raises():
    import pytest
    from pph.adapters.common import EmptyListingError
    with pytest.raises(EmptyListingError): list(iter_offers(CFG, FakeFetcher({}, default=feed())))
    with pytest.raises(EmptyListingError): list(iter_offers(CFG, FakeFetcher({}, default="<html>redesign</html>")))
