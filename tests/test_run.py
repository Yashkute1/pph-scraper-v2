import json
from datetime import datetime

import mongomock
import pytest

from pph import run as R
from pph.adapters.common import EmptyListingError
from pph.fetch import BlockedError

NOW = datetime(2026, 10, 4, 3, 0)
CFG = {"adapter": "fake", "mode": "http", "base": "https://s.test", "delay": (0, 0)}


def raw(n): return {"title": f"Corsair Vengeance {n * 8}GB DDR5 RAM Kit", "price": 4000 + n, "url": f"https://s.test/p/{n}", "image": "i"}


def adapter(items, error=None):
    class A:
        @staticmethod
        def iter_offers(cfg, fetcher):
            yield from items
            if error: raise error
    return A


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setitem(R.STORES, "s", dict(CFG))
    monkeypatch.setattr(R, "OUT", tmp_path)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    return tmp_path


def go(items, db, error=None, monkeypatch=None, **kw):
    R.ADAPTERS["fake"] = adapter(items, error)
    try:
        return R.scrape("s", db=db, now=NOW, fetcher=object(), **kw)
    finally:
        R.ADAPTERS.pop("fake")


def test_ok_run_writes_and_exits_zero(env):
    db = mongomock.MongoClient().pph_site
    code, run = go([raw(1), raw(2), {"title": "Sponsored", "price": 1, "url": "u"}], db)
    assert (code, run["status"], run["fetched"], run["written"]) == (0, "ok", 2, 2)
    assert db.offers.count_documents({}) == 2
    assert json.loads((env / "s.json").read_text())["status"] == "ok"


def test_dry_run_needs_no_database(env):
    code, run = go([raw(1)], None, dry_run=True)
    assert (code, run["status"], run["fetched"], run["written"]) == (0, "dry-run", 1, 0)


def test_fatal_block_is_reported_and_saves_what_was_fetched(env):
    db = mongomock.MongoClient().pph_site
    code, run = go([raw(1), raw(2)], db, error=BlockedError("u", 403, fatal=True))
    assert (code, run["status"], run["written"]) == (3, "blocked", 2)     # 3 = refused, retried elsewhere, not a failure


def test_store_that_does_not_answer_is_retried_not_failed(env):
    db = mongomock.MongoClient().pph_site
    code, run = go([], db, error=TimeoutError("Timeout"))
    assert (code, run["status"], run["written"]) == (3, "blocked", 0)
    assert "did not answer" in run["note"]


def test_a_program_error_is_a_failure_not_a_store_that_did_not_answer(env):
    class Error(Exception):          # what the browser library raises when its browser is missing
        pass
    db = mongomock.MongoClient().pph_site
    code, run = go([], db, error=Error("Executable doesn't exist"))
    assert (code, run["status"]) == (1, "failed")


def test_empty_listing_is_failed(env):
    db = mongomock.MongoClient().pph_site
    code, run = go([], db, error=EmptyListingError("u"))
    assert (code, run["status"], run["note"]) == (1, "failed", "no products found")


def test_crash_mid_run_is_partial_and_never_leaks_details(env):
    db = mongomock.MongoClient().pph_site
    go([raw(n) for n in range(10)], db)
    code, run = go([raw(n) for n in range(9)], db, error=RuntimeError("mongodb+srv://u:pw@host/x boom"))
    assert (code, run["status"], run["note"]) == (1, "partial", "RuntimeError")
    assert db.offers.find_one({"url": "https://s.test/p/9"})["missed_runs"] == 0
    assert "pw@host" not in (env / "s.json").read_text()


def test_time_budget_stops_the_run_as_incomplete(env):
    db = mongomock.MongoClient().pph_site
    go([raw(n) for n in range(10)], db)
    ticks = iter(range(0, 10000, 100))
    code, run = go([raw(n) for n in range(10)], db, time_budget=250, clock=lambda: next(ticks))
    assert run["status"] == "partial" and run["note"] == "time budget reached" and 0 < run["fetched"] < 10


def test_unknown_store_exits_2(env, capsys):
    assert R.main(["scrape", "nope"]) == 2


def test_missing_mongo_uri_exits_2_without_traceback(env, monkeypatch, capsys):
    monkeypatch.delenv("MONGO_URI", raising=False)
    assert R.main(["rollup"]) == 2
    assert "MONGO_URI" in capsys.readouterr().err


def test_safe_error_hides_connection_string():
    assert R.safe_error(Exception("mongodb+srv://user:pw@cluster0.example.mongodb.net/x failed")) == "Exception"


def test_summary_row_written_when_env_set(env, monkeypatch):
    f = env / "summary.md"; monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(f))
    go([raw(1)], None, dry_run=True)
    assert "| s | dry-run | 1 |" in f.read_text()


def test_rollup_command(env):
    db = mongomock.MongoClient().pph_site
    go([raw(1), raw(2)], db)
    code, out = R.rollup_cmd(db=db, now=NOW)
    assert code == 0 and out["products"] == 2 and json.loads((env / "rollup.json").read_text())["products"] == 2


def test_budget_raised_inside_the_adapter_is_a_clean_partial(env):
    from pph.fetch import TimeBudgetExceeded
    db = mongomock.MongoClient().pph_site
    go([raw(n) for n in range(10)], db)
    code, run = go([raw(n) for n in range(9)], db, error=TimeBudgetExceeded())
    assert (code, run["status"], run["note"], run["written"]) == (1, "partial", "time budget reached", 9)


def test_scrape_sets_the_fetcher_deadline(env):
    class F: deadline = None
    f = F(); R.ADAPTERS["fake"] = adapter([raw(1)])
    try: R.scrape("s", dry_run=True, now=NOW, fetcher=f, time_budget=600, clock=lambda: 50.0)
    finally: R.ADAPTERS.pop("fake")
    assert f.deadline == 650.0


def test_incomplete_feed_is_partial_and_keeps_fetched(env):
    from pph.adapters.common import IncompleteError
    db = mongomock.MongoClient().pph_site
    go([raw(n) for n in range(10)], db)
    code, run = go([raw(n) for n in range(9)], db, error=IncompleteError("u"))
    assert (code, run["status"], run["note"], run["written"]) == (1, "partial", "store stopped responding part-way", 9)


def test_health_flags_only_stores_without_a_recent_good_run(env):
    from datetime import timedelta
    db = mongomock.MongoClient().pph_site
    db.scrape_runs.insert_many([
        {"store": "a", "status": "ok", "started": NOW - timedelta(hours=3)},
        {"store": "b", "status": "ok", "started": NOW - timedelta(hours=40)},
        {"store": "b", "status": "blocked", "started": NOW - timedelta(hours=1)},      # a refusal is not a good run
        {"store": "c", "status": "ok", "started": NOW - timedelta(hours=20)},
        {"store": "c", "status": "blocked", "started": NOW - timedelta(hours=2)},      # blocked once, still fresh enough
    ])
    code, out = R.health_cmd(26, db=db, now=NOW, stores=["a", "b", "c", "never"])
    assert (code, out["stale"]) == (1, ["b", "never"])
    assert R.health_cmd(26, db=db, now=NOW, stores=["a", "c"]) [0] == 0


class OperationalError(Exception):
    """Stands in for pymysql's: the scraper tells errors apart by name and number."""


def unreachable_then(db, failures):
    calls = {"n": 0}

    def connect():
        calls["n"] += 1
        if calls["n"] <= failures:
            raise OperationalError(2003, "Can't connect to MySQL server on 'host' (Network is unreachable)")
        return db
    return connect, calls


def test_an_unreachable_database_is_waited_out_not_a_lost_scrape(env, monkeypatch):
    db = mongomock.MongoClient().pph_site
    connect, calls = unreachable_then(db, 2)
    monkeypatch.setattr(R, "_connect", connect)
    waits = []
    R.ADAPTERS["fake"] = adapter([raw(1), raw(2)])
    try:
        code, run = R.scrape("s", now=NOW, fetcher=object(), sleep=waits.append)
    finally:
        R.ADAPTERS.pop("fake")
    assert (code, run["status"], run["written"], calls["n"]) == (0, "ok", 2, 3)
    assert waits == [20, 40]


def test_a_scrape_the_database_never_accepts_is_saved_and_replayed(env, monkeypatch):
    connect, _ = unreachable_then(None, 99)
    monkeypatch.setattr(R, "_connect", connect)
    waits = []
    R.ADAPTERS["fake"] = adapter([raw(1), raw(2)])
    try:
        code, run = R.scrape("s", now=NOW, fetcher=object(), sleep=waits.append)
    finally:
        R.ADAPTERS.pop("fake")
    assert (code, run["status"]) == (1, "failed")
    assert run["note"] == "database: OperationalError 2003; scrape saved for replay"
    assert waits == list(R.WAITS)
    saved = env / "s-offers.json"
    assert len(json.loads(saved.read_text())["offers"]) == 2

    db = mongomock.MongoClient().pph_site
    code, run = R.replay_cmd(saved, db=db, now=NOW)
    assert (code, run["status"], run["written"]) == (0, "ok", 2)
    assert db.offers.count_documents({}) == 2
    assert not saved.exists()


def test_save_mode_never_connects_and_the_server_writes_it(env, monkeypatch):
    def connect():
        raise AssertionError("a saving scrape must not connect to the database")
    monkeypatch.setattr(R, "_connect", connect)
    R.ADAPTERS["fake"] = adapter([raw(1), raw(2)])
    try:
        code, run = R.scrape("s", now=NOW, fetcher=object(), save=True)
    finally:
        R.ADAPTERS.pop("fake")
    assert (code, run["status"], run["fetched"]) == (0, "saved", 2)
    saved = env / "s-offers.json"
    db = mongomock.MongoClient().pph_site
    code, run = R.replay_cmd(saved, db=db, now=NOW)
    assert (code, run["status"], run["written"]) == (0, "ok", 2)


def test_save_mode_still_reports_a_refusing_store(env, monkeypatch):
    monkeypatch.setattr(R, "_connect", lambda: (_ for _ in ()).throw(AssertionError("no database")))
    R.ADAPTERS["fake"] = adapter([], error=R.BlockedError("https://s.test/", 403, True))
    try:
        code, run = R.scrape("s", now=NOW, fetcher=object(), save=True)
    finally:
        R.ADAPTERS.pop("fake")
    assert (code, run["status"]) == (R.BLOCKED_EXIT, "blocked")


def test_other_database_errors_are_not_retried(env, monkeypatch):
    def connect():
        raise OperationalError(1064, "syntax")
    monkeypatch.setattr(R, "_connect", connect)
    waits = []
    R.ADAPTERS["fake"] = adapter([raw(1)])
    try:
        code, run = R.scrape("s", now=NOW, fetcher=object(), sleep=waits.append)
    finally:
        R.ADAPTERS.pop("fake")
    assert (code, run["note"], waits) == (1, "database: OperationalError 1064", [])
    assert not (env / "s-offers.json").exists()
