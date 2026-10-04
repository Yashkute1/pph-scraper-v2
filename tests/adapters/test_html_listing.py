import pathlib, pytest
from pph.adapters.html_listing import iter_offers
from pph.adapters.common import EmptyListingError
from pph.fetch import Page, BlockedError
from pph.normalize import parse_price, normalize
from pph.stores import STORES
from .helpers import FakeFetcher

FX = pathlib.Path(__file__).parent.parent / "fixtures" / "html"
HTML_STORES = ["primeabgb", "vedantcomputers", "mdcomputers", "theitdepot", "flipkart", "amazon"]
EXPECT = {"primeabgb": 24, "vedantcomputers": 12, "mdcomputers": 20, "theitdepot": 12, "flipkart": 38, "amazon": 20}
EMPTY = "<html><body><p>nothing here</p></body></html>"


def one_page(store):
    """Config narrowed to a single start URL; the fixture is served for it, every other URL is an empty page."""
    cfg = dict(STORES[store]); cfg["start_urls"] = cfg["start_urls"][:1]
    html = (FX / f"{store}.html").read_text(encoding="utf-8")
    return cfg, FakeFetcher({cfg["start_urls"][0]: html}, default=EMPTY)


@pytest.mark.parametrize("store", HTML_STORES)
def test_store_fixture_parses(store):
    cfg, f = one_page(store)
    offers = list(iter_offers(cfg, f))
    assert len(offers) >= EXPECT[store], len(offers)
    for o in offers:
        assert o["title"] and len(o["title"]) > 8, o
        assert parse_price(o["price"]) > 0, o
        assert o["url"].startswith("https://"), o
        assert o["mrp"] is None or parse_price(o["mrp"]) >= parse_price(o["price"]), o
    assert sum(1 for o in offers if o["image"].startswith("https://")) >= 0.9 * len(offers)
    assert len({o["url"] for o in offers}) == len(offers)
    kept = [n for n in (normalize(o, store) for o in offers) if n]
    # real PC products survive the cleaning rules; marketplaces mix in junk (mobile VR boxes etc.) that must not
    assert len(kept) >= (0.6 if store == "flipkart" else 0.8) * len(offers)


def test_amazon_urls_are_canonical_dp_links():
    cfg, f = one_page("amazon")
    assert all(o["url"].startswith("https://www.amazon.in/dp/") and len(o["url"]) == 35 for o in iter_offers(cfg, f))


def test_out_of_stock_label_detected():
    cfg, f = one_page("theitdepot")
    offers = list(iter_offers(cfg, f))
    assert any(o["in_stock"] is False for o in offers) and any(o["in_stock"] for o in offers)


CFG = {"base": "https://s.test", "start_urls": ["https://s.test/c"], "card": "div.card", "title": ["a.t::text"],
       "link": ["a.t::attr(href)"], "price": ["span.p::text"], "mrp": ["span.m::text"], "image": "img",
       "page_param": "page", "max_pages": 3}


def cards(*items):
    return "<html><body>" + "".join(
        f'<div class="card"><a class="t" href="{u}">{t}</a>{img}<span class="p">{p}</span></div>' for u, t, p, img in items) + "</body></html>"


def test_first_page_without_cards_raises():
    with pytest.raises(EmptyListingError):
        list(iter_offers(CFG, FakeFetcher({}, default=EMPTY)))


def test_pagination_follows_page_param_and_stops_at_max_pages():
    page = lambda n: cards((f"/p/{n}", f"Product number {n}", "₹100", ""))
    f = FakeFetcher({"https://s.test/c": page(1), "https://s.test/c?page=2": page(2), "https://s.test/c?page=3": page(3),
                     "https://s.test/c?page=4": page(4)}, default=EMPTY)
    assert [o["url"] for o in iter_offers(CFG, f)] == ["https://s.test/p/1", "https://s.test/p/2", "https://s.test/p/3"]
    assert "https://s.test/c?page=4" not in f.calls


def test_pagination_stops_when_a_page_repeats():
    same = cards(("/p/1", "Product number 1", "₹100", ""))
    f = FakeFetcher({}, default=same)
    assert len(list(iter_offers(dict(CFG, max_detail=0), f))) == 1 and len(f.calls) == 2


def test_next_page_selector_is_followed():
    cfg = dict(CFG, page_param=None, next_page=["a.next::attr(href)"])
    p1 = cards(("/p/1", "Product number 1", "₹100", "")).replace("</body>", '<a class="next" href="/c/page/2/">n</a></body>')
    f = FakeFetcher({"https://s.test/c": p1, "https://s.test/c/page/2/": cards(("/p/2", "Product number 2", "₹5", ""))}, default=EMPTY)
    assert [o["url"][-1] for o in iter_offers(cfg, f)] == ["1", "2"]


@pytest.mark.parametrize("img,want", [
    ('<img src="" data-src="https://i.test/a.jpg">', "https://i.test/a.jpg"),
    ('<img src="data:image/gif;base64,AAAA" data-lazy-src="/b.jpg">', "https://s.test/b.jpg"),
    ('<img src="https://i.test/tiny.jpg" srcset="https://i.test/s.jpg 300w, https://i.test/l.jpg 800w">', "https://i.test/l.jpg"),
    ('<img src="https://i.test/c.jpg">', "https://i.test/c.jpg"), ("", "")])
def test_lazy_image_attributes(img, want):
    f = FakeFetcher({"https://s.test/c": cards(("/p/1", "Product number 1", "₹100", img))}, default=EMPTY)
    assert next(iter_offers(dict(CFG, max_detail=0), f))["image"] == want


LD = '<html><head><script type="application/ld+json">{"@type":"Product","name":"X","image":["https://i.test/ld.jpg"],' \
     '"offers":{"@type":"Offer","price":"4999","availability":"https://schema.org/OutOfStock"}}</script></head></html>'


def test_detail_page_fetched_only_for_incomplete_cards():
    listing = cards(("/p/full", "Complete product one", "₹100", '<img src="https://i.test/c.jpg">'), ("/p/bare", "Incomplete product two", "", ""))
    f = FakeFetcher({"https://s.test/c": listing, "https://s.test/p/bare": LD}, default=EMPTY)
    a, b = list(iter_offers(dict(CFG, max_pages=1), f))
    assert f.calls.count("https://s.test/p/bare") == 1 and "https://s.test/p/full" not in f.calls
    assert (b["price"], b["image"], b["in_stock"]) == ("4999", "https://i.test/ld.jpg", False)


def test_detail_fetches_are_capped():
    listing = cards(*[(f"/p/{n}", f"Incomplete product {n}", "", "") for n in range(6)])
    f = FakeFetcher({"https://s.test/c": listing}, default=LD)
    list(iter_offers(dict(CFG, max_pages=1, max_detail=2), f))
    assert sum("/p/" in c for c in f.calls) == 2


class Flaky(FakeFetcher):
    def get(self, url):
        if url in self.blocked:
            self.calls.append(url); raise BlockedError(url, 403, fatal=self.fatal)
        return super().get(url)


def test_one_blocked_category_is_skipped_but_fatal_block_propagates():
    cfg = dict(CFG, start_urls=["https://s.test/c", "https://s.test/d", "https://s.test/e"], max_pages=1)
    pg = lambda n: cards((f"/p/{n}", f"Product number {n}", "₹100", ""))
    f = Flaky({"https://s.test/c": pg(1), "https://s.test/e": pg(3)}, default=EMPTY); f.blocked, f.fatal = {"https://s.test/d"}, False
    assert [o["url"][-1] for o in iter_offers(cfg, f)] == ["1", "3"]
    f = Flaky({"https://s.test/c": pg(1)}, default=EMPTY); f.blocked, f.fatal = {"https://s.test/d"}, True
    with pytest.raises(BlockedError): list(iter_offers(cfg, f))
