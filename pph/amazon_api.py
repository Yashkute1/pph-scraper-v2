"""What Amazon's Creators API says about a product, and what that means for a scraped offer. Pure, no I/O."""
import json
import re
import time
import urllib.error
import urllib.request

_ASIN = re.compile(r"/dp/([A-Z0-9]{10})")


def asin_of(url):
    """The 10-character product id in an Amazon product link, or None."""
    m = _ASIN.search(url or "")
    return m.group(1) if m else None


def classify(item):
    """(kind, price) for one API item. Kind is in_stock, out_of_stock, preorder, other, or missing (no offer known).
    The price is the buy-box listing's (else the first listing's), None when absent or not above 0."""
    listings = ((item or {}).get("offersV2") or {}).get("listings") or []
    if not listings:
        return "missing", None
    listing = next((l for l in listings if l.get("isBuyBoxWinner")), listings[0])
    amount = ((listing.get("price") or {}).get("money") or {}).get("amount")
    price = round(amount) if isinstance(amount, (int, float)) and amount > 0 else None
    kind = {"IN_STOCK": "in_stock", "OUT_OF_STOCK": "out_of_stock", "PREORDER": "preorder"}.get(
        (listing.get("availability") or {}).get("type"), "other")
    return kind, price


def apply(offer, kind, price):
    """A corrected copy of the offer. Out of stock, preorder and missing mean not in stock; in stock means in stock;
    other leaves stock as it was. A usable price replaces the scraped one, and the mrp never ends up below it."""
    out = dict(offer)
    if kind in ("out_of_stock", "preorder", "missing"):
        out["in_stock"] = False
    elif kind == "in_stock":
        out["in_stock"] = True
    if price is not None and price > 0 and kind in ("in_stock", "other"):
        out["price"] = round(price)
        out["mrp"] = max(out.get("mrp") or 0, out["price"])
    return out


# ---- the client: credentials, token, pacing, stop rules ----
TOKEN_HOSTS = {"3.1": "api.amazon.com", "3.2": "api.amazon.co.uk", "3.3": "api.amazon.co.jp"}
GET_ITEMS = "https://creatorsapi.amazon/catalog/v1/getItems"
MARKETPLACE = "www.amazon.in"
RESOURCES = ["itemInfo.title", "offersV2.listings.price", "offersV2.listings.availability"]
MAX_ASINS = 10
MIN_GAP = 1.0
RETRY_WAITS = (5, 20)
_CODE = re.compile(r"[A-Za-z0-9_.-]{1,40}")


class ApiStop(Exception):
    """The API cannot be used for the rest of this run. The message carries only an HTTP status and Amazon's own
    short error code word, never a response body and never a credential."""


def credentials(env):
    """The four settings as a dict (id, secret, version, tag), or None when any is missing or blank."""
    names = ("AMAZON_CREATORS_CREDENTIAL_ID", "AMAZON_CREATORS_CREDENTIAL_SECRET",
             "AMAZON_CREATORS_CREDENTIAL_VERSION", "AMAZON_PARTNER_TAG")
    vals = [(env.get(n) or "").strip() for n in names]
    if not all(vals):
        return None
    cid, secret, version, tag = vals
    return {"id": cid, "secret": secret, "version": version.lstrip("vV"), "tag": tag}


def _post(url, body, headers):
    """(status, text) of a JSON POST, also for HTTP error statuses. Network trouble becomes ApiStop."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        raise ApiStop(f"network {type(e).__name__}") from None


def _code_word(text):
    """Amazon's own error code word from an answer body, only when it is a short plain token."""
    try:
        data = json.loads(text)
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    errors = data.get("errors")
    candidates = [data.get("code"), data.get("error"), data.get("__type")]
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        candidates.insert(0, errors[0].get("code"))
    for c in candidates:
        if isinstance(c, str) and _CODE.fullmatch(c):
            return c
    return ""


def _stop(status, text):
    word = _code_word(text)
    return ApiStop(f"HTTP {status} {word}" if word else f"HTTP {status}")


class AmazonApi:
    """Creators API getItems for www.amazon.in. At most 10 ASINs a call, at least a second between calls, the token
    reused until two minutes before it expires. Anything unexpected raises ApiStop."""

    def __init__(self, creds, post=_post, sleep=time.sleep, clock=time.monotonic):
        self._creds, self._post, self._sleep, self._clock = creds, post, sleep, clock
        self._token = None
        self._token_until = 0.0
        self._last_start = None

    def _call(self, url, body, headers):
        """One network call, started at least MIN_GAP after the previous one."""
        if self._last_start is not None:
            wait = MIN_GAP - (self._clock() - self._last_start)
            if wait > 0:
                self._sleep(wait)
        self._last_start = self._clock()
        return self._post(url, body, headers)

    def _bearer(self):
        if self._token and self._clock() < self._token_until:
            return self._token
        host = TOKEN_HOSTS.get(self._creds["version"])
        if not host:
            raise ApiStop("unknown credential version")
        status, text = self._call(f"https://{host}/auth/o2/token", {
            "grant_type": "client_credentials", "client_id": self._creds["id"],
            "client_secret": self._creds["secret"], "scope": "creatorsapi::default"}, {})
        if "associatenoteligible" in text.lower() or status != 200:
            raise _stop(status, text)
        try:
            data = json.loads(text)
            token, expires = data["access_token"], float(data.get("expires_in", 0))
            if not isinstance(token, str) or not token:
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise ApiStop("token answer unusable") from None
        self._token, self._token_until = token, self._clock() + expires - 120
        return token

    def get_items(self, asins):
        """ASIN -> raw item for the ASINs the API returned. An ASIN it did not return is absent."""
        if len(asins) > MAX_ASINS:
            raise ValueError(f"at most {MAX_ASINS} ASINs a call")
        body = {"itemIds": list(asins), "itemIdType": "ASIN", "partnerTag": self._creds["tag"],
                "marketplace": MARKETPLACE, "resources": RESOURCES}
        for attempt in range(len(RETRY_WAITS) + 1):
            headers = {"Authorization": f"Bearer {self._bearer()}", "x-marketplace": MARKETPLACE}
            status, text = self._call(GET_ITEMS, body, headers)
            if "associatenoteligible" in text.lower():
                raise _stop(status, text)
            if status == 429 and attempt < len(RETRY_WAITS):
                self._sleep(RETRY_WAITS[attempt])
                continue
            if status != 200:
                raise _stop(status, text)
            break
        try:
            items = json.loads(text)["itemsResult"].get("items") or []
            return {i["asin"]: i for i in items if isinstance(i, dict) and isinstance(i.get("asin"), str)}
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ApiStop("answer unusable") from None
