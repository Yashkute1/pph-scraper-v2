"""Check whether the Amazon Creators API answers with this account's credentials. Prints only status codes and
Amazon's own error or result text, never the credentials.

  python tools/amazon_api_probe.py [ASIN ...]

Reads AMAZON_CREATORS_CREDENTIAL_ID, AMAZON_CREATORS_CREDENTIAL_SECRET, AMAZON_CREATORS_CREDENTIAL_VERSION and
AMAZON_PARTNER_TAG from the environment."""
import collections
import json
import os
import sys
import urllib.error
import urllib.request

# The credential version picks the Login with Amazon token host: 3.1 North America, 3.2 Europe, Middle East and
# India, 3.3 Far East.
TOKEN_HOSTS = {"3.1": "api.amazon.com", "3.2": "api.amazon.co.uk", "3.3": "api.amazon.co.jp"}
GET_ITEMS = "https://creatorsapi.amazon/catalog/v1/getItems"
MARKETPLACE = "www.amazon.in"
# The same list the scraper asks for (pph/amazon_api.py), so a new name can be tried against the live API first.
RESOURCES = ["itemInfo.title", "offersV2.listings.price", "offersV2.listings.availability", "images.primary.large"]


def post(url, body, headers):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def summarize(text):
    """What came back, as counts only: these logs are public, and Amazon's data may not be republished."""
    try:
        items = json.loads(text)["itemsResult"].get("items") or []
    except (ValueError, KeyError, AttributeError, TypeError):
        return []
    kinds, photos = collections.Counter(), 0
    for item in items:
        listings = ((item.get("offersV2") or {}).get("listings") or [])
        l = next((x for x in listings if x.get("isBuyBoxWinner")), listings[0]) if listings else None
        kinds["no-offer" if l is None else str((l.get("availability") or {}).get("type"))[:30]] += 1
        photos += bool((((item.get("images") or {}).get("primary") or {}).get("large") or {}).get("url"))
    return [f"items: {len(items)}, with a photo address: {photos}"] + [f"{k}: {n}" for k, n in sorted(kinds.items())]


def main(asins):
    cid, secret = os.environ.get("AMAZON_CREATORS_CREDENTIAL_ID"), os.environ.get("AMAZON_CREATORS_CREDENTIAL_SECRET")
    version, tag = os.environ.get("AMAZON_CREATORS_CREDENTIAL_VERSION", "").strip(), os.environ.get("AMAZON_PARTNER_TAG", "").strip()
    missing = [n for n, v in (("CREDENTIAL_ID", cid), ("CREDENTIAL_SECRET", secret), ("CREDENTIAL_VERSION", version), ("PARTNER_TAG", tag)) if not v]
    if missing:
        print("missing:", ", ".join("AMAZON_CREATORS_" + m if m != "PARTNER_TAG" else "AMAZON_PARTNER_TAG" for m in missing))
        return 2
    version = version.lstrip("vV")
    host = TOKEN_HOSTS.get(version)
    if not host:
        print(f"unknown credential version {version!r}; expected one of {', '.join(TOKEN_HOSTS)}")
        return 2
    status, text = post(f"https://{host}/auth/o2/token", {"grant_type": "client_credentials", "client_id": cid,
                                                         "client_secret": secret, "scope": "creatorsapi::default"}, {})
    try:
        tok = json.loads(text)
    except ValueError:
        tok = {}
    if status != 200 or "access_token" not in tok:
        print(f"token: HTTP {status} {tok.get('error', '')} {tok.get('error_description', text[:300])}")
        return 1
    print(f"token: ok (version {version}, {host}, expires in {tok.get('expires_in')} s)")
    body = {"itemIds": asins, "itemIdType": "ASIN", "partnerTag": tag, "marketplace": MARKETPLACE,
            "resources": RESOURCES}
    status, text = post(GET_ITEMS, body, {"Authorization": f"Bearer {tok['access_token']}", "x-marketplace": MARKETPLACE})
    print(f"getItems: HTTP {status}")
    for line in summarize(text):
        print(line)
    if status != 200:
        print(text[:300])                      # Amazon's error text, which holds no product data
    return 0 if status == 200 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["B0CJJKF2Q2"]))
