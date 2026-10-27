"""Write GitHub's scrapes into MySQL from the Hostinger server itself, then roll up.

GitHub scrapes each store and publishes the result on the `scrapes` branch of this public repository (one
`<store>-offers.json.gz` per store, plus `run.json`). This runs on the server every few minutes from cron
(tools/hostinger_sync.sh): when that branch has a commit it has not written yet, it replays every store file into the
database at 127.0.0.1 and runs the roll-up and the health check. Nothing outside the server connects to MySQL, so
Hostinger's firewall, which refuses some GitHub machines on the MySQL port, no longer matters.

The database address is the website's own: MYSQL_URL from the Node app's settings file, with the host set to
127.0.0.1. It is never printed. Usage: python -m tools.hostinger_sync <repo dir> <state dir>"""
import gzip
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

SITE_ENV = pathlib.Path.home() / "domains/pcparthunt.com/hbuilds/config/.env"
BRANCH = "origin/scrapes"
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
        return sync(repo, state)[0]
    except Exception as e:
        print("error:", R.safe_error(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
