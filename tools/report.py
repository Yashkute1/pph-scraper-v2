"""Build status/latest.md from the per-store run files the scrape jobs uploaded."""
import json, pathlib, sys
from datetime import datetime, timezone


def build(root, stores, when):
    root = pathlib.Path(root)
    runs = {}
    for f in root.rglob("*.json"):
        try:
            d = json.loads(f.read_text())
        except ValueError:
            continue
        runs[d.get("store") or f.stem] = d
    ok = sum(1 for s in stores if runs.get(s, {}).get("status") in ("ok", "dry-run"))
    lines = [f"# Scraper status", "", f"Last run: {when}. {ok} of {len(stores)} stores ok.", "",
             "| store | status | fetched | written | previous | seconds | note |", "|---|---|---|---|---|---|---|"]
    for s in stores:
        d = runs.get(s)
        if not d:
            lines.append(f"| {s} | no report | | | | | job did not finish |")
            continue
        lines.append(f"| {s} | {d['status']} | {d['fetched']} | {d['written']} | {d['previous_count']} | {d.get('seconds', '')} | {d.get('note', '')} |")
    r = runs.get("rollup")
    if r:
        size = f", database {r['bytes'] / 1048576:.1f} MB" if r.get("bytes") else ""
        lines += ["", f"Products: {r['products']}{size}" + (" (roll-up skipped: no offers)" if r.get("skipped") else "")
                  + (" (history trimmed to stay inside the storage limit)" if r.get("trimmed") else "")]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    from pph.stores import STORES
    print(build(sys.argv[1], list(STORES), datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")), end="")
