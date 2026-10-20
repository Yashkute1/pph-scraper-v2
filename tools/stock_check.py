"""Check stock flags against the stores' own pages.

    MYSQL_URL=... python -m tools.stock_check [store ...]

For each store: opens a sample of offers the database marks in stock and reports what the product page says
(JSON-LD availability, out-of-stock wording), then reads the first listing page and shows every card whose text
says out of stock next to the flag the scraper's config gives it. Public product data only; read-only."""
import html
import os
import random
import re
import sys

from pph import sql_db
from pph.adapters.html_listing import _OOS, _card, _from_detail
from pph.fetch import BlockedError, Fetcher_
from pph.stores import STORES

SAMPLE = int(os.environ.get("SAMPLE", "60"))
_TAGS = re.compile(r"<script.*?</script>|<style.*?</style>|<[^>]+>", re.S | re.I)
_BUY = re.compile(r"add to cart|buy now|add to basket", re.I)
_META = re.compile(r'<meta[^>]+(?:product:availability|og:availability)[^>]+content="([^"]+)"', re.I)


def _text(page_html):
    return re.sub(r"\s+", " ", html.unescape(_TAGS.sub(" ", page_html)))


def _snips(text, n=2):
    return [text[max(0, m.start() - 50):m.end() + 30] for m in list(_OOS.finditer(text))[:n]]


def product_pages(store, cfg, db, fetcher):
    with db.cursor() as cur:
        cur.execute("SELECT url, title, price FROM offers WHERE store=%s AND in_stock=1", (store,))
        rows = cur.fetchall()
    random.seed(7)
    picked = random.sample(rows, min(SAMPLE, len(rows)))
    tally = {"ld_out": 0, "ld_in": 0, "text_oos": 0, "blocked": 0}
    for url, title, price in picked:
        try:
            page = fetcher.get(url)
        except BlockedError:
            tally["blocked"] += 1
            print(f"  BLOCKED {url}")
            continue
        except Exception as e:  # noqa: BLE001 - a report, not the scraper
            print(f"  ERROR {type(e).__name__} {url}")
            continue
        _, _, ld = _from_detail(page)
        meta = _META.search(page.text)
        text = _text(page.text)
        sn = _snips(text)
        tally["ld_out"] += ld is False
        tally["ld_in"] += ld is True
        tally["text_oos"] += bool(sn)
        if ld is True and not (store == "amazon"):
            continue
        avail = re.search(r'id="availability".{0,400}?</div>', page.text, re.S)
        if avail:
            print(f"      availability: {_text(avail.group(0))[:120]}")
        print(f"  [{'ld:' + ('IN' if ld else 'OUT') if ld is not None else 'ld:-'} meta:{meta.group(1) if meta else '-'} "
              f"buy:{len(_BUY.findall(text))} status:{page.status}] {price} {title[:70]}\n    {url}")
        for s in sn:
            print(f"      oos-text: …{s}…")
    print(f"  == {store} product pages: {tally} of {len(picked)}")


def listing(store, cfg, fetcher):
    if cfg["adapter"] != "html_listing":
        return
    url = cfg["start_urls"][0]
    try:
        page = fetcher.get(url)
    except Exception as e:  # noqa: BLE001
        print(f"  listing {url}: {type(e).__name__}")
        return
    cards = page.css(cfg["card"])
    flagged = missed = 0
    for el in cards:
        o = _card(el, cfg, page.url)
        if not o:
            continue
        t = el.get_all_text(separator=" ", strip=True)
        says = _OOS.search(t)
        if says or not o["in_stock"]:
            flagged += 1
            missed += bool(says) and o["in_stock"]
            print(f"  card in_stock={o['in_stock']} text-says={says.group(0) if says else '-'} price={o['price']} {o['title'][:70]}")
    print(f"  == {store} listing {url}: {len(cards)} cards, {flagged} say out of stock, {missed} of those kept in stock")


def woo_api(store, cfg, fetcher):
    """PC Studio blocks product pages; its Store API says how each product counts as in stock."""
    if cfg["adapter"] != "woo_store_api":
        return
    from collections import Counter
    from pph.adapters.common import json_page
    seen = Counter()
    for n in range(1, 6):
        items = json_page(fetcher, cfg["base"].rstrip("/") + f"/wp-json/wc/store/v1/products?per_page=100&page={n}", first=(n == 1)) or []
        for p in items:
            av = p.get("stock_availability") or {}
            key = (p.get("is_in_stock"), p.get("is_purchasable"), av.get("class"), (av.get("text") or "")[:30])
            if seen[key] < 2:
                print(f"  api in_stock={key[0]} purchasable={key[1]} class={key[2]!r} text={key[3]!r} low={p.get('low_stock_remaining')} {p.get('name', '')[:60]}")
            seen[key] += 1
    for k, v in seen.most_common():
        print(f"  == {store} api {v:4} x in_stock={k[0]} purchasable={k[1]} class={k[2]!r} text={k[3]!r}")


def inspect(store, urls, search=None, searches_all=(), targets=frozenset()):
    """Print every stock signal for given product pages, and the full text of matching search cards."""
    cfg = STORES[store]
    fetcher = Fetcher_(cfg["mode"], (1, 2))
    for url in urls:
        page = fetcher.get(url)
        _, _, ld = _from_detail(page)
        text = _text(page.text)
        print(f"\n## {url}\n  status={page.status} ld={ld} buy={len(_BUY.findall(text))}")
        for m in re.finditer(r"sold out|currently unavailable|coming soon|notify me|out of stock|add to cart|buy now|pre-?order|"
                             r"temporarily unavailable|unavailable", text, re.I):
            print(f"    …{text[max(0, m.start() - 60):m.end() + 40]}…")
        for m in re.finditer(r'"(availability|availabilityStatus|stockStatus|inStock|isAvailable|buyable|sellable)"\s*:\s*("?[^,}]{0,40})', page.text):
            print(f"    json {m.group(1)}={m.group(2)}")
    for extra in searches_all:
        page = fetcher.get(extra)
        cards = page.css(cfg["card"])
        ids = [el.attrib.get("data-id") for el in cards]
        print(f"\n## search {extra}\n  {len(cards)} cards; targets present: {sorted(set(ids) & targets)}")
        for el in cards[:40]:
            print(f"    {el.attrib.get('data-id')} {el.get_all_text(separator=' | ', strip=True)[:110]}")
    if search:
        page = fetcher.get(search)
        pids = {re.search(r"pid=(\w+)", u).group(1) for u in urls if "pid=" in u}
        for el in page.css(cfg["card"]):
            t = el.get_all_text(separator=" | ", strip=True)
            if el.attrib.get("data-id") in pids or "PS5" in t:
                o = _card(el, cfg, page.url)
                print(f"\n  card id={el.attrib.get('data-id')} flag={o and o['in_stock']}: {t[:400]}")


def main(stores):
    db = sql_db.connect(os.environ["MYSQL_URL"])
    for store in stores or list(STORES):
        cfg = STORES[store]
        print(f"\n######## {store} ({cfg['adapter']}, {cfg['mode']})", flush=True)
        fetcher = Fetcher_(cfg["mode"], (1, 2))
        listing(store, cfg, fetcher)
        woo_api(store, cfg, fetcher)
        product_pages(store, cfg, db, fetcher)
        sys.stdout.flush()


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[2].startswith("http"):
        args = sys.argv[2:]
        searches = [a for a in args if "/search?" in a]
        targets = {re.search(r"pid=(\w+)", a).group(1) for a in args if "pid=" in a and "/search?" not in a}
        inspect(sys.argv[1], [a for a in args if a not in searches and "/p/" in a and not os.environ.get("SKIP_PAGES")],
                None, searches, targets)
    else:
        main(sys.argv[1:])
