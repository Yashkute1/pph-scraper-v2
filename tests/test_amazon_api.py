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
    assert classify(item("AVAILABLE_DATE"))[0] == "in_stock"      # buyable now with a stated delivery date (checked on amazon.in, 10 of 10)


def test_scarce_listing_is_in_stock():
    assert classify(item("IN_STOCK_SCARCE", 1499.0)) == ("in_stock", 1499.0)
    got = apply({"price": 1000, "mrp": 1200, "in_stock": False}, *classify(item("IN_STOCK_SCARCE", 1499.0)))
    assert (got["price"], got["in_stock"]) == (1499, True)


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


# ---- client: credentials, token, pacing, stop rules ----
import json

import pytest

from pph.amazon_api import AmazonApi, ApiStop, credentials

SECRET = "s3cr3t-VALUE-xyz"
CID = "amzn1.application-oa2-client.abc123"
ENV = {"AMAZON_CREATORS_CREDENTIAL_ID": CID, "AMAZON_CREATORS_CREDENTIAL_SECRET": SECRET,
       "AMAZON_CREATORS_CREDENTIAL_VERSION": "v3.2", "AMAZON_PARTNER_TAG": "shadow-21"}
TOKEN_OK = (200, json.dumps({"access_token": "T", "expires_in": 3600}))


def ok_items(*asins):
    return 200, json.dumps({"itemsResult": {"items": [{"asin": a} for a in asins]}})


class Fake:
    """Fake post, clock and sleep. Answers come from a list, in order; the clock moves only when sleep or tick does."""
    def __init__(self, *answers):
        self.answers, self.calls, self.sleeps, self.starts, self.now = list(answers), [], [], [], 1000.0

    def post(self, url, body, headers):
        self.calls.append((url, body, headers))
        self.starts.append(self.now)
        return self.answers.pop(0)

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s

    def clock(self):
        return self.now

    def api(self):
        return AmazonApi(credentials(ENV), post=self.post, sleep=self.sleep, clock=self.clock)


def test_credentials_need_all_four():
    c = credentials(ENV)
    assert c["version"] == "3.2" and c["id"] == CID and c["secret"] == SECRET and c["tag"] == "shadow-21"
    for key in ENV:
        assert credentials({k: v for k, v in ENV.items() if k != key}) is None
        assert credentials({**ENV, key: "  "}) is None


def test_get_items_returns_items_by_asin():
    f = Fake(TOKEN_OK, ok_items("B0AAAAAAA1", "B0AAAAAAA2"))
    got = f.api().get_items(["B0AAAAAAA1", "B0AAAAAAA2", "B0AAAAAAA3"])
    assert got == {"B0AAAAAAA1": {"asin": "B0AAAAAAA1"}, "B0AAAAAAA2": {"asin": "B0AAAAAAA2"}}
    token_url, token_body, _ = f.calls[0]
    assert token_url == "https://api.amazon.co.uk/auth/o2/token"
    assert token_body == {"grant_type": "client_credentials", "client_id": CID, "client_secret": SECRET,
                          "scope": "creatorsapi::default"}
    url, body, headers = f.calls[1]
    assert url == "https://creatorsapi.amazon/catalog/v1/getItems"
    assert body["itemIds"] == ["B0AAAAAAA1", "B0AAAAAAA2", "B0AAAAAAA3"]
    assert body["itemIdType"] == "ASIN" and body["marketplace"] == "www.amazon.in" and body["partnerTag"] == "shadow-21"
    assert body["resources"] == ["itemInfo.title", "offersV2.listings.price", "offersV2.listings.availability", "images.primary.large"]
    assert headers["Authorization"] == "Bearer T" and headers["x-marketplace"] == "www.amazon.in"


def test_token_is_reused_and_refreshed():
    f = Fake(TOKEN_OK, ok_items("A"), ok_items("A"), TOKEN_OK, ok_items("A"))
    api = f.api()
    api.get_items(["A"])
    api.get_items(["A"])
    assert sum("/auth/o2/token" in c[0] for c in f.calls) == 1
    f.now += 3600 - 120
    api.get_items(["A"])
    assert sum("/auth/o2/token" in c[0] for c in f.calls) == 2


def test_calls_are_at_least_one_second_apart():
    f = Fake(TOKEN_OK, ok_items("A"), ok_items("A"), ok_items("A"))
    api = f.api()
    for _ in range(3):
        api.get_items(["A"])
    assert sum(f.sleeps) >= 2
    assert all(b - a >= 1.0 for a, b in zip(f.starts, f.starts[1:]))


def test_more_than_ten_asins_is_refused():
    with pytest.raises(ValueError):
        Fake().api().get_items([f"B0AAAAAA{i:02d}" for i in range(11)])


def test_429_waits_and_retries_twice_then_stops():
    f = Fake(TOKEN_OK, (429, "{}"), (429, "{}"), (429, "{}"))
    with pytest.raises(ApiStop, match="429"):
        f.api().get_items(["A"])
    assert [c for c in f.sleeps if c >= 5] == [5, 20]
    assert len(f.calls) == 4
    g = Fake(TOKEN_OK, (429, "{}"), ok_items("A"))
    assert g.api().get_items(["A"]) == {"A": {"asin": "A"}}
    assert [c for c in g.sleeps if c >= 5] == [5]


@pytest.mark.parametrize("answers", [
    [TOKEN_OK, (401, "{}")],
    [TOKEN_OK, (403, "{}")],
    [TOKEN_OK, (200, '{"errors": [{"code": "AssociateNotEligible"}]}')],
    [TOKEN_OK, (400, "associatenoteligible")],
    [(400, '{"error": "invalid_client"}')],
])
def test_stop_answers(answers):
    f = Fake(*answers)
    with pytest.raises(ApiStop):
        f.api().get_items(["A"])
    assert f.answers == [] and len(f.calls) == len(answers)
    assert not any(s >= 5 for s in f.sleeps)


def test_bad_answers_stop():
    for bad in [(200, "not json"), (200, "{}"), (500, "oops")]:
        with pytest.raises(ApiStop):
            Fake(TOKEN_OK, bad).api().get_items(["A"])
    with pytest.raises(ApiStop):
        AmazonApi({**credentials(ENV), "version": "9.9"}, post=Fake().post).get_items(["A"])


def test_errors_never_carry_credentials_or_bodies():
    body = json.dumps({"__type": "AccessDenied", "message": f"bad {SECRET} for {CID}"})
    for answers in ([TOKEN_OK, (403, body)], [(400, body)], [TOKEN_OK, (500, f"<html>{SECRET}</html>")]):
        with pytest.raises(ApiStop) as e:
            Fake(*answers).api().get_items(["A"])
        text = str(e.value)
        assert SECRET not in text and CID not in text and "bad" not in text and "html" not in text
        assert "40" in text or "500" in text


def test_error_code_word_only_when_short_token():
    with pytest.raises(ApiStop) as e:
        Fake(TOKEN_OK, (403, '{"code": "AccessDenied"}')).api().get_items(["A"])
    assert str(e.value) == "HTTP 403 AccessDenied"
    with pytest.raises(ApiStop) as e:
        Fake(TOKEN_OK, (403, '{"code": "has spaces and secret"}')).api().get_items(["A"])
    assert str(e.value) == "HTTP 403"


def test_network_error_becomes_stop(monkeypatch):
    import urllib.error
    import urllib.request
    from pph import amazon_api

    def boom(*a, **k):
        raise urllib.error.URLError(f"cannot reach {SECRET}")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(ApiStop) as e:
        amazon_api._post("https://x.test/", {}, {})
    assert str(e.value) == "network URLError" and SECRET not in str(e.value)


def test_other_transport_failures_become_stop(monkeypatch):
    import http.client
    import io
    import urllib.error
    import urllib.request
    from pph import amazon_api

    def raiser(exc):
        def f(*a, **k):
            raise exc
        return f
    for exc, name in [(http.client.IncompleteRead(b"x"), "IncompleteRead"),
                      (http.client.BadStatusLine(SECRET), "BadStatusLine")]:
        monkeypatch.setattr(urllib.request, "urlopen", raiser(exc))
        with pytest.raises(ApiStop) as e:
            amazon_api._post("https://x.test/", {}, {})
        assert str(e.value) == f"network {name}" and SECRET not in str(e.value)

    class BadBody(io.BytesIO):
        def read(self, *a):
            raise ConnectionResetError(SECRET)
    err = urllib.error.HTTPError("https://x.test/", 500, "x", {}, BadBody())
    monkeypatch.setattr(urllib.request, "urlopen", raiser(err))
    with pytest.raises(ApiStop) as e:
        amazon_api._post("https://x.test/", {}, {})
    assert str(e.value) == "network ConnectionResetError" and SECRET not in str(e.value)


# ---- enrich: corrected offers and a short note ----
from pph.amazon_api import enrich, enrich_from_env


def lst(type_, amount=None):
    return {"availability": {"type": type_}, "isBuyBoxWinner": True, "price": {"money": {"amount": amount}}}


def api_item(asin, type_=None, amount=None):
    return {"asin": asin, "offersV2": {"listings": [lst(type_, amount)]}} if type_ else {"asin": asin}


def offer(asin, price=1000, mrp=1200, in_stock=True):
    return {"url": f"https://www.amazon.in/dp/{asin}", "price": price, "mrp": mrp, "in_stock": in_stock}


class FakeApi:
    def __init__(self, items, stop_on_batch=None):
        self.items, self.batches, self.stop_on_batch = items, [], stop_on_batch

    def get_items(self, asins):
        self.batches.append(list(asins))
        if self.stop_on_batch == len(self.batches):
            raise ApiStop("HTTP 429")
        return {a: self.items[a] for a in asins if a in self.items}


def test_enrich_corrects_and_counts():
    offers = [offer("B000000001"), offer("B000000002"), offer("B000000003"), offer("B000000004"),
              {"url": "https://x.test/p/1", "price": 5, "mrp": 5, "in_stock": True}]
    api = FakeApi({"B000000001": api_item("B000000001", "IN_STOCK", 1499.0),
                   "B000000002": api_item("B000000002", "OUT_OF_STOCK"),
                   "B000000004": api_item("B000000004", "AVAILABLE_DATE", 900.0)})
    out, note = enrich(offers, api)
    assert (out[0]["price"], out[0]["in_stock"]) == (1499, True)
    assert (out[1]["price"], out[1]["in_stock"]) == (1000, False)
    assert out[2] == offers[2]                      # not returned: scraped values kept
    assert (out[3]["price"], out[3]["in_stock"]) == (900, True)
    assert out[4] == offers[4]
    assert offers[0]["price"] == 1000               # inputs untouched
    assert note == "api: 3 of 4 checked, 1 out of stock, 1 not returned"


def test_scarce_is_in_stock_and_not_counted_as_other():
    api = FakeApi({"B000000001": api_item("B000000001", "IN_STOCK_SCARCE", 1499.0),
                   "B000000002": api_item("B000000002", "AVAILABLE_DATE", 900.0),
                   "B000000003": api_item("B000000003", "IN_STOCK", 700.0)})
    out, note = enrich([offer("B000000001", in_stock=False), offer("B000000002"), offer("B000000003")], api)
    assert (out[0]["price"], out[0]["in_stock"]) == (1499, True)
    assert "other" not in note and "IN_STOCK_SCARCE" not in note and "AVAILABLE_DATE" not in note


def test_preorder_and_odd_type_names():
    api = FakeApi({"B000000001": api_item("B000000001", "PREORDER", 10.0),
                   "B000000002": api_item("B000000002", "weird type!", 800.0)})
    out, note = enrich([offer("B000000001"), offer("B000000002")], api)
    assert out[0]["in_stock"] is False
    assert note == "api: 2 of 2 checked, 1 preorder, 1 other (OTHER:1)"


def test_same_asin_twice_is_asked_once():
    api = FakeApi({"B000000001": api_item("B000000001", "IN_STOCK", 1499.0)})
    out, note = enrich([offer("B000000001"), offer("B000000001", price=7)], api)
    assert api.batches == [["B000000001"]]
    assert [o["price"] for o in out] == [1499, 1499]
    assert note == "api: 2 of 2 checked"


def test_batches_of_ten():
    asins = [f"B{n:09d}" for n in range(25)]
    api = FakeApi({a: api_item(a, "IN_STOCK", 1.0) for a in asins})
    enrich([offer(a) for a in asins], api)
    assert [len(b) for b in api.batches] == [10, 10, 5]


def test_stop_midway_keeps_earlier_corrections():
    asins = [f"B{n:09d}" for n in range(25)]
    api = FakeApi({a: api_item(a, "IN_STOCK", 1499.0) for a in asins}, stop_on_batch=2)
    out, note = enrich([offer(a) for a in asins], api)
    assert [o["price"] for o in out] == [1499] * 10 + [1000] * 15
    assert note == "api: stopped after 10 of 25 (HTTP 429)"


def test_item_without_offers_is_missing_not_a_crash():
    api = FakeApi({"B000000001": {"asin": "B000000001"},
                   "B000000002": {"asin": "B000000002", "errors": [{"code": "ItemNotAccessible"}]}})
    out, note = enrich([offer("B000000001"), offer("B000000002")], api)
    assert [o["in_stock"] for o in out] == [False, False]
    assert note == "api: 2 of 2 checked, 2 out of stock"


class Boom:
    def __init__(self, *a, **k): raise RuntimeError(SECRET)


def test_enrich_from_env(monkeypatch):
    offers = [offer("B000000001")]
    calls = []
    monkeypatch.setattr("pph.amazon_api._post", lambda *a: calls.append(a))
    assert enrich_from_env(offers, env={}) == (offers, "")
    assert calls == []
    monkeypatch.setattr("pph.amazon_api.AmazonApi", Boom)
    out, note = enrich_from_env(offers, env=ENV)
    assert out is offers or out == offers
    assert note == "api: unavailable (RuntimeError)"
    assert SECRET not in note and CID not in note


# ---- final review fixes ----
import math


def many(n, kinds):
    """n offers and a FakeApi whose items follow kinds(i) -> an api item."""
    asins = [f"B{i:09d}" for i in range(n)]
    return [offer(a) for a in asins], FakeApi({a: kinds(i, a) for i, a in enumerate(asins)})


def test_deadline_between_batches_stops_with_time_limit():
    asins = [f"B{n:09d}" for n in range(25)]
    api = FakeApi({a: api_item(a, "IN_STOCK", 1499.0) for a in asins})
    ticks = iter([0, 0, 100])                       # checked before batch 1, 2, 3
    out, note = enrich([offer(a) for a in asins], api, deadline=50, clock=lambda: next(ticks))
    assert len(api.batches) == 2
    assert [o["price"] for o in out] == [1499] * 20 + [1000] * 5
    assert note == "api: stopped after 20 of 25 (time limit)"


def test_stop_on_first_batch_names_the_reason():
    api = FakeApi({}, stop_on_batch=1)
    out, note = enrich([offer("B000000001")], api)
    assert out == [offer("B000000001")]
    assert note == "api: stopped after 0 of 1 (HTTP 429)"


def test_mostly_missing_answer_is_not_trusted():
    offers, api = many(30, lambda i, a: api_item(a) if i < 20 else api_item(a, "IN_STOCK", 1499.0))
    out, note = enrich(offers, api)
    assert all(o["in_stock"] for o in out)
    assert [o["price"] for o in out] == [1000] * 20 + [1499] * 10
    assert "missing ignored: 20 of 30" in note


def test_some_missing_still_goes_out_of_stock():
    offers, api = many(30, lambda i, a: api_item(a) if i < 10 else api_item(a, "IN_STOCK", 1499.0))
    out, note = enrich(offers, api)
    assert [o["in_stock"] for o in out] == [False] * 10 + [True] * 20
    assert "missing ignored" not in note and "10 out of stock" in note


def test_missing_guard_needs_twenty_items():
    offers, api = many(19, lambda i, a: api_item(a))
    out, note = enrich(offers, api)
    assert not any(o["in_stock"] for o in out)
    assert "missing ignored" not in note


def test_missing_guard_applies_to_a_stopped_run():
    asins = [f"B{n:09d}" for n in range(25)]
    api = FakeApi({a: api_item(a) for a in asins}, stop_on_batch=3)
    out, note = enrich([offer(a) for a in asins], api)
    assert all(o["in_stock"] for o in out)          # 20 returned, all missing: ignored


def test_error_code_equal_to_a_secret_never_reaches_the_stop():
    for echoed in (SECRET, CID, "shadow-21"):
        body = json.dumps({"errors": [{"code": echoed}]})
        f = Fake(TOKEN_OK, (403, body))
        with pytest.raises(ApiStop) as e:
            api_for(f).get_items(["B000000001"])
        assert str(e.value) == "HTTP 403"
        _, note = enrich([offer("B000000001")], api_for(Fake(TOKEN_OK, (403, body))))
        assert note == "api: stopped after 0 of 1 (HTTP 403)"
    f = Fake(TOKEN_OK, (403, json.dumps({"errors": [{"code": "AssociateNotEligible"}]})))
    _, note = enrich([offer("B000000001")], api_for(f))
    assert note == "api: stopped after 0 of 1 (HTTP 403 AssociateNotEligible)"


def api_for(f):
    return AmazonApi(credentials(ENV), post=f.post, sleep=f.sleep, clock=f.clock)


def test_malformed_items_cost_only_themselves():
    bad = {"B000000002": {"offersV2": {"listings": ["text"]}},
           "B000000003": {"offersV2": {"listings": {"a": 1}}},
           "B000000004": {"offersV2": {"listings": [{"availability": {"type": {"x": 1}}}]}}}
    good = api_item("B000000001", "IN_STOCK", 1499.0)
    api = FakeApi({"B000000001": good, **bad})
    offers = [offer(a) for a in ("B000000001", "B000000002", "B000000003", "B000000004")]
    out, note = enrich(offers, api)
    assert out[0]["price"] == 1499 and out[1:] == offers[1:]
    assert note == "api: 1 of 4 checked, 3 unreadable"


def test_unusable_amounts():
    for amount in (math.inf, -math.inf, math.nan, True):
        assert classify(item("IN_STOCK", amount)) == ("in_stock", None)


def test_currency():
    it = item("IN_STOCK", 1499.0)
    it["offersV2"]["listings"][0]["price"]["money"]["currency"] = "USD"
    assert classify(it) == ("in_stock", None)
    it["offersV2"]["listings"][0]["price"]["money"]["currency"] = "INR"
    assert classify(it) == ("in_stock", 1499.0)
    assert classify(item("IN_STOCK", 1499.0)) == ("in_stock", 1499.0)       # no currency given


def test_end_to_end_with_a_real_client():
    f = Fake(TOKEN_OK, (200, json.dumps({"itemsResult": {"items": [
        api_item("B000000001", "IN_STOCK", 1499.0), api_item("B000000002", "OUT_OF_STOCK"),
        api_item("B000000003", "IN_STOCK_SCARCE", 700.0)]}})))
    offers = [offer("B000000001"), offer("B000000002"), offer("B000000003", in_stock=False)]
    out, note = enrich_from_env(offers, env=ENV, post=f.post, sleep=f.sleep, clock=f.clock)
    assert [(o["price"], o["in_stock"]) for o in out] == [(1499, True), (1000, False), (700, True)]
    assert note == "api: 3 of 3 checked, 1 out of stock"
    assert "Authorization" not in f.calls[0][2] and f.calls[1][2]["Authorization"] == "Bearer T"
    assert SECRET not in note and CID not in note


def test_token_without_expires_in_is_reused():
    f = Fake((200, json.dumps({"access_token": "T"})), ok_items("B000000001"), ok_items("B000000002"))
    api = api_for(f)
    api.get_items(["B000000001"])
    api.get_items(["B000000002"])
    assert sum("/auth/o2/token" in c[0] for c in f.calls) == 1


def test_probe_summary_lists_each_item_with_its_availability():
    from tools.amazon_api_probe import summarize
    body = json.dumps({"itemsResult": {"items": [
        {"asin": "B000000001", "offersV2": {"listings": [{"isBuyBoxWinner": True, "price": {"money": {"amount": 1499.0}},
                                                          "availability": {"type": "AVAILABLE_DATE", "message": "Available: 5 Dec"}}]}},
        {"asin": "B000000002"}]}})
    assert summarize(body) == ["B000000001 AVAILABLE_DATE price=1499.0 msg=Available: 5 Dec", "B000000002 no-offer"]
    assert summarize("not json") == []


def test_available_date_makes_an_offer_the_scraper_called_out_of_stock_buyable():
    """Amazon's AVAILABLE_DATE listings have Add to Cart and a delivery date; the scraper had marked 12 of 17 sampled ones out of stock."""
    out, _ = enrich([offer("B000000001", price=5000, in_stock=False)], FakeApi({"B000000001": api_item("B000000001", "AVAILABLE_DATE", 6633.0)}))
    assert (out[0]["price"], out[0]["in_stock"]) == (6633, True)


# ---- what is confirmed by the API: price, time and photo ----
from datetime import datetime as _dt

from pph.amazon_api import enrich, image_of

AT = _dt(2026, 11, 25, 10, 30, 5)
PHOTO = "https://m.media-amazon.com/images/I/api.jpg"


def with_photo(it, url=PHOTO):
    return dict(it, images={"primary": {"large": {"url": url}}})


class Items:
    def __init__(self, *items): self.items = {i["asin"]: i for i in items}
    def get_items(self, asins): return {a: self.items[a] for a in asins if a in self.items}


def scraped(asin, **kw):
    return dict({"url": f"https://www.amazon.in/dp/{asin}", "price": 1000, "mrp": 1200, "in_stock": True,
                 "image": "https://m.media-amazon.com/images/I/scraped.jpg"}, **kw)


def test_the_api_photo_is_read_and_only_from_amazon():
    assert image_of(with_photo({"asin": "B0"})) == PHOTO
    assert image_of({"asin": "B0"}) == ""
    assert image_of(with_photo({"asin": "B0"}, "https://evil.test/x.jpg")) == ""
    assert image_of(with_photo({"asin": "B0"}, "http://m.media-amazon.com/x.jpg")) == ""
    assert "images.primary.large" in __import__("pph.amazon_api", fromlist=["x"]).RESOURCES


def test_a_confirmed_offer_carries_the_time_and_the_api_photo():
    it = dict(with_photo(item("IN_STOCK", 1499.0)), asin="B000000001")
    out, _ = enrich([scraped("B000000001")], Items(it), now=lambda: AT)
    assert (out[0]["price"], out[0]["price_at"], out[0]["image"], out[0]["api"]) == (1499, "2026-11-25T10:30:05Z", PHOTO, True)


def test_an_answer_without_a_usable_price_is_an_answer_but_confirms_no_price():
    gone = dict(item("OUT_OF_STOCK"), asin="B000000001")
    out, _ = enrich([scraped("B000000001")], Items(gone), now=lambda: AT)
    assert out[0]["api"] and "price_at" not in out[0] and out[0]["in_stock"] is False and out[0]["image"] == ""


def test_an_offer_the_api_did_not_answer_has_no_time_and_no_photo():
    out, _ = enrich([scraped("B000000002")], Items(), now=lambda: AT)
    assert "api" not in out[0] and "price_at" not in out[0] and out[0]["image"] == ""
    assert out[0]["price"] == 1000


def test_the_probe_asks_for_what_the_scraper_asks_for(monkeypatch):
    """The probe is how a new resource name is checked against the live API before release."""
    import inspect

    from pph import amazon_api
    from tools import amazon_api_probe
    assert "RESOURCES" in inspect.getsource(amazon_api_probe.main) and amazon_api_probe.RESOURCES == amazon_api.RESOURCES
