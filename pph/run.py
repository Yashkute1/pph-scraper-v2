"""Command line: `python -m pph.run scrape <store> [--dry-run] [--max-pages N] [--time-budget MIN]` and `rollup`."""
import argparse
import json
import os
import pathlib
import sys
import time
from datetime import datetime, timezone

from . import DB_NAME
from .adapters import ADAPTERS
from .adapters.common import EmptyListingError
from .fetch import BlockedError, Fetcher_, TimeBudgetExceeded
from .normalize import normalize
from .stores import STORES
from . import store_db

OUT = pathlib.Path("out")


def safe_error(e):
    """Exception type only: messages can carry connection strings or URLs with credentials."""
    return type(e).__name__


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def _connect():
    uri = os.environ.get("MONGO_URI")
    if not uri:
        raise SystemExit("MONGO_URI is not set")
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


def scrape(store, dry_run=False, max_pages=None, time_budget=None, db=None, now=None, fetcher=None, clock=time.monotonic):
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
    except Exception as e:                      # keep whatever was fetched; never crash the job silently
        complete, note = False, safe_error(e)
    seconds = int(clock() - t0)
    if dry_run:
        run = {"store": store, "started": started, "status": "dry-run", "fetched": len({o["url"] for o in offers}),
               "written": 0, "previous_count": 0, "note": note, "blocked": blocked, "complete": complete}
    else:
        try:
            db = db if db is not None else _connect()
            run = store_db.write_store(db, store, offers, now or _utcnow(), blocked, started=started, note=note, complete=complete)
        except SystemExit:
            raise
        except Exception as e:
            run = {"store": store, "started": started, "status": "failed", "fetched": len(offers), "written": 0,
                   "previous_count": 0, "note": "database: " + safe_error(e)}
    run["seconds"] = seconds
    _report(store, run)
    return (0 if run["status"] in ("ok", "dry-run") and (not dry_run or (offers and complete and not blocked)) else 1), run


def rollup_cmd(db=None, now=None):
    db = db if db is not None else _connect()
    store_db.ensure_indexes(db)
    out = store_db.write_rollup(db, now or _utcnow())
    _report("rollup", out)
    return 0, out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pph.run")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scrape")
    s.add_argument("store")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--max-pages", type=int)
    s.add_argument("--time-budget", type=int, help="minutes; stop cleanly and keep what was fetched")
    sub.add_parser("rollup")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "rollup":
            return rollup_cmd()[0]
        if a.store not in STORES:
            print(f"unknown store: {a.store}", file=sys.stderr)
            return 2
        return scrape(a.store, a.dry_run, a.max_pages, a.time_budget * 60 if a.time_budget else None)[0]
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 2
    except Exception as e:
        print("error:", safe_error(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
