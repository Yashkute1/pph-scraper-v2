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

SAMPLE = 15
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


def main(stores):
    db = sql_db.connect(os.environ["MYSQL_URL"])
    for store in stores or list(STORES):
        cfg = STORES[store]
        print(f"\n######## {store} ({cfg['adapter']}, {cfg['mode']})", flush=True)
        fetcher = Fetcher_(cfg["mode"], (1, 2))
        listing(store, cfg, fetcher)
        product_pages(store, cfg, db, fetcher)
        sys.stdout.flush()


if __name__ == "__main__":
    main(sys.argv[1:])
