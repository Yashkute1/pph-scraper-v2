"""Write GitHub's scrapes into MySQL from the Hostinger server itself, then roll up.

GitHub scrapes each store and publishes the result on the `scrapes` branch of this public repository (one
`<store>-offers.json.gz` per store, plus `run.json`). This runs on the server every few minutes from cron
(tools/hostinger_sync.sh): when that branch has a commit it has not written yet, it replays every store file into the
database at 127.0.0.1 and runs the roll-up and the health check. Nothing outside the server connects to MySQL, so
Hostinger's firewall, which refuses some GitHub machines on the MySQL port, no longer matters.

After each write it refreshes the export files the site serves at /api/export/ (public product data, for the audit,
stock check and test-sample workflows), and it runs jobs GitHub requests on the `server-jobs` branch: only the names in
JOBS, each once. Their results appear at /api/export/job.json.

The database address is the website's own: MYSQL_URL from the Node app's settings file, with the host set to
127.0.0.1. It is never printed. Usage: python -m tools.hostinger_sync <repo dir> <state dir>"""
import gzip
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

SITE_ENV = pathlib.Path.home() / "domains/pcparthunt.com/hbuilds/config/.env"
BRANCH = "origin/scrapes"
JOBS_BRANCH = "origin/server-jobs"
EXPORTS = pathlib.Path.home() / "pph/exports"
AMAZON_SECONDS = 480       # the most one run spends asking Amazon (cron runs every 10 minutes)
ROLLUP_EVERY = timedelta(hours=6)    # Amazon prices expire even when no new scrape arrives
AMAZON_ENV = ("AMAZON_CREATORS_CREDENTIAL_ID", "AMAZON_CREATORS_CREDENTIAL_SECRET", "AMAZON_CREATORS_CREDENTIAL_VERSION",
              "AMAZON_PARTNER_TAG")
TRIES = 3                  # a commit that keeps failing is given up after this many runs, so one bad file cannot loop


def local_url(env_text):
    """MYSQL_URL from a .env file, pointed at this server (127.0.0.1). None when the file does not name one."""
    m = re.search(r"^\s*(?:export\s+)?MYSQL_URL\s*=\s*(.+?)\s*$", env_text, re.M)
    if not m:
        return None
    url = m.group(1).strip().strip("'\"")
    p = urlsplit(url)
    if p.scheme not in ("mysql", "mysql+pymysql") or not p.hostname:
        return None
    auth = p.netloc.rsplit("@", 1)[0] + "@" if "@" in p.netloc else ""
    return urlunsplit((p.scheme, f"{auth}127.0.0.1:{p.port or 3306}", p.path, p.query, ""))


def env_values(env_text, names):
    """The non-empty values a .env text gives for `names`."""
    out = {}
    for name in names:
        m = re.search(rf"^[ \t]*(?:export[ \t]+)?{re.escape(name)}[ \t]*=[ \t]*(.*?)[ \t]*$", env_text, re.M)
        value = m.group(1).strip().strip("'\"") if m else ""
        if value:
            out[name] = value
    return out


def amazon_step(db, env, now, api=None, log=print):
    """Refresh due Amazon prices (when there are credentials), then roll up if any changed or the products are old,
    so a price past its day leaves the site. True when it rolled up."""
    from pph import amazon_api
    from pph import run as R
    from tools import amazon_refresh
    changed = False
    try:
        if api is None:
            creds = amazon_api.credentials(env)
            api = amazon_api.AmazonApi(creds) if creds else None
        if api is not None:
            from pph.sql_db import ensure_indexes
            ensure_indexes(db)
            out = amazon_refresh.refresh(db, api, now, deadline=time.monotonic() + AMAZON_SECONDS)
            changed = bool(out["priced"] or out["blanked"])
            if out["asked"] or out["note"]:
                log("amazon: " + json.dumps(out))
    except Exception as e:                                # expiry below must still happen
        log(f"amazon: {R.safe_error(e)}")
    with db.cursor() as cur:
        cur.execute("SELECT MAX(updated_at) FROM products")
        last = cur.fetchone()[0]
    if changed or not last or now - last >= ROLLUP_EVERY:
        R.rollup_cmd(db=db, now=now)
        return True
    return False


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def pending(repo, state):
    """The scrapes commit to write, or None when it was written already (or there is none yet)."""
    try:
        head = git(repo, "rev-parse", BRANCH).strip()
    except subprocess.CalledProcessError:
        return None
    done = state / "written"
    return None if done.exists() and done.read_text().strip() == head else head


def sync(repo, state, db=None, now=None, log=print):
    """Write the newest scrapes commit, if any. Returns (exit code, summary)."""
    from pph import run as R

    head = pending(repo, state)
    # When this run looked, so a quiet run (nothing new) can be told from one that never ran.
    (state / "checked").write_text((now or datetime.now(timezone.utc)).isoformat(timespec="seconds") + "\n")
    if not head:
        return 0, {"written": [], "note": "nothing new"}
    names = [n for n in git(repo, "ls-tree", "--name-only", head).split() if n.endswith("-offers.json.gz")]
    # A commit tried before: only the stores that failed are written again. Writing a store a second time would count
    # every part its scrape did not meet as missed once more.
    tries = state / "tries"
    seen = tries.read_text().split() if tries.exists() else []
    again = bool(seen) and seen[0] == head
    n = int(seen[1]) + 1 if again else 1
    done = set(seen[2].split(",")) if again and len(seen) > 2 else set()
    results, code, retry = [], 0, False
    with tempfile.TemporaryDirectory() as tmp:
        for name in sorted(x for x in names if x not in done):
            raw = subprocess.run(["git", "-C", str(repo), "show", f"{head}:{name}"], check=True, capture_output=True).stdout
            path = pathlib.Path(tmp) / name[:-3]
            path.write_bytes(gzip.decompress(raw))
            try:
                c, run = R.replay_cmd(path, db=db, now=now)
                results.append({"store": run["store"], "status": run["status"], "written": run["written"]})
                if run["status"] in ("ok", "partial", "blocked"):
                    done.add(name)
                else:
                    code, retry = 1, True
            except Exception as e:                       # one store's failure must not stop the others
                from pph.seal import Unopenable
                results.append({"store": name.split("-")[0], "status": "error", "note": R.safe_error(e)})
                code = 1
                if isinstance(e, Unopenable):
                    done.add(name)                       # it never will open: not a reason to try the commit again
                else:
                    retry = True
        if names:
            R.rollup_cmd(db=db, now=now)
            stale = R.health_cmd(26, db=db, now=now)[1]["stale"]
        else:
            stale = []
    # A store that could not be written (the database was down) is tried again on the next run.
    if not retry or n >= TRIES:
        (state / "written").write_text(head + "\n")
        tries.unlink(missing_ok=True)
    else:
        tries.write_text(f"{head} {n} {','.join(sorted(done))}\n")
    summary = {"commit": head[:9], "written": results, "stale": stale, "try": n,
               "at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")}
    (state / "last.json").write_text(json.dumps(summary, indent=1))
    log(json.dumps(summary))
    return code, summary


def _publish(tmp, final):
    """Gzip `tmp` beside `final` and move it into place, so the site never serves a half-written file."""
    part = final.with_name(final.name + ".part")
    with open(tmp, "rb") as src, gzip.open(part, "wb", 6) as dst:
        shutil.copyfileobj(src, dst)
    os.replace(part, final)


def refresh_exports(db, out=None):
    """Rewrite the files the site serves: the audit dump and the sample for the website's tests."""
    from tools import audit_dump, export_sample
    out = pathlib.Path(out or EXPORTS)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        tmp = pathlib.Path(tmp)
        audit_dump.dump(db, tmp)
        (tmp / "sample.json").write_text(json.dumps(export_sample.export_sql(db), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        for name in ("offers.tsv", "products.tsv", "sample.json"):
            _publish(tmp / name, out / (name + ".gz"))


def _job_rollup(repo, db, now):
    from pph import run as R
    return R.rollup_cmd(db=db, now=now)[1]


def _job_redirects(repo, db, now):
    """Load old -> new product addresses from redirects.tsv on the `audit` branch."""
    from pph import run as R
    from tools import load_redirects
    git(repo, "fetch", "-q", "--depth", "1", "origin", "+refs/heads/audit:refs/remotes/origin/audit")
    text = git(repo, "show", "origin/audit:redirects.tsv")
    pairs = [tuple(line.split("\t")[:2]) for line in text.splitlines() if "\t" in line]
    when = (now or datetime.now(timezone.utc)).replace(tzinfo=None, microsecond=0)
    return load_redirects.load(db if db is not None else R._connect(), pairs, when)


def _job_clear_amazon(repo, db, now):
    """Delete stored Amazon price history (irreversible)."""
    from pph import run as R
    from pph import sql_db
    return sql_db.clear_amazon_history(db if db is not None else R._connect())


JOBS = {"rollup": _job_rollup, "redirects": _job_redirects, "amazon-history-clear": _job_clear_amazon}


def run_job(repo, state, exports=None, db=None, now=None):
    """Run the job requested on the jobs branch, once. Returns its result, or None when there is nothing to do."""
    from pph import run as R
    try:
        head = git(repo, "rev-parse", JOBS_BRANCH).strip()
    except subprocess.CalledProcessError:
        return None
    done = state / "job-done"
    if done.exists() and done.read_text().strip() == head:
        return None
    done.write_text(head + "\n")                        # before running: a job that kills the run is not repeated forever
    try:
        req = json.loads(git(repo, "show", f"{head}:job.json"))
    except (subprocess.CalledProcessError, ValueError):
        req = {}
    name, rid = str(req.get("job")), str(req.get("id"))
    result = {"id": rid if re.fullmatch(r"\d{1,20}", rid) else "", "job": name if name in JOBS else "", "status": "failed"}
    if name not in JOBS or not result["id"]:
        result["note"] = "not an allowed job"
    else:
        try:
            result.update(status="ok", out=JOBS[name](repo, db, now))
        except Exception as e:
            result["note"] = R.safe_error(e)
    result["at"] = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    out = pathlib.Path(exports or EXPORTS)
    out.mkdir(parents=True, exist_ok=True)
    (out / "job.json.part").write_text(json.dumps(result, default=str))
    os.replace(out / "job.json.part", out / "job.json")
    print(json.dumps(result, default=str))
    return result


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    repo, state = pathlib.Path(argv[0]), pathlib.Path(argv[1])
    state.mkdir(parents=True, exist_ok=True)
    url = local_url(SITE_ENV.read_text()) if SITE_ENV.exists() else None
    url = os.environ.get("MYSQL_URL") or url
    if not url:
        print(f"no MYSQL_URL in {SITE_ENV}", file=sys.stderr)
        return 2
    os.environ["MYSQL_URL"] = url
    from pph import run as R
    R.OUT = state / "out"                               # replay's reports go here, not into the code checkout
    try:
        from pph import seal
        os.environ["PPH_AMAZON_KEY"] = str(seal.ensure_key(state, EXPORTS))
    except Exception as e:                              # without a key only the Amazon file cannot be written
        print("amazon key:", R.safe_error(e), file=sys.stderr)
    try:
        code, summary = sync(repo, state)
        job = run_job(repo, state)
        rolled = False
        try:
            env_text = SITE_ENV.read_text() if SITE_ENV.exists() else ""
            env = {**env_values(env_text, AMAZON_ENV), **{k: v for k, v in os.environ.items() if k in AMAZON_ENV and v}}
            rolled = amazon_step(R._connect(), env, datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0))
        except Exception as e:
            print("amazon:", R.safe_error(e), file=sys.stderr)
            code = code or 1
        # Only after the database changed, and once at the start so the files exist. A failure here leaves the last good files.
        if summary.get("written") or job or rolled or not (EXPORTS / "offers.tsv.gz").exists():
            try:
                refresh_exports(R._connect())
            except Exception as e:
                print("exports:", R.safe_error(e), file=sys.stderr)
                code = code or 1
        return code
    except Exception as e:
        print("error:", R.safe_error(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
