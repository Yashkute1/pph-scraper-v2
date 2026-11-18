"""Freeze the category every live title gets, for tests/test_frozen_categories.py.

    python -m tools.freeze_categories live          # add the live site's titles, then freeze
    python -m tools.freeze_categories products.tsv  # same, from a saved export
    python -m tools.freeze_categories               # just re-freeze the titles already in the fixture

Prints every title whose category differs from the last freeze, grouped by from -> to, before writing. Read that list: it is the
review record for a classifier change. Public product titles only."""
import collections
import gzip
import io
import sys
import urllib.request
from pathlib import Path

from pph.group import slug
from pph.normalize import type_of

FROZEN = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "frozen_categories.tsv.gz"
LIVE = "https://pcparthunt.com/api/export/products.tsv.gz"


def moves(rows):
    """[(title, frozen_slug, slug_now)] for every row whose category the current rules change."""
    out = []
    for title, old in rows:
        new = slug(type_of(title))
        if new != old:
            out.append((title, old, new))
    return out


def _clean(title):
    return " ".join(str(title).replace("\t", " ").split())


def _read_frozen():
    if not FROZEN.exists():
        return {}
    with gzip.open(FROZEN, "rt", encoding="utf-8") as f:
        return dict(line.rstrip("\n").split("\t", 1) for line in f if line.strip())


def _titles_from(source):
    raw = urllib.request.urlopen(LIVE, timeout=60).read() if source == "live" else Path(source).read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    lines = io.StringIO(raw.decode("utf-8")).read().split("\n")
    head = lines[0].split("\t")
    col = head.index("title")
    return [_clean(line.split("\t")[col]) for line in lines[1:] if line.strip()]


def main(argv):
    frozen = _read_frozen()
    titles = list(frozen)
    if argv:
        seen = set(frozen)
        titles += [t for t in _titles_from(argv[0]) if t and t not in seen and not seen.add(t)]
    changed = [(t, frozen[t], slug(type_of(t))) for t in titles if t in frozen and slug(type_of(t)) != frozen[t]]
    new_titles = [t for t in titles if t not in frozen]
    if changed:
        for (old, new), n in collections.Counter((o, n) for _, o, n in changed).most_common():
            print(f"{n:5} {old} -> {new}")
        for t, old, new in changed[:60]:
            print(f"      {old} -> {new}  {t[:100]}")
        print(f"{len(changed)} titles change category since the last freeze")
    print(f"{len(new_titles)} new titles")
    FROZEN.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(FROZEN, "wt", encoding="utf-8", compresslevel=9) as f:
        for t in titles:
            f.write(f"{t}\t{slug(type_of(t))}\n")
    print(f"froze {len(titles)} titles -> {FROZEN}")


if __name__ == "__main__":
    main(sys.argv[1:])
