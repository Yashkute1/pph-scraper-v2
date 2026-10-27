import gzip
import json
import subprocess
from datetime import datetime

import mongomock
import pytest

from tools.hostinger_sync import local_url, sync

NOW = datetime(2026, 10, 28, 1, 0)


def test_local_url_points_the_site_address_at_this_server():
    env = "PPH_DATA=mysql\nMYSQL_URL='mysql://u1:p%40ss@srv1825.hstgr.io:3306/u1_pph'\nOTHER=1\n"
    assert local_url(env) == "mysql://u1:p%40ss@127.0.0.1:3306/u1_pph"
    assert local_url("export MYSQL_URL=mysql://u:p@localhost/db") == "mysql://u:p@127.0.0.1:3306/db"
    assert local_url("MONGO_URI=mongodb://x") is None
    assert local_url("MYSQL_URL=") is None


def offer(n):
    return {"store": "a", "url": f"https://a.test/p/{n}", "title": f"MSI Part {n} PN{n}X 1TB SSD", "price": 1000 + n, "mrp": None,
            "in_stock": True, "image": "", "brand": "MSI", "category": "SSD", "model_key": f"pn{n}x", "group_id": f"ssd-msi-pn{n}x",
            "specs": {}}


def publish(repo, files):
    """Make a scrapes commit like the workflow's publish job: one gzipped file per store."""
    for store, offers in files.items():
        doc = {"store": store, "started": "2026-10-28T00:20:00", "blocked": False, "note": "", "complete": True, "offers": offers}
        (repo / f"{store}-offers.json.gz").write_bytes(gzip.compress(json.dumps(doc).encode()))
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "scrapes"], check=True)
    subprocess.run(["git", "-C", str(repo), "update-ref", "refs/remotes/origin/scrapes", "HEAD"], check=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    return r


def test_a_new_scrapes_commit_is_written_once_then_rolled_up(repo, tmp_path, monkeypatch):
    from pph import run as R
    monkeypatch.setattr(R, "OUT", tmp_path / "out")
    state = tmp_path / "state"
    state.mkdir()
    db = mongomock.MongoClient().pph_site
    assert sync(repo, state, db=db, now=NOW, log=lambda s: None)[1]["note"] == "nothing new"     # no branch yet

    publish(repo, {"a": [offer(n) for n in range(3)]})
    code, out = sync(repo, state, db=db, now=NOW, log=lambda s: None)
    assert code == 0 and out["written"] == [{"store": "a", "status": "ok", "written": 3}]
    assert db.offers.count_documents({}) == 3 and db.products_v2.count_documents({}) == 3
    assert sync(repo, state, db=db, now=NOW, log=lambda s: None)[1]["note"] == "nothing new"     # written once


def test_a_store_the_database_could_not_take_is_tried_again(repo, tmp_path, monkeypatch):
    from pph import run as R
    monkeypatch.setattr(R, "OUT", tmp_path / "out")
    state = tmp_path / "state"
    state.mkdir()
    publish(repo, {"a": [offer(1)]})
    db = mongomock.MongoClient().pph_site
    real = R.replay_cmd

    def broken(path, **kw):
        raise RuntimeError("database down")
    monkeypatch.setattr(R, "replay_cmd", broken)
    monkeypatch.setattr(R, "rollup_cmd", lambda **kw: (0, {}))
    monkeypatch.setattr(R, "health_cmd", lambda *a, **kw: (0, {"stale": []}))
    assert sync(repo, state, db=db, now=NOW, log=lambda s: None)[0] == 1
    monkeypatch.setattr(R, "replay_cmd", real)
    code, out = sync(repo, state, db=db, now=NOW, log=lambda s: None)                        # same commit, next run
    assert code == 0 and out["try"] == 2 and db.offers.count_documents({}) == 1
