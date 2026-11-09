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
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

SITE_ENV = pathlib.Path.home() / "domains/pcparthunt.com/hbuilds/config/.env"
BRANCH = "origin/scrapes"
JOBS_BRANCH = "origin/server-jobs"
EXPORTS = pathlib.Path.home() / "pph/exports"
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
    results, code = [], 0
    with tempfile.TemporaryDirectory() as tmp:
        for name in sorted(names):
            raw = subprocess.run(["git", "-C", str(repo), "show", f"{head}:{name}"], check=True, capture_output=True).stdout
            path = pathlib.Path(tmp) / name[:-3]
            path.write_bytes(gzip.decompress(raw))
            try:
                c, run = R.replay_cmd(path, db=db, now=now)
                results.append({"store": run["store"], "status": run["status"], "written": run["written"]})
                code = code or (0 if run["status"] in ("ok", "partial", "blocked") else 1)
            except Exception as e:                       # one store's failure must not stop the others
                results.append({"store": name.split("-")[0], "status": "error", "note": R.safe_error(e)})
                code = 1
        if names:
            R.rollup_cmd(db=db, now=now)
            stale = R.health_cmd(26, db=db, now=now)[1]["stale"]
        else:
            stale = []
    # A store that could not be written (the database was down) is tried again on the next run, the whole commit with
    # it: writing a store twice on one day keeps one history point and counts a missed offer once.
    tries = state / "tries"
    n = int(tries.read_text().split()[1]) + 1 if tries.exists() and tries.read_text().split()[0] == head else 1
    if code == 0 or n >= TRIES:
        (state / "written").write_text(head + "\n")
        tries.unlink(missing_ok=True)
    else:
        tries.write_text(f"{head} {n}\n")
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


JOBS = {"rollup": _job_rollup, "redirects": _job_redirects}


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
        code, summary = sync(repo, state)
        job = run_job(repo, state)
        # Only after the database changed, and once at the start so the files exist. A failure here leaves the last good files.
        if summary.get("written") or job or not (EXPORTS / "offers.tsv.gz").exists():
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
