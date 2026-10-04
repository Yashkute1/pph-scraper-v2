"""Adapters turn one store into a stream of raw offers: iter_offers(cfg, fetcher)."""
from . import html_listing, shopify_feed, woo_store_api

ADAPTERS = {"shopify_feed": shopify_feed, "woo_store_api": woo_store_api, "html_listing": html_listing}
