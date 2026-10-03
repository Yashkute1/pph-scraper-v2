"""Fetch one listing page per HTML store and save a trimmed copy as a test fixture.
Run from GitHub Actions (capture.yml); the stores are not reachable from every network."""
import pathlib, re, sys, time
from pph.fetch import Fetcher_

PAGES = {
    "primeabgb": ("http", "https://www.primeabgb.com/buy-online-price-india/graphic-cards-gpu/"),
    "vedantcomputers": ("http", "https://www.vedantcomputers.com/pc-components/gpu"),
    "mdcomputers": ("http", "https://mdcomputers.in/catalog/graphics-card"),
    "theitdepot": ("http", "https://www.theitdepot.com/Graphic_Card"),
    "flipkart": ("http", "https://www.flipkart.com/search?q=graphics+card"),
    "amazon": ("stealth", "https://www.amazon.in/s?k=graphics+card&i=computers"),
}
STRIP = [r"<script(?![^>]*ld\+json)[^>]*>.*?</script>", r"<style[^>]*>.*?</style>", r"<svg[^>]*>.*?</svg>",
         r"<!--.*?-->", r"<noscript[^>]*>.*?</noscript>", r'\sstyle="[^"]*"', r"data:image/[^\"' )]+"]


def trim(html):
    for rx in STRIP:
        html = re.sub(rx, "", html, flags=re.S | re.I)
    return re.sub(r"[ \t]{2,}", " ", re.sub(r"\n\s*\n+", "\n", html))


out = pathlib.Path("tests/fixtures/html"); out.mkdir(parents=True, exist_ok=True)
want = sys.argv[1:] or list(PAGES)
for name in want:
    mode, url = PAGES[name]
    try:
        page = Fetcher_(mode, (1, 2)).get(url)
        html = trim(page.text)
        (out / f"{name}.html").write_text(html, encoding="utf-8")
        print(f"{name}: {page.status} raw={len(page.text)} trimmed={len(html)}")
    except Exception as e:
        print(f"{name}: FAILED {type(e).__name__}")
    time.sleep(1)
