"""Thin wrapper over Scrapling: polite delays, retries, and block detection.

Everything network-facing goes through ``Fetcher_.get``. Tests inject a
``transport`` so nothing here needs the network to be tested.
"""
import json
import random
import re
import time

BLOCK_STATUS = {403, 429, 503}
# Matched only in <title> and the first 6,000 characters: a large real page that
# merely mentions "captcha" in a footer widget is not a block page.
_BLOCK = re.compile(
    r"just a moment|cf-chl|checking your browser|attention required|robot check|are you a human|"
    r"validatecaptcha|enter the characters you see|type the characters|unusual traffic|access denied|"
    r"request blocked|pardon our interruption|px-captcha|verify you are human", re.I)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def is_blocked(status, text):
    """True when the response is a block, challenge or captcha page rather than content."""
    if status in BLOCK_STATUS:
        return True
    if status != 200:
        return False
    text = text or ""
    if not text.strip():
        return True
    m = _TITLE.search(text)
    return bool((m and _BLOCK.search(m.group(1))) or _BLOCK.search(text[:6000]))


class BlockedError(Exception):
    def __init__(self, url, status, fatal):
        super().__init__(f"blocked ({status})")
        self.url, self.status, self.fatal = url, status, fatal


class TimeBudgetExceeded(Exception):
    """The store's time allowance ran out; the run stops cleanly and keeps what it has."""


class Page:
    def __init__(self, status, text, url):
        self.status, self.text, self.url = status, text or "", url
        self._sel = None

    def css(self, selector):
        if self._sel is None:
            from scrapling.parser import Selector
            self._sel = Selector(self.text, url=self.url)
        return self._sel.css(selector)

    def json(self):
        return json.loads(self.text)


def _scrapling_transport(url, mode):
    from scrapling.fetchers import Fetcher, StealthyFetcher
    if mode == "stealth":
        r = StealthyFetcher.fetch(url, headless=True, network_idle=True, timeout=90000, disable_resources=True)
    else:
        r = Fetcher.get(url, impersonate="chrome", stealthy_headers=True, timeout=30, follow_redirects=True)
    body = r.body
    text = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body or "")
    return Page(r.status, text, url)


class Fetcher_:
    """One per store run. Counts consecutive blocked pages; the third is fatal."""
    MAX_BLOCKED = 3

    def __init__(self, mode="http", delay=(1.0, 2.0), retries=3, transport=None, sleep=time.sleep, clock=time.monotonic):
        self.mode, self.delay, self.retries = mode, delay, retries
        self._transport = transport or _scrapling_transport
        self._sleep = sleep
        self._clock = clock
        self.deadline = None             # monotonic seconds; set by the runner
        self.consecutive_blocked = 0
        self.requests = 0

    def get(self, url):
        if self.deadline is not None and self._clock() > self.deadline:
            raise TimeBudgetExceeded()
        if self.requests:
            self._sleep(random.uniform(*self.delay))
        self.requests += 1
        last = None
        for attempt in range(self.retries):
            try:
                page = self._transport(url, self.mode)
            except Exception as e:           # network error: back off and retry
                last = e
                if attempt + 1 < self.retries:
                    self._sleep(min(2 ** attempt * 2, 20))
                continue
            if is_blocked(page.status, page.text):
                self.consecutive_blocked += 1
                raise BlockedError(url, page.status, self.consecutive_blocked >= self.MAX_BLOCKED)
            self.consecutive_blocked = 0
            return page
        raise last
