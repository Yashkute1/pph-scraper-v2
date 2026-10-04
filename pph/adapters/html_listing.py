"""Generic listing-page scraper driven entirely by per-store config (pph/stores.py).

Reads every product card on a category/search page, follows pagination, and opens
a product page only for a card that is missing its price or image.
"""
import json
import re
from urllib.parse import urljoin

from ..fetch import BlockedError
from ..normalize import canonical_url, parse_price
from .common import EmptyListingError

_OOS = re.compile(r"out of stock|sold out|currently unavailable|notify me|coming soon", re.I)
_RUPEE = re.compile(r"₹\s?[\d,]+(?:\.\d{1,2})?")
_LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)


def _first(el, selectors):
    for s in selectors or ():
        if s.endswith("::alltext"):
            hit = el.css(s[:-9])
            v = hit[0].get_all_text(separator=" ", strip=True) if hit else None
        else:
            v = el.css(s).get()
        if v and str(v).strip():
            return str(v).strip()
    return None


def _rupee(el, index):
    found = _RUPEE.findall(el.get_all_text(separator=" ", strip=True))
    return found[index] if len(found) > index else None


def _field(el, spec):
    """spec is a list of CSS selectors, or ("rupee", n) = the nth rupee amount in the card's text."""
    if isinstance(spec, tuple) and spec and spec[0] == "rupee":
        return _rupee(el, spec[1])
    return _first(el, spec)


def _image(el, selector, base):
    for img in el.css(selector) if selector else ():
        a = img.attrib
        srcset = a.get("srcset") or a.get("data-srcset") or ""
        biggest = ""
        if srcset:
            parts = [p.strip().split(" ") for p in srcset.split(",") if p.strip()]
            parts.sort(key=lambda p: int(re.sub(r"\D", "", p[1]) or 0) if len(p) > 1 else 0)
            biggest = parts[-1][0] if parts else ""
        for cand in (a.get("data-src"), a.get("data-lazy-src"), a.get("data-original"), biggest, a.get("src")):
            if cand and not cand.startswith("data:"):
                return urljoin(base, cand)
    return ""


def _from_detail(page):
    """(price, image, in_stock) from a product page's JSON-LD, falling back to og:/product: meta."""
    price = image = None
    stock = None
    for block in _LD.findall(page.text):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        nodes = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for n in nodes:
            if not isinstance(n, dict) or "Product" not in str(n.get("@type")):
                continue
            img = n.get("image")
            image = image or (img[0] if isinstance(img, list) and img else img.get("url") if isinstance(img, dict) else img)
            off = n.get("offers")
            off = off[0] if isinstance(off, list) and off else off
            if isinstance(off, dict):
                spec = off.get("priceSpecification")
                spec = spec[0] if isinstance(spec, list) and spec else spec
                price = price or off.get("price") or off.get("lowPrice") or (spec.get("price") if isinstance(spec, dict) else None)
                if off.get("availability"):
                    stock = "instock" in str(off["availability"]).lower().replace("_", "")
    price = price or page.css('meta[property="product:price:amount"]::attr(content)').get()
    image = image or page.css('meta[property="og:image"]::attr(content)').get()
    return (str(price) if price else None), (str(image) if image else None), stock


def _card(el, cfg, page_url):
    title = _field(el, cfg["title"])
    if cfg.get("link_attr"):
        attr, tpl = cfg["link_attr"]
        key = el.attrib.get(attr)
        link = tpl.format(key) if key else None
    else:
        link = _first(el, cfg["link"])
    if not title or not link:
        return None
    if cfg.get("skip") and el.css(cfg["skip"]):
        return None
    price, mrp = _field(el, cfg["price"]), _field(el, cfg.get("mrp"))
    if mrp and price and parse_price(mrp) < parse_price(price):
        mrp = None                                  # some stores print a stale "old price" below the live one
    oos = cfg.get("oos")
    in_stock = not (oos and _OOS.search(" ".join(el.css(oos).getall())))
    return {"title": re.sub(r"\s+", " ", title), "price": price, "mrp": mrp, "url": urljoin(page_url, link),
            "image": _image(el, cfg.get("image"), page_url), "in_stock": in_stock, "sku": ""}


def _next_url(page, cfg, start, n):
    if cfg.get("next_page"):
        href = _first(page, cfg["next_page"])
        return urljoin(page.url, href) if href else None
    if cfg.get("page_param"):
        return f"{start}{'&' if '?' in start else '?'}{cfg['page_param']}={n + 1}"
    return None


def iter_offers(cfg, fetcher):
    seen, total, detail_budget = set(), 0, cfg.get("max_detail", 30)
    for i, start in enumerate(cfg["start_urls"]):
        url, n = start, 1
        while url and n <= cfg.get("max_pages", 20):
            try:
                page = fetcher.get(url)
            except BlockedError as e:
                if e.fatal:
                    raise
                break                                   # this category only; the run carries on
            fresh = 0
            for el in page.css(cfg["card"]):
                o = _card(el, cfg, page.url)
                if not o:
                    continue
                key = canonical_url(o["url"])
                if key in seen:
                    continue
                seen.add(key)
                if (not o["price"] or not o["image"]) and detail_budget > 0:
                    detail_budget -= 1
                    try:
                        price, image, stock = _from_detail(fetcher.get(o["url"]))
                        o["price"], o["image"] = o["price"] or price, o["image"] or image or ""
                        if stock is not None:
                            o["in_stock"] = stock
                    except BlockedError as e:
                        if e.fatal:
                            raise
                if not o["price"]:
                    continue
                fresh += 1
                total += 1
                yield o
            if fresh == 0:
                if i == 0 and n == 1:
                    raise EmptyListingError(url)     # layout change or silent block: fail loudly
                break
            url, n = _next_url(page, cfg, start, n), n + 1
    if total == 0:
        raise EmptyListingError(cfg["start_urls"][0])
