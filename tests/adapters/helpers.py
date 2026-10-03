from pph.fetch import Page, BlockedError


class FakeFetcher:
    """Serves canned bodies keyed by URL; anything else is an empty JSON list / 404 page."""
    def __init__(self, routes, default=None):
        self.routes, self.default, self.calls = routes, default, []

    def get(self, url):
        self.calls.append(url)
        body = self.routes.get(url, self.default)
        if isinstance(body, Exception): raise body
        if body is None: return Page(404, "", url)
        return Page(200, body, url)
