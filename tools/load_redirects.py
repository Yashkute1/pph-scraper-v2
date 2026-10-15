"""Load old -> new product addresses into group_redirects from a two-column TSV, for ids that changed in a run that
stopped before it could record them.

    MYSQL_URL=... python -m tools.load_redirects redirects.tsv

Pairs whose old id is still a product, or whose new id is not one, are skipped. Prints counts only."""
import os
import sys
from datetime import datetime, timezone

from pph import sql_db


def load(db, pairs, now):
    with db.cursor() as cur:
        cur.execute("SELECT group_id FROM products")
        live = {r[0] for r in cur.fetchall()}
        good = [(old, new, now) for old, new in pairs if old not in live and new in live and old != new]
        sql_db._many(cur, "REPLACE INTO group_redirects (old_id, group_id, created) VALUES (%s,%s,%s)", good)
    return {"pairs": len(pairs), "loaded": len(good), "skipped": len(pairs) - len(good)}


def main():
    pairs = [tuple(line.rstrip("\n").split("\t")[:2]) for line in open(sys.argv[1], encoding="utf-8") if "\t" in line]
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    print(load(sql_db.connect(os.environ["MYSQL_URL"]), pairs, now))


if __name__ == "__main__":
    main()
