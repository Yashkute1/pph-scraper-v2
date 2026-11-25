"""The server asks Amazon again before a price is a day old. Needs a scratch database (PPH_TEST_MYSQL)."""
from datetime import timedelta

import pytest

from pph.amazon_api import ApiStop
from tests.test_amazon_api import PHOTO, item, with_photo
from tests.test_sql_db import URL, am, db, o, q, row  # noqa: F401
from tests.test_sql_db import day

pytestmark = pytest.mark.skipif(not URL, reason="PPH_TEST_MYSQL is not set")

NOW = day(10)


def asin(n): return f"B{n:09d}"


class Api:
    """Answers for every ASIN with `kind` and `price` unless it is listed in `answers` (None: not returned)."""
    def __init__(self, answers=None, stop_after=None):
        self.answers, self.batches, self.stop_after = answers or {}, [], stop_after

    def get_items(self, asins):
        if self.stop_after is not None and len(self.batches) >= self.stop_after:
            raise ApiStop("HTTP 429")
        self.batches.append(list(asins))
        out = {}
        for a in asins:
            it = self.answers.get(a, with_photo(item("IN_STOCK", 1499.0)))
            if it is not None:
                out[a] = dict(it, asin=a)
        return out


def seed(db, n, price_age=None, tried_age=None):
    """An Amazon row last confirmed `price_age` hours before NOW and last asked about `tried_age` hours before it."""
    from pph.sql_db import write_store
    write_store(db, "amazon", [am(n, 900, day(0))], day(0), blocked=False, complete=False)
    at = lambda h: None if h is None else NOW - timedelta(hours=h)
    with db.cursor() as cur:
        cur.execute("UPDATE offers SET price_at=%s, api_tried=%s, missed_runs=5, last_seen=%s WHERE url LIKE %s",
                    (at(price_age), at(tried_age), day(1), f"%{asin(n)}"))


def run(db, api, **kw):
    from tools.amazon_refresh import refresh
    return refresh(db, api, NOW, **kw)


def test_only_prices_over_half_a_day_old_are_asked_for_the_oldest_first(db):
    seed(db, 1, price_age=13)
    seed(db, 2, price_age=30)
    seed(db, 3, price_age=2)                       # still fresh
    seed(db, 4, price_age=None, tried_age=2)       # asked recently, had no price
    seed(db, 5, price_age=None, tried_age=14)
    api = Api()
    out = run(db, api)
    assert api.batches == [[asin(2), asin(1), asin(5)]]
    assert (out["asked"], out["priced"], out["note"]) == (3, 3, "")


def test_a_priced_answer_updates_price_stock_photo_and_time_only(db):
    seed(db, 1, price_age=20)
    run(db, Api())
    assert row(db, 1, "price, mrp, in_stock, image, price_at, api_tried") == (1499, 1499, 1, PHOTO, NOW, NOW)
    assert row(db, 1, "missed_runs, last_seen") == (5, day(1))


@pytest.mark.parametrize("answer", [None, item("OUT_OF_STOCK"), {"offersV2": {"listings": []}}])
def test_no_price_from_amazon_blanks_the_row_and_waits(db, answer):
    seed(db, 1, price_age=20)
    seed(db, 2, price_age=20)
    out = run(db, Api({asin(1): answer}))
    assert row(db, 1, "in_stock, price_at, api_tried") == (0, None, NOW)
    assert (out["priced"], out["blanked"]) == (1, 1)
    assert run(db, Api())["asked"] == 0


def test_ten_a_call(db):
    for n in range(23):
        seed(db, n, price_age=20)
    api = Api()
    run(db, api)
    assert [len(b) for b in api.batches] == [10, 10, 3]


def test_an_answer_that_looks_broken_blanks_nothing(db):
    for n in range(25):
        seed(db, n, price_age=20)
    out = run(db, Api({asin(n): {"offersV2": {"listings": []}} for n in range(20)}))
    assert out["blanked"] == 0 and "ignored" in out["note"]
    assert row(db, 0, "in_stock, price_at") == (1, NOW - timedelta(hours=20))
    # they go to the back of the queue for an hour, so a run never starves the rest by asking the same ones again
    from tools.amazon_refresh import refresh
    assert refresh(db, Api(), NOW + timedelta(minutes=10))["asked"] == 0
    assert refresh(db, Api(), NOW + timedelta(minutes=61))["asked"] == 20


def test_a_stop_keeps_what_was_done_and_says_why(db):
    for n in range(15):
        seed(db, n, price_age=20)
    out = run(db, Api(stop_after=1))
    assert (out["asked"], out["priced"], out["note"]) == (10, 10, "HTTP 429")


def test_the_deadline_stops_between_calls(db):
    for n in range(25):
        seed(db, n, price_age=20)
    ticks = iter([0, 40, 80, 120])
    out = run(db, Api(), deadline=50, clock=lambda: next(ticks))
    assert (out["asked"], out["note"]) == (20, "time limit")


def test_other_stores_are_never_asked(db):
    from pph.sql_db import write_store
    write_store(db, "a", [o("a", 1)], day(0), blocked=False)
    assert run(db, Api())["asked"] == 0


def test_the_server_refreshes_rolls_up_and_lets_old_prices_expire(db, tmp_path, monkeypatch):
    from pph import run as R
    from tools import hostinger_sync as H
    monkeypatch.setattr(R, "OUT", tmp_path)
    seed(db, 1, price_age=20)
    assert H.amazon_step(db, {}, NOW, api=Api(), log=lambda s: None) is True       # rolled up and refreshed
    assert q(db, "SELECT best_price FROM products")[0][0] == 1499
    assert H.amazon_step(db, {}, NOW + timedelta(hours=1), api=Api(), log=lambda s: None) is False      # nothing due
    # no credentials and no new scrape: after a day the roll-up still runs and the price goes
    assert H.amazon_step(db, {}, NOW + timedelta(hours=25), log=lambda s: None) is True
    assert q(db, "SELECT best_price, any_stock FROM products")[0] == (0, 0)


def test_a_batch_amazon_returns_nothing_for_blanks_nothing(db):
    for n in range(25):
        seed(db, n, price_age=13)
    out = run(db, Api({asin(n): None for n in range(25)}))
    assert out["blanked"] == 0 and "ignored" in out["note"]
    assert row(db, 0, "in_stock, price_at") == (1, NOW - timedelta(hours=13))
