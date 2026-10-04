import pytest
from pph.fetch import Page, is_blocked, BlockedError, Fetcher_


@pytest.mark.parametrize("status,text,want", [
    (403, "", True), (429, "", True), (503, "", True),
    (200, "<title>Just a moment...</title>", True),
    (200, "<title>Attention Required! | Cloudflare</title>", True),
    (200, "<html><body>Enter the characters you see below. Type the characters you see in this image</body></html>", True),
    (200, "<form action='/errors/validateCaptcha'>", True),
    (200, "<title>Are you a human?</title>", True),
    (200, "<title>Robot Check</title>", True),
    (200, "", True),
    (200, "<html><head><title>Products</title></head><body>" + "x" * 7000 + " recaptcha widget in footer</body></html>", False),
    (200, "<html><title>Graphics Card</title><div class='product'>RTX 5060</div></html>", False),
    (404, "<html>not found</html>", False)])
def test_is_blocked(status, text, want): assert is_blocked(status, text) is want


def seq(*pages):
    it = iter(pages); calls = []
    def transport(url, mode):
        calls.append(url); p = next(it)
        if isinstance(p, Exception): raise p
        return p
    transport.calls = calls
    return transport


OK = Page(200, "<title>ok</title><p>fine</p>", "u")
BAD = Page(403, "", "u")


def test_three_blocked_in_a_row_is_fatal():
    f = Fetcher_("http", (0, 0), transport=lambda u, m: BAD, sleep=lambda s: None)
    for n in (1, 2):
        with pytest.raises(BlockedError) as e: f.get("https://a.test/%d" % n)
        assert e.value.fatal is False and f.consecutive_blocked == n
    with pytest.raises(BlockedError) as e: f.get("https://a.test/3")
    assert e.value.fatal is True


def test_blocked_page_is_not_retried():
    t = seq(BAD, OK)
    f = Fetcher_("http", (0, 0), transport=t, sleep=lambda s: None)
    with pytest.raises(BlockedError): f.get("https://a.test/1")
    assert len(t.calls) == 1


def test_success_resets_blocked_counter():
    f = Fetcher_("http", (0, 0), transport=seq(BAD, OK, BAD), sleep=lambda s: None)
    with pytest.raises(BlockedError): f.get("u1")
    assert f.get("u2").status == 200 and f.consecutive_blocked == 0


def test_retries_on_exception_then_succeeds():
    t = seq(TimeoutError("x"), ConnectionError("y"), OK)
    f = Fetcher_("http", (0, 0), retries=3, transport=t, sleep=lambda s: None)
    assert f.get("u").status == 200 and len(t.calls) == 3


def test_gives_up_after_retries():
    t = seq(TimeoutError("1"), TimeoutError("2"), TimeoutError("3"))
    f = Fetcher_("http", (0, 0), retries=3, transport=t, sleep=lambda s: None)
    with pytest.raises(TimeoutError): f.get("u")
    assert len(t.calls) == 3


def test_delay_between_requests_is_within_range():
    slept = []
    f = Fetcher_("http", (1.0, 2.0), transport=lambda u, m: OK, sleep=slept.append)
    f.get("u1"); f.get("u2"); f.get("u3")
    assert len(slept) == 2 and all(1.0 <= s <= 2.0 for s in slept)   # no wait before the first request


def test_page_json_and_css():
    p = Page(200, '{"products": [1, 2]}', "u")
    assert p.json() == {"products": [1, 2]}
    h = Page(200, "<html><body><a class='x' href='/p/1'>One</a></body></html>", "https://s.test/c")
    assert h.css("a.x::attr(href)").get() == "/p/1" and h.css("a.x::text").get() == "One"


def test_deadline_stops_further_requests():
    from pph.fetch import TimeBudgetExceeded
    now = [0.0]
    f = Fetcher_("http", (0, 0), transport=lambda u, m: OK, sleep=lambda s: None, clock=lambda: now[0])
    f.deadline = 100.0
    assert f.get("u1").status == 200
    now[0] = 101.0
    with pytest.raises(TimeBudgetExceeded): f.get("u2")
