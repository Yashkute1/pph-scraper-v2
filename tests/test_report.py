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
