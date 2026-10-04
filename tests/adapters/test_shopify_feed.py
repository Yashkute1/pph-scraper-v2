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


class Scripted(FakeFetcher):
    """routes values may be a list: one body per successive call to that URL."""
    def get(self, url):
        body = self.routes.get(url, self.default)
        if isinstance(body, list):
            self.calls.append(url)
            from pph.fetch import Page
            b = body.pop(0) if len(body) > 1 else body[0]
            return Page(200, b, url)
        return super().get(url)


def test_a_page_that_fails_once_is_retried_and_the_feed_continues():
    f = Scripted({B + "/products.json?limit=250&page=1": feed(prod("a", [v("1")])),
                  B + "/products.json?limit=250&page=2": ["<html>502 Bad Gateway</html>", feed(prod("b", [v("2")]))]}, default=feed())
    assert [o["url"][-1] for o in iter_offers(CFG, f)] == ["a", "b"]
    assert f.calls.count(B + "/products.json?limit=250&page=2") == 2


def test_a_page_that_keeps_failing_ends_the_run_as_incomplete_without_other_requests():
    import pytest
    from pph.adapters.common import IncompleteError
    f = Scripted({B + "/products.json?limit=250&page=1": feed(prod("a", [v("1")])),
                  B + "/products.json?limit=250&page=2": ["<html>502</html>"]}, default=feed())
    got = []
    with pytest.raises(IncompleteError):
        for o in iter_offers(CFG, f): got.append(o)
    assert len(got) == 1                                   # what was fetched is still handed over
    assert f.calls.count(B + "/products.json?limit=250&page=2") == 3 and not any("collections" in c for c in f.calls)


def test_empty_or_missing_feed_raises():
    import pytest
    from pph.adapters.common import EmptyListingError
    with pytest.raises(EmptyListingError): list(iter_offers(CFG, FakeFetcher({}, default=feed())))
    with pytest.raises(EmptyListingError): list(iter_offers(CFG, FakeFetcher({}, default="<html>redesign</html>")))
