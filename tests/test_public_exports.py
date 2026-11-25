"""Nothing the site publishes for download may carry Amazon data."""
import json

import mongomock
import pytest

from pph.store_db import ensure_indexes, write_rollup, write_store
from tests.test_export_sample import T0, o
from tests.test_sql_db import URL, db  # noqa: F401  (the scratch MySQL database; skipped without it)
from tools.export_sample import export

AMAZON_IMAGE = "https://m.media-amazon.com/images/I/secret.jpg"


def offers():
    """"mix" is sold by both, cheaper at Amazon; "only" is sold by Amazon alone."""
    mixed = o("amazon", "mix", 700, title="Amazon wording PN77X 1TB SSD")
    only = o("amazon", "only", 800, title="Amazon only PN88X 1TB SSD")
    for x in (mixed, only):
        x.update(url=x["url"].replace("amazon.test", "www.amazon.in"), image=AMAZON_IMAGE)
    return [mixed, only], [o("a", "mix", 900, title="Store wording PN77X 1TB SSD")]


def check(sample):
    text = json.dumps(sample, default=str).lower()
    assert "amazon" not in text and "secret.jpg" not in text
    assert len(sample["products"]) == 1          # the part only Amazon sells is not published
    p = sample["products"][0]
    assert (p["best_price"], p["best_store"], p["store_count"], p["title"]) == (900, "a", 1, "Store wording PN77X 1TB SSD")
    assert [x["store"] for x in sample["offers"]] == ["a"]
    assert [r["store"] for r in sample["runs"]] == ["a"]


def test_the_sample_leaves_amazon_out():
    db = mongomock.MongoClient().pph_site
    ensure_indexes(db)
    amazon, other = offers()
    write_store(db, "amazon", amazon, T0, False)
    write_store(db, "a", other, T0, False)
    write_rollup(db, T0)
    check(export(db))


@pytest.mark.skipif(not URL, reason="PPH_TEST_MYSQL is not set")
def test_server_exports_leave_amazon_out(db, tmp_path):
    import gzip
    from pph.run import rollup_cmd
    from pph.sql_db import write_store
    from tools.hostinger_sync import refresh_exports
    amazon, other = offers()
    write_store(db, "amazon", amazon, T0, False)
    write_store(db, "a", other, T0, False)
    rollup_cmd(db=db, now=T0)
    refresh_exports(db, tmp_path)
    read = lambda n: gzip.decompress((tmp_path / n).read_bytes()).decode()
    for name in ("offers.tsv.gz", "products.tsv.gz", "sample.json.gz"):
        text = read(name).lower()
        assert "amazon" not in text and "secret.jpg" not in text, name
    assert len(read("offers.tsv.gz").splitlines()) == 2
    assert read("products.tsv.gz").splitlines()[1].split("\t")[1:] == \
        ["ssd", "MSI", "900", "1", "1", "Store wording PN77X 1TB SSD"]
    check(json.loads(read("sample.json.gz")))

