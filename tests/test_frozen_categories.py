"""Safety net for the classifier: no live product may change category by accident.

tests/fixtures/frozen_categories.tsv.gz holds every title the other stores list on the live site (Amazon's are not kept here) (one "title<TAB>category-slug" per line) with the
category the rules gave it when it was last reviewed. Any rule change that moves even one title fails this test and prints
every move, grouped by from -> to, so the change has to be read before it can land.

Moves you meant to make: run `python -m tools.freeze_categories`, read the printed list, and commit the new fixture with the
rule change. The diff of the fixture is the review record."""
import collections
import gzip
from pathlib import Path

import pytest

from tools.freeze_categories import FROZEN, moves

HOW = "Read every move above. If all are intended, run: python -m tools.freeze_categories  and commit the new fixture."


def load():
    with gzip.open(FROZEN, "rt", encoding="utf-8") as f:
        return [line.rstrip("\n").split("\t", 1) for line in f if line.strip()]


def test_no_title_changes_category_by_accident():
    changed = moves(load())
    if changed:
        by_pair = collections.Counter((old, new) for _, old, new in changed)
        lines = [f"{n:5} {old} -> {new}" for (old, new), n in by_pair.most_common(25)]
        lines += [f"      {old} -> {new}  {title[:90]}" for title, old, new in changed[:40]]
        pytest.fail(f"{len(changed)} titles would change category:\n" + "\n".join(lines) + "\n" + HOW)


def test_the_check_really_sees_a_change(monkeypatch):
    """A rule that moves a title must be reported, not silently accepted."""
    import tools.freeze_categories as fc
    rows = [["APC SRV2KL-IN 230 V Online/double-conversion Tower Model, Rack-mount Model UPS 2000VA", "ups"]]
    assert fc.moves(rows) == []
    monkeypatch.setattr(fc, "type_of", lambda title: "Accessories")
    assert fc.moves(rows) == [(rows[0][0], "ups", "accessories")]


def test_the_frozen_set_covers_the_live_catalogue_and_every_category():
    rows = load()
    assert len(rows) > 30000
    assert len({title for title, _ in rows}) == len(rows)          # one line per title
    cats = {cat for _, cat in rows}
    assert {"ups", "headset", "pc-case-chassis", "components", "keyboard", "networking"} <= cats
