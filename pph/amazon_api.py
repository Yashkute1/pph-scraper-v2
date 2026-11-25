"""What Amazon's Creators API says about a product, and what that means for a scraped offer.

Only a price the API gave is ever shown (with the time it gave it, `price_at`), and only a photo address it gave is kept."""
import collections
import http.client
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlsplit

_ASIN = re.compile(r"/dp/([A-Z0-9]{10})")


def asin_of(url):
    """The 10-character product id in an Amazon product link, or None."""
    m = _ASIN.search(url or "")
    return m.group(1) if m else None


def _listing(item):
    """The buy-box listing of an item (else its first listing), or None."""
    listings = ((item or {}).get("offersV2") or {}).get("listings") or []
    return next((l for l in listings if l.get("isBuyBoxWinner")), listings[0]) if listings else None


def classify(item):
    """(kind, price) for one API item. Kind is in_stock (IN_STOCK, IN_STOCK_SCARCE or AVAILABLE_DATE), out_of_stock, preorder, other,
    or missing (no offer known).
    The price is the buy-box listing's (else the first listing's), None when absent, not a finite number above 0, or
    not in rupees."""
    listing = _listing(item)
    if listing is None:
        return "missing", None
    money = (listing.get("price") or {}).get("money") or {}
    amount, currency = money.get("amount"), money.get("currency")
    usable = (isinstance(amount, (int, float)) and not isinstance(amount, bool) and math.isfinite(amount)
              and amount > 0 and currency in (None, "INR"))
    price = round(amount) if usable else None
    # AVAILABLE_DATE: Amazon sells it now with a stated delivery date (Add to Cart and Buy Now both work on amazon.in)
    kind = {"IN_STOCK": "in_stock", "IN_STOCK_SCARCE": "in_stock", "AVAILABLE_DATE": "in_stock", "OUT_OF_STOCK": "out_of_stock",
            "PREORDER": "preorder"}.get((listing.get("availability") or {}).get("type"), "other")
    return kind, price


IMAGE_HOSTS = ("media-amazon.com", "ssl-images-amazon.com", "images-amazon.com")


def image_of(item):
    """The large product photo's address as the API gives it, when it is https on an Amazon image host; else ""."""
    url = ((((item or {}).get("images") or {}).get("primary") or {}).get("large") or {}).get("url")
    if not isinstance(url, str) or len(url) > 2000:
        return ""
    try:
        u = urlsplit(url)
    except ValueError:
        return ""
    host = u.hostname or ""
    return url if u.scheme == "https" and any(host == h or host.endswith("." + h) for h in IMAGE_HOSTS) else ""


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def unconfirmed(offer):
    """The offer as scraped, without its photo: only a photo address the API gave is ever stored."""
    return dict(offer, image="") if offer.get("image") else offer


def apply(offer, kind, price, image="", now=None):
    """A corrected copy of the offer. Out of stock, preorder and missing mean not in stock; in stock means in stock;
    other leaves stock as it was. A usable price replaces the scraped one, and the mrp never ends up below it."""
    out = dict(offer, api=True, image=image)       # the API answered for this offer; only its photo is kept
    out.pop("price_at", None)
    if kind in ("out_of_stock", "preorder", "missing"):
        out["in_stock"] = False
    elif kind == "in_stock":
        out["in_stock"] = True
    if price is not None and price > 0 and kind in ("in_stock", "other"):
        out["price"] = round(price)
        out["mrp"] = max(out.get("mrp") or 0, out["price"])
        out["price_at"] = (now or utcnow()).strftime("%Y-%m-%dT%H:%M:%SZ")     # when the API confirmed this price
    return out


# ---- the client: credentials, token, pacing, stop rules ----
TOKEN_HOSTS = {"3.1": "api.amazon.com", "3.2": "api.amazon.co.uk", "3.3": "api.amazon.co.jp"}
GET_ITEMS = "https://creatorsapi.amazon/catalog/v1/getItems"
MARKETPLACE = "www.amazon.in"
PHOTO = "images.primary.large"
RESOURCES = ["itemInfo.title", "offersV2.listings.price", "offersV2.listings.availability", PHOTO]
MAX_ASINS = 10
MIN_GAP = 1.0
DEFAULT_EXPIRES = 3600     # seconds a token is kept when the answer does not say
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
        try:
            return e.code, e.read().decode("utf-8", "replace")
        except (OSError, http.client.HTTPException) as e2:
            raise ApiStop(f"network {type(e2).__name__}") from None
    except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
        raise ApiStop(f"network {type(e).__name__}") from None


def _code_word(text, secrets=()):
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
        if isinstance(c, str) and _CODE.fullmatch(c) and not any(x in c for x in secrets):
            return c
    return ""


def _stop(status, text, secrets=()):
    word = _code_word(text, secrets)
    return ApiStop(f"HTTP {status} {word}" if word else f"HTTP {status}")


class AmazonApi:
    """Creators API getItems for www.amazon.in. At most 10 ASINs a call, at least a second between calls, the token
    reused until two minutes before it expires. Anything unexpected raises ApiStop."""

    def __init__(self, creds, post=_post, sleep=time.sleep, clock=time.monotonic):
        self._creds, self._post, self._sleep, self._clock = creds, post, sleep, clock
        self._secrets = tuple(v for v in (creds.get("id"), creds.get("secret"), creds.get("tag")) if v)
        self._token = None
        self._token_until = 0.0
        self._last_start = None
        self._resources = list(RESOURCES)

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
            raise _stop(status, text, self._secrets)
        try:
            data = json.loads(text)
            token, expires = data["access_token"], data.get("expires_in")
            if not isinstance(token, str) or not token:
                raise ValueError
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ApiStop("token answer unusable") from None
        if isinstance(expires, bool) or not isinstance(expires, (int, float)) or not math.isfinite(expires):
            expires = DEFAULT_EXPIRES
        self._token, self._token_until = token, self._clock() + expires - 120
        return token

    def _ask(self, asins, resources):
        """(status, text) of one getItems request, waiting out "too many requests"."""
        body = {"itemIds": list(asins), "itemIdType": "ASIN", "partnerTag": self._creds["tag"],
                "marketplace": MARKETPLACE, "resources": resources}
        for attempt in range(len(RETRY_WAITS) + 1):
            headers = {"Authorization": f"Bearer {self._bearer()}", "x-marketplace": MARKETPLACE}
            status, text = self._call(GET_ITEMS, body, headers)
            if "associatenoteligible" in text.lower():
                raise _stop(status, text, self._secrets)
            if status != 429 or attempt == len(RETRY_WAITS):
                return status, text
            self._sleep(RETRY_WAITS[attempt])

    def get_items(self, asins):
        """ASIN -> raw item for the ASINs the API returned. An ASIN it did not return is absent."""
        if len(asins) > MAX_ASINS:
            raise ValueError(f"at most {MAX_ASINS} ASINs a call")
        status, text = self._ask(asins, self._resources)
        if status == 400 and PHOTO in self._resources:
            # Prices matter more than photos: if the request is refused, try it once without the photo.
            fewer = [r for r in self._resources if r != PHOTO]
            status, text = self._ask(asins, fewer)
            if status == 200:
                self._resources = fewer
        if status != 200:
            raise _stop(status, text, self._secrets)
        try:
            items = json.loads(text)["itemsResult"].get("items") or []
            return {i["asin"]: i for i in items if isinstance(i, dict) and isinstance(i.get("asin"), str)}
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ApiStop("answer unusable") from None


# ---- enrich a scrape ----
MISSING_MIN_ITEMS = 20
_TYPE_NAME = re.compile(r"[A-Z_]{1,30}")


def _type_name(item):
    """The buy-box listing's availability type when it is a short plain name, else OTHER."""
    name = ((_listing(item) or {}).get("availability") or {}).get("type")
    return name if isinstance(name, str) and _TYPE_NAME.fullmatch(name) else "OTHER"


def enrich(offers, api, deadline=None, clock=time.monotonic, now=utcnow):
    """(corrected offers, note). Each distinct ASIN is asked once, ten at a time. Offers without an ASIN, and ASINs
    the API did not return, keep the scraped values. If the API stops, or the deadline passes between batches, what
    was corrected stays and the rest is as scraped. When most returned items have no offer data the API is taken to
    be broken and "missing" does not mean out of stock in this run. The note holds only counts and the stop reason."""
    asins = list(dict.fromkeys(a for a in map(asin_of, (o.get("url") for o in offers)) if a))
    total = sum(1 for o in offers if asin_of(o.get("url")))
    items, asked, reason, times = {}, set(), "", {}
    try:
        for i in range(0, len(asins), MAX_ASINS):
            if deadline is not None and clock() >= deadline:
                reason = "time limit"
                break
            batch = asins[i:i + MAX_ASINS]
            got = api.get_items(batch)
            times.update(dict.fromkeys(got, now()))
            items.update(got)
            asked.update(batch)
    except ApiStop as e:
        reason = str(e)
    kinds = {}
    for a, it in items.items():
        try:
            kinds[a] = classify(it)
        except Exception:
            kinds[a] = None                 # one malformed item must not cost the other corrections
    n_missing = sum(1 for k in kinds.values() if k and k[0] == "missing")
    ignore_missing = len(items) >= MISSING_MIN_ITEMS and n_missing * 2 > len(items)
    out, counts, others = [], collections.Counter(), collections.Counter()
    checked = not_returned = unreadable = in_asked = 0
    for o in offers:
        a = asin_of(o.get("url"))
        if a in asked:
            in_asked += 1
        if a not in items:
            out.append(unconfirmed(o))
            not_returned += a in asked
            continue
        if kinds[a] is None:
            out.append(unconfirmed(o))
            unreadable += 1
            continue
        kind, price = kinds[a]
        checked += 1
        if kind == "missing" and ignore_missing:
            out.append(unconfirmed(o))
            continue
        out.append(apply(o, kind, price, image_of(items[a]), times[a]))
        counts[kind] += 1
        if kind == "other":
            others[_type_name(items[a])] += 1
    if in_asked < total:
        return out, f"api: stopped after {in_asked} of {total}" + (f" ({reason})" if reason else "")
    parts = [f"{checked} of {total} checked"]
    for n, label in ((counts["out_of_stock"] + counts["missing"], "out of stock"), (counts["preorder"], "preorder")):
        if n:
            parts.append(f"{n} {label}")
    if others:
        parts.append(f"{sum(others.values())} other (" + ", ".join(f"{k}:{v}" for k, v in sorted(others.items())) + ")")
    if not_returned:
        parts.append(f"{not_returned} not returned")
    if unreadable:
        parts.append(f"{unreadable} unreadable")
    if ignore_missing:
        parts.append(f"missing ignored: {n_missing} of {len(items)}")
    return out, "api: " + ", ".join(parts)


def enrich_from_env(offers, env=os.environ, deadline=None, **kw):
    """enrich with credentials from the environment. No credentials: nothing happens. Any other trouble: the offers
    stay as scraped and the note names only the exception class."""
    try:
        creds = credentials(env)
        if creds is None:
            return offers, ""
        return enrich(offers, AmazonApi(creds, **kw), deadline=deadline, clock=kw.get("clock", time.monotonic))
    except Exception as e:
        return offers, f"api: unavailable ({type(e).__name__})"
