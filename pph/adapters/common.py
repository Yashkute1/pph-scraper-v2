"""Shared by all adapters."""
import json


class EmptyListingError(Exception):
    """A page that should list products listed none: layout change or silent block."""
    def __init__(self, url):
        super().__init__("no products found")
        self.url = url


def json_page(fetcher, url, first):
    """Parsed JSON, or None when a later page is missing/invalid (= end of feed).
    The first page must be valid: a store whose feed is gone is a failure, not an empty store."""
    page = fetcher.get(url)
    if page.status == 200:
        try:
            return json.loads(page.text)
        except ValueError:
            pass
    if first:
        raise EmptyListingError(url)
    return None
