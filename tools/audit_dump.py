"""Write every live offer's store, category, price, stock and title to audit/offers.tsv, for checking classification.

    MYSQL_URL=... python -m tools.audit_dump

Public product data only."""
import os
import pathlib

from pph import sql_db


def main():
    db = sql_db.connect(os.environ["MYSQL_URL"])
    out = pathlib.Path("audit"); out.mkdir(exist_ok=True)
    with db.cursor() as cur, open(out / "offers.tsv", "w", encoding="utf-8") as f:
        cur.execute("SELECT o.store, o.category, o.price, o.in_stock, o.group_id, REPLACE(REPLACE(o.title, '\t', ' '), '\n', ' ') "
                    "FROM offers o ORDER BY o.category, o.title")
        f.write("store\tcategory\tprice\tin_stock\tgroup_id\ttitle\n")
        n = 0
        for r in cur.fetchall():
            f.write("\t".join(str(x) for x in r) + "\n"); n += 1
    print(n, "offers")


if __name__ == "__main__":
    main()
