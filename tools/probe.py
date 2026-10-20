"""Probe store URLs from a runner: status, platform hints, page title, and card-like elements. Read-only.

    python -m tools.probe URL [URL ...]"""
import re
from collections import Counter
import sys

from pph.fetch import Fetcher_

HINTS = {"shopify": r"cdn\.shopify|Shopify\.theme", "woocommerce": r"woocommerce|wp-content", "magento": r"Magento|mage/",
         "opencart": r"route=product|catalog/view/theme", "journal": r"journal3|journal-", "next.js": r"__NEXT_DATA__",
         "json-ld product": r'"@type"\s*:\s*"Product"'}


def main(urls):
    f = Fetcher_("http", (1, 2))
    for url in urls:
        try:
            p = f.get(url)
        except Exception as e:  # noqa: BLE001 - a report
            print(f"\n## {url}\n  {type(e).__name__}: {e}")
            continue
        t = p.text
        title = re.search(r"<title[^>]*>(.*?)</title>", t, re.S | re.I)
        print(f"\n## {url}\n  status={p.status} bytes={len(t)} title={title.group(1).strip()[:100] if title else '-'}")
        print("  hints:", [k for k, rx in HINTS.items() if re.search(rx, t)])
        if "TEXT" in __import__("os").environ:
            body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S | re.I)
            heads = re.findall(r"<(h[1-4])[^>]*>(.*?)</\1>", body, re.S | re.I)
            print("  headings:", [re.sub(r"<[^>]+>|\s+", " ", h[1]).strip()[:80] for h in heads][:60])
            meta = re.findall(r'<meta[^>]+(?:name|property)="([^"]+)"[^>]+content="([^"]*)"', t)
            print("  meta:", meta[:20])
            txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))
            print("  text:", txt[:9000])
            print("  scripts:", re.findall(r'<script[^>]+src="([^"]+)"', t)[:15])
        if t.lstrip().startswith(("{", "[", "<?xml")):
            print("  json:", t[:600].replace("\n", " "))
            continue
        classes = re.findall(r'class="([^"]*(?:product|item|card)[^"]*)"', t)
        print("  common classes:", Counter(classes).most_common(12))
        prods = [m for m in re.finditer(r'href="(/product/[^"]+|https?://[^"]+/product/[^"]+)"', t)]
        print(f"  product links: {len(prods)} e.g. {[m.group(1) for m in prods[:3]]}")
        for m in prods[:2]:
            print("  --- html around a product link ---\n" + t[max(0, m.start() - 1500):m.start() + 2500])
        print("  paging:", sorted(set(re.findall(r'href="([^"]*[?&]page=\d+[^"]*)"', t)))[:8])
        print("  stock words:", Counter(w.lower() for w in re.findall(r"out of stock|in stock|sold out|notify me|add to cart|unavailable", t, re.I)))
        links = sorted({m for m in re.findall(r'href="(https?://[^"]*computech[^"]*|/[^"]+)"', t) if any(k in m for k in ("product", "/p/", "category", "collections"))})
        print("  sample links:", links[:15])


if __name__ == "__main__":
    main(sys.argv[1:])
