"""The site's data as it may be published: everything except Amazon, whose rules do not allow republishing it.

Product rows are rebuilt from the other stores' offers, not read from the products table, so a part Amazon also sells
shows no Amazon price, title or photo, and a part only Amazon sells is left out."""
from datetime import datetime

from pph import sql_db
from pph.benchmarks import build_lookup
from pph.group import AMAZON, rollup


def public_offers(offers):
    return [o for o in offers if o.get("store") != AMAZON]


def products(offers, benchmarks=None, now=None):
    """Product rows, shaped like the products table, built from the publishable offers."""
    try:
        lookup = build_lookup(benchmarks) if benchmarks is not None else None
    except Exception:
        lookup = None
    rows = rollup(public_offers(offers), now or datetime.utcnow(), lookup)
    return [{c: r.get(c) for c in sql_db.PRODUCT_COLS} for r in rows]


def sql_products(db):
    try:
        benchmarks = sql_db.read_benchmarks(db)
    except Exception:
        benchmarks = None
    return products(sql_db.read_offers(db), benchmarks)
