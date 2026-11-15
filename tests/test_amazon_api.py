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
    assert body["resources"] == ["itemInfo.title", "offersV2.listings.price", "offersV2.listings.availability"]
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
    assert note == "api: 3 of 4 checked, 1 out of stock, 1 other (AVAILABLE_DATE:1), 1 not returned"


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
    assert note == "api: stopped after 10 of 25"


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
