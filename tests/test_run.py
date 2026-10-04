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
    assert (code, run["status"], run["written"]) == (1, "blocked", 2)


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
