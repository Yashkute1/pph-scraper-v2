"""Command line: `python -m pph.run scrape <store> [--dry-run] [--max-pages N] [--time-budget MIN]`, `rollup`,
`health [--hours N]` and `replay <file>` (write a scrape saved when the database could not be reached).

Exit codes for `scrape`: 0 done, 1 failed or incomplete, 3 the store refused this machine (old prices are kept; the
workflow tries again from another machine and does not count it as a failure)."""
import argparse
import json
import os
import pathlib
import sys
import time
from datetime import datetime, timezone

from . import DB_NAME
from .adapters import ADAPTERS
from .adapters.common import EmptyListingError, IncompleteError
from .fetch import BlockedError, Fetcher_, TimeBudgetExceeded
from .normalize import normalize
from .stores import STORES
from . import store_db

OUT = pathlib.Path("out")
BLOCKED_EXIT = 3


def safe_error(e):
    """Exception type, and a database error number when there is one: messages can carry connection strings or URLs
    with credentials, error numbers cannot."""
    code = e.args[0] if getattr(e, "args", None) and isinstance(e.args[0], int) else None
    return type(e).__name__ + (f" {code}" if code is not None else "")


# Exception names that mean the store could not be reached, from curl_cffi, the browser and Python itself. Anything
# else (a broken browser install, a bug) must fail the run so it is noticed, not pass as "the store did not answer".
NETWORK_ERRORS = {"Timeout", "TimeoutError", "ConnectTimeout", "ReadTimeout", "ConnectionError", "ConnectionResetError",
                  "ConnectionRefusedError", "RequestsError", "CurlError", "SSLError", "ProxyError", "DNSError", "gaierror"}


def _network_error(e):
    return any(c.__name__ in NETWORK_ERRORS for c in type(e).__mro__)


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


# MySQL errors that mean "could not get a connection right now", not a problem with the data: can't connect (2003),
# lost during the handshake (2013), too many connections for the server (1040) or for the user (1203). Hostinger
# refuses connections for a few minutes at a time, so these are waited out instead of throwing away a scrape.
CONNECT_ERRORS = {2003, 2013, 1040, 1203}
WAITS = (20, 40, 60)                     # seconds between attempts; a longer refusal is written from another machine


def _unreachable(e):
    code = e.args[0] if getattr(e, "args", None) and isinstance(e.args[0], int) else None
    return type(e).__name__ == "OperationalError" and code in CONNECT_ERRORS


def _write(store, offers, started, blocked, note, complete, db=None, now=None, sleep=time.sleep):
    """Write one store's scrape, waiting out a database that cannot be reached. Returns the run document."""
    for attempt in range(len(WAITS) + 1):
        try:
            conn = db if db is not None else _connect()
            return _dbmod(conn).write_store(conn, store, offers, now or _utcnow(), blocked, started=started, note=note,
                                            complete=complete)
        except SystemExit:
            raise
        except Exception as e:
            if not _unreachable(e) or attempt == len(WAITS):
                raise
            print(f"database not reachable ({safe_error(e)}), trying again in {WAITS[attempt]} s", file=sys.stderr)
            db = None
            sleep(WAITS[attempt])


def _save(store, offers, started, blocked, note, complete):
    """Keep a scrape the database refused, so `replay` can write it later instead of fetching everything again."""
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{store}-offers.json"
    path.write_text(json.dumps({"store": store, "started": started, "blocked": blocked, "note": note,
                                "complete": complete, "offers": offers}, default=str))
    return path


def _connect():
    """MySQL (Hostinger) when MYSQL_URL is set, otherwise MongoDB from MONGO_URI."""
    url = os.environ.get("MYSQL_URL")
    if url:
        from . import sql_db
        return sql_db.connect(url)
    uri = os.environ.get("MONGO_URI")
    if not uri:
        raise SystemExit("Neither MYSQL_URL nor MONGO_URI is set")
    from pymongo import MongoClient
    return MongoClient(uri, serverSelectionTimeoutMS=20000, retryWrites=True)[DB_NAME]


def _report(name, doc):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(doc, default=str, indent=1))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and "store" in doc:
        with open(summary, "a") as f:
            f.write(f"| {doc['store']} | {doc['status']} | {doc['fetched']} | {doc['written']} | "
                    f"{doc['previous_count']} | {doc.get('seconds', '')} | {doc.get('note', '')} |\n")
    print(json.dumps(doc, default=str))


def _dbmod(db):
    """The module that knows how to talk to this kind of connection."""
    if type(db).__module__.startswith("pymysql"):
        from . import sql_db
        return sql_db
    return store_db


def scrape(store, dry_run=False, max_pages=None, time_budget=None, db=None, now=None, fetcher=None, clock=time.monotonic,
           sleep=time.sleep, save=False):
    """Scrape one store. Returns (exit_code, run document)."""
    cfg = dict(STORES[store])
    if max_pages:
        cfg["max_pages"] = max_pages
    fetcher = fetcher or Fetcher_(cfg["mode"], cfg["delay"])
    started, t0 = now or _utcnow(), clock()
    if time_budget and hasattr(fetcher, "deadline"):
        fetcher.deadline = t0 + time_budget          # enforced at every request, even when nothing is yielded
    offers, blocked, complete, note = [], False, True, ""
    try:
        for raw in ADAPTERS[cfg["adapter"]].iter_offers(cfg, fetcher):
            clean = normalize(raw, store)
            if clean:
                offers.append(clean)
            if time_budget and clock() - t0 > time_budget:
                complete, note = False, "time budget reached"
                break
    except BlockedError:
        blocked, note = True, "blocked by store"
    except TimeBudgetExceeded:
        complete, note = False, "time budget reached"
    except EmptyListingError:
        complete, note = False, "no products found"
    except IncompleteError:
        complete, note = False, "store stopped responding part-way"
    except Exception as e:                      # keep whatever was fetched; never crash the job silently
        complete, note = False, safe_error(e)
        if not offers and _network_error(e):
            # The store did not answer at all (timeouts, dropped connections). Like a refusal: nothing is written,
            # old prices stay, and the store is tried again from another machine instead of failing the run.
            blocked, note = True, "store did not answer: " + note
    seconds = int(clock() - t0)
    if dry_run:
        run = {"store": store, "started": started, "status": "dry-run", "fetched": len({o["url"] for o in offers}),
               "written": 0, "previous_count": 0, "note": note, "blocked": blocked, "complete": complete}
    elif save:
        # The database is written from the Hostinger server itself (tools/hostinger_sync.sh replays this file there),
        # so this machine never connects to it. Hostinger's firewall refuses some GitHub machines on the MySQL port.
        _save(store, offers, started, blocked, note, complete)
        run = {"store": store, "started": started, "status": "blocked" if blocked else "saved" if offers else "failed",
               "fetched": len({o["url"] for o in offers}), "written": 0, "previous_count": 0, "note": note}
    else:
        try:
            run = _write(store, offers, started, blocked, note, complete, db=db, now=now, sleep=sleep)
        except SystemExit:
            raise
        except Exception as e:
            run = {"store": store, "started": started, "status": "failed", "fetched": len(offers), "written": 0,
                   "previous_count": 0, "note": "database: " + safe_error(e)}
            if offers and _unreachable(e):
                _save(store, offers, started, blocked, note, complete)
                run["note"] += "; scrape saved for replay"
    run["seconds"] = seconds
    _report(store, run)
    if run["status"] == "blocked" or (dry_run and blocked):
        return BLOCKED_EXIT, run
    return (0 if run["status"] in ("ok", "dry-run", "saved") and (not dry_run or (offers and complete)) else 1), run


def replay_cmd(path, db=None, now=None, sleep=time.sleep):
    """Write a scrape that `scrape` saved because the database could not be reached."""
    saved = json.loads(pathlib.Path(path).read_text())
    started = datetime.fromisoformat(saved["started"]) if isinstance(saved["started"], str) else saved["started"]
    run = _write(saved["store"], saved["offers"], started, saved["blocked"], saved["note"], saved["complete"], db=db,
                 now=now, sleep=sleep)
    run["note"] = (run.get("note") or "") + ("; " if run.get("note") else "") + "written from a saved scrape"
    _report(saved["store"], run)
    if run["status"] in ("ok", "partial", "blocked"):
        pathlib.Path(path).unlink()
    return (0 if run["status"] == "ok" else 1), run


def rollup_cmd(db=None, now=None):
    db = db if db is not None else _connect()
    mod = _dbmod(db)
    mod.ensure_indexes(db)
    out = mod.write_rollup(db, now or _utcnow())
    _report("rollup", out)
    return 0, out


def health_cmd(hours, db=None, now=None, stores=None):
    """Exit 1 when a store has had no good run for `hours`: the one situation worth an alert."""
    db = db if db is not None else _connect()
    stale = _dbmod(db).stale_stores(db, list(stores or STORES), now or _utcnow(), hours)
    out = {"stale": stale, "hours": hours}
    _report("health", out)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and stale:
        with open(summary, "a") as f:
            f.write(f"\nNo good run in the last {hours} hours: {', '.join(stale)}\n")
    return (1 if stale else 0), out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pph.run")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scrape")
    s.add_argument("store")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--max-pages", type=int)
    s.add_argument("--time-budget", type=int, help="minutes; stop cleanly and keep what was fetched")
    s.add_argument("--save", action="store_true", help="save to out/<store>-offers.json for the server to write; no database")
    sub.add_parser("rollup")
    r = sub.add_parser("replay")
    r.add_argument("file")
    h = sub.add_parser("health")
    h.add_argument("--hours", type=int, default=26)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "rollup":
            return rollup_cmd()[0]
        if a.cmd == "health":
            return health_cmd(a.hours)[0]
        if a.cmd == "replay":
            return replay_cmd(a.file)[0]
        if a.store not in STORES:
            print(f"unknown store: {a.store}", file=sys.stderr)
            return 2
        return scrape(a.store, a.dry_run, a.max_pages, a.time_budget * 60 if a.time_budget else None, save=a.save)[0]
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 2
    except Exception as e:
        print("error:", safe_error(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
