"""Per-store configuration. Fetch methods were proven from a GitHub runner (docs/probe/)."""
from urllib.parse import quote_plus

# One search per site category, used for the two marketplaces.
SEARCH_TERMS = [
    "graphics card", "desktop processor", "motherboard", "ddr4 desktop ram", "ddr5 desktop ram", "nvme ssd", "sata ssd",
    "internal hard disk", "smps power supply", "pc cabinet", "cpu cooler", "cabinet fan", "thermal paste",
    "gaming monitor", "mechanical keyboard", "gaming mouse", "mouse pad", "gaming headset", "webcam",
    "usb microphone", "pc speakers", "ups for pc", "wifi adapter for pc", "gaming chair", "pen drive",
    "gaming laptop", "gaming pc desktop", "ps5 console", "xbox series console", "nintendo switch console", "ps5 games",
]

_JOURNAL = {  # OpenCart "Journal" theme, shared by Vedant and TheITDepot
    "card": ".main-products .product-thumb", "title": [".name a::text"], "link": [".name a::attr(href)"],
    "price": [".price-new::text", ".price-normal::text"], "mrp": [".price-old::text"], "image": ".image img",
    "oos": ".product-label ::text", "page_param": "page",
}


def _cats(base, paths):
    return [base + p for p in paths]


STORES = {
    "elitehubs": {"adapter": "shopify_feed", "mode": "http", "base": "https://elitehubs.com", "delay": (1, 2)},
    "vishalperipherals": {"adapter": "shopify_feed", "mode": "http", "base": "https://www.vishalperipherals.com", "delay": (1, 2)},
    "pcstudio": {"adapter": "woo_store_api", "mode": "http", "base": "https://www.pcstudio.in", "delay": (1, 2)},
    "primeabgb": {
        "adapter": "html_listing", "mode": "http", "base": "https://www.primeabgb.com", "delay": (1, 2), "max_pages": 40,
        "start_urls": _cats("https://www.primeabgb.com/buy-online-price-india/", [
            "graphic-cards-gpu/", "cpu-processor/", "motherboards/", "ram-memory/", "ssd/", "internal-hard-drive/",
            "power-supplies-smps/", "cpu-cooler/", "led-monitors/", "gaming-headset/"]),
        "card": "div.product-wrapper", "title": ["h3.product-title a::text"], "link": ["h3.product-title a::attr(href)"],
        "price": ["span.price ins .amount::alltext", "span.price .amount::alltext"], "mrp": ["span.price del .amount::alltext"],
        "image": "img.front-image, .product-image img", "oos": ".out-of-stock ::text, .stock ::text",
        "next_page": ["a.next.page-numbers::attr(href)"],
    },
    "vedantcomputers": dict(_JOURNAL, **{
        "adapter": "html_listing", "mode": "http", "base": "https://www.vedantcomputers.com", "delay": (1, 2), "max_pages": 40,
        "start_urls": _cats("https://www.vedantcomputers.com/pc-components/", [
            "gpu", "processor", "motherboard", "memory", "storage", "smps", "cpu-cooler", "cabinet"]),
    }),
    "theitdepot": dict(_JOURNAL, **{
        "adapter": "html_listing", "mode": "http", "base": "https://www.theitdepot.com", "delay": (1, 2), "max_pages": 40,
        "start_urls": _cats("https://www.theitdepot.com/", [
            "Graphic_Card", "Processor", "Motherboard", "Memory", "Solid_State_Drive_(SSD)", "Power_Supply%20(PSU)",
            "Cabinet%20(Case)", "Monitor"]),
    }),
    "mdcomputers": {
        "adapter": "html_listing", "mode": "http", "base": "https://mdcomputers.in", "delay": (1, 2), "max_pages": 40,
        "start_urls": _cats("https://mdcomputers.in/catalog/", [
            "graphics-card", "processor", "motherboard", "ram", "storage", "smps", "cabinet", "cpu-cooler", "monitor",
            "laptop", "keyboard", "mouse", "headset"]),
        "card": "div.product-grid-item", "title": ["h3.product-entities-title a::text"],
        "link": ["h3.product-entities-title a::attr(href)"],
        "price": ["span.price .ins .amount::alltext", "span.price .amount::alltext"], "mrp": ["span.price .del .amount::alltext"],
        "image": "a.product-image-link img", "oos": ".out-of-stock ::text, .product-label ::text", "page_param": "page",
    },
    "flipkart": {
        "adapter": "html_listing", "mode": "http", "base": "https://www.flipkart.com", "delay": (1, 2), "max_pages": 10,
        "start_urls": ["https://www.flipkart.com/search?q=" + quote_plus(t) for t in SEARCH_TERMS],
        # class names on Flipkart are randomised per release, so only structure is used
        "card": "div[data-id]", "title": ["a[title]::attr(title)", "img::attr(alt)"], "link": ['a[href*="/p/"]::attr(href)'],
        "price": ("rupee", 0), "mrp": ("rupee", 1), "image": "img[alt]", "page_param": "page", "max_detail": 0,
    },
    "amazon": {
        "adapter": "html_listing", "mode": "stealth", "base": "https://www.amazon.in", "delay": (3, 5), "max_pages": 12,
        "start_urls": ["https://www.amazon.in/s?k=" + quote_plus(t) for t in SEARCH_TERMS],
        "card": 'div[data-component-type="s-search-result"][data-asin]', "title": ["h2::alltext"],
        "link_attr": ("data-asin", "https://www.amazon.in/dp/{}"),
        "price": ["span.a-price:not(.a-text-price) span.a-offscreen::text"],
        "mrp": ["span.a-price.a-text-price span.a-offscreen::text"], "image": "img.s-image",
        "skip": ".puis-sponsored-label-text", "page_param": "page", "max_detail": 0,
    },
}
