"""The Amazon scrape file leaves the scraper sealed to a key only the server holds."""
import gzip
import json

import mongomock
import pytest

from pph import run as R
from pph import seal
from tests.test_hostinger_sync import NOW, offer, publish
from tests.test_run import adapter, raw

DOC = {"store": "amazon", "offers": [{"title": "Secret Amazon Title", "price": 4321}]}


@pytest.fixture
def keys(tmp_path, monkeypatch):
    """A server key pair; the public half sits where the repository keeps it."""
    seal.ensure_key(tmp_path / "state", tmp_path / "exports")
    public = tmp_path / "exports" / "amazon-key.pub"
    monkeypatch.setattr(seal, "PUBLIC", public)
    monkeypatch.setenv("PPH_AMAZON_KEY", str(tmp_path / "state" / "amazon_scrape.key"))
    monkeypatch.setattr(R, "OUT", tmp_path / "out")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    return public


def private(tmp_path):
    return (tmp_path / "state" / "amazon_scrape.key").read_text()


def test_round_trip_and_nothing_readable(tmp_path, keys):
    env = seal.seal(DOC, keys.read_text())
    assert set(env) == {"sealed"}
    text = json.dumps(env)
    assert "Secret" not in text and "4321" not in text
    assert seal.unseal(env, private(tmp_path)) == DOC


def test_another_key_cannot_open_it(tmp_path, keys):
    env = seal.seal(DOC, keys.read_text())
    seal.ensure_key(tmp_path / "other", tmp_path / "other_exports")
    with pytest.raises(Exception):
        seal.unseal(env, (tmp_path / "other" / "amazon_scrape.key").read_text())


def test_the_key_is_made_once_and_kept_private(tmp_path, keys):
    first = private(tmp_path), keys.read_text()
    keys.unlink()
    seal.ensure_key(tmp_path / "state", tmp_path / "exports")
    assert (private(tmp_path), keys.read_text()) == first
    assert (tmp_path / "state" / "amazon_scrape.key").stat().st_mode & 0o777 == 0o600
    assert private(tmp_path).strip() != keys.read_text().strip()


def scrape(store, monkeypatch):
    monkeypatch.setitem(R.STORES, store, {"adapter": "fake", "mode": "http", "base": "https://s.test", "delay": (0, 0)})
    monkeypatch.delenv("AMAZON_CREATORS_CREDENTIAL_ID", raising=False)
    R.ADAPTERS["fake"] = adapter([raw(1), raw(2)])
    try:
        return R.scrape(store, now=NOW, fetcher=object(), save=True)
    finally:
        R.ADAPTERS.pop("fake")


def test_the_amazon_file_is_saved_sealed_and_replays(tmp_path, keys, monkeypatch):
    code, run = scrape("amazon", monkeypatch)
    assert (code, run["status"]) == (0, "saved")
    path = tmp_path / "out" / "amazon-offers.json"
    text = path.read_text()
    assert set(json.loads(text)) == {"sealed"} and "Corsair" not in text
    db = mongomock.MongoClient().pph_site
    code, run = R.replay_cmd(path, db=db, now=NOW)
    assert (code, run["written"]) == (0, 2)


def test_without_the_public_key_nothing_is_saved_and_the_run_says_why(tmp_path, keys, monkeypatch):
    keys.unlink()
    code, run = scrape("amazon", monkeypatch)
    assert (code, run["status"]) == (0, "withheld") and "key" in run["note"]
    assert not (tmp_path / "out" / "amazon-offers.json").exists()


def test_other_stores_are_saved_as_before(tmp_path, keys, monkeypatch):
    keys.unlink()
    code, run = scrape("s", monkeypatch)
    assert run["status"] == "saved"
    assert len(json.loads((tmp_path / "out" / "s-offers.json").read_text())["offers"]) == 2


@pytest.mark.parametrize("key", ["missing", "wrong"])
def test_an_unopenable_amazon_file_does_not_stop_the_other_stores(tmp_path, keys, monkeypatch, key):
    from tools.hostinger_sync import sync
    repo = tmp_path / "repo"
    repo.mkdir()
    import subprocess
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    env = seal.seal(dict(DOC, started="2026-10-28T00:20:00", blocked=False, note="", complete=True), keys.read_text())
    (repo / "amazon-offers.json.gz").write_bytes(gzip.compress(json.dumps(env).encode()))
    publish(repo, {"a": [offer(1)]})
    if key == "missing":
        monkeypatch.delenv("PPH_AMAZON_KEY")
    else:
        seal.ensure_key(tmp_path / "other", tmp_path / "other_exports")
        monkeypatch.setenv("PPH_AMAZON_KEY", str(tmp_path / "other" / "amazon_scrape.key"))
    state = tmp_path / "sync"
    state.mkdir()
    db = mongomock.MongoClient().pph_site
    code, out = sync(repo, state, db=db, now=NOW, log=lambda s: None)
    status = {r["store"]: r["status"] for r in out["written"]}
    assert code == 1 and status == {"a": "ok", "amazon": "error"}
    assert db.offers.count_documents({}) == 1 and db.products_v2.count_documents({}) == 1
    assert "Secret" not in json.dumps(out)
