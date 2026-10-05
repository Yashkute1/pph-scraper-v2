import json
from tools.report import build


def test_report_table(tmp_path):
    (tmp_path / "out-a").mkdir(); (tmp_path / "out-b").mkdir(); (tmp_path / "out-rollup").mkdir()
    (tmp_path / "out-a" / "a.json").write_text(json.dumps({"store": "a", "status": "ok", "fetched": 10, "written": 10, "previous_count": 9, "seconds": 5, "note": ""}))
    (tmp_path / "out-b" / "b.json").write_text(json.dumps({"store": "b", "status": "blocked", "fetched": 0, "written": 0, "previous_count": 4, "seconds": 2, "note": "blocked by store"}))
    (tmp_path / "out-rollup" / "rollup.json").write_text(json.dumps({"products": 7, "skipped": False, "bytes": 1048576, "trimmed": False}))
    md = build(tmp_path, ["a", "b", "c"], "2026-10-04 03:00 UTC")
    assert "| a | ok | 10 | 10 | 9 | 5 |  |" in md
    assert "| b | blocked | 0 | 0 | 4 | 2 | blocked by store |" in md
    assert "| c | no report |" in md                      # a job that died before reporting is still listed
    assert "Products: 7" in md and "1.0 MB" in md and "2026-10-04 03:00 UTC" in md
    assert "1 of 3 stores ok" in md


def test_a_retried_store_is_reported_by_its_good_attempt(tmp_path):
    for d, status in (("out-a", "blocked"), ("out-retry-a", "ok")):
        (tmp_path / d).mkdir()
        (tmp_path / d / "a.json").write_text(json.dumps({"store": "a", "status": status, "fetched": 5, "written": 5, "previous_count": 5, "seconds": 1, "note": ""}))
    md = build(tmp_path, ["a"], "t")
    assert "| a | ok |" in md and "blocked" not in md and "1 of 1 stores ok" in md
