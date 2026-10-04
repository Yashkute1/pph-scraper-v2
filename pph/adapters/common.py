"""Shared by all adapters."""
import json

PAGE_TRIES = 3


class EmptyListingError(Exception):
    """A page that should list products listed none: layout change or silent block."""
    def __init__(self, url):
        super().__init__("no products found")
        self.url = url


class IncompleteError(Exception):
    """The store stopped answering part-way. What was fetched is valid, but the run is not a full picture."""
    def __init__(self, url):
        super().__init__("store stopped responding part-way")
        self.url = url


def json_page(fetcher, url, first):
    """Parsed JSON for one feed page, retried a few times (big feeds hiccup).
    A dead first page means the feed is gone (EmptyListingError); a dead later page means the
    run is incomplete (IncompleteError) - never silently treated as the end of the catalogue."""
    for _ in range(PAGE_TRIES):
        page = fetcher.get(url)
        if page.status == 200:
            try:
                return json.loads(page.text)
            except ValueError:
                pass
    raise EmptyListingError(url) if first else IncompleteError(url)
