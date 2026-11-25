"""Write every live offer's store, category, price, stock, title, URL and freshness to audit/offers.tsv, for checking the catalogue.
Amazon is left out (tools/public_data.py).

    MYSQL_URL=... python -m tools.audit_dump

Public product data only."""
import os
import pathlib

from pph import sql_db
from pph.group import AMAZON
from tools import public_data


def dump(db, out):
    """Write offers.tsv and products.tsv into the directory `out`."""
    out = pathlib.Path(out)
    with db.cursor() as cur, open(out / "offers.tsv", "w", encoding="utf-8") as f:
        cur.execute("SELECT o.store, o.category, o.price, o.in_stock, o.group_id, REPLACE(REPLACE(o.title, '\t', ' '), '\n', ' '), "
                    "o.url, o.mrp, o.last_seen, o.missed_runs, o.image <> '', o.brand "
                    "FROM offers o WHERE o.store <> %s ORDER BY o.category, o.title", (AMAZON,))
        f.write("store\tcategory\tprice\tin_stock\tgroup_id\ttitle\turl\tmrp\tlast_seen\tmissed_runs\thas_image\tbrand\n")
        n = 0
        for r in cur.fetchall():
            f.write("\t".join(str(x) for x in r) + "\n"); n += 1
    print(n, "offers")
    rows = sorted(public_data.sql_products(db), key=lambda p: (p["category_slug"] or "", p["group_id"]))
    with open(out / "products.tsv", "w", encoding="utf-8") as f:
        f.write("group_id\tcategory_slug\tbrand\tbest_price\tany_stock\tstore_count\ttitle\n")
        for p in rows:
            title = str(p["title"]).replace("\t", " ").replace("\n", " ")
            r = (p["group_id"], p["category_slug"], p["brand"], p["best_price"], 1 if p["any_stock"] else 0, p["store_count"], title)
            f.write("\t".join(str(x) for x in r) + "\n")
    print(len(rows), "products")


def main():
    out = pathlib.Path("audit"); out.mkdir(exist_ok=True)
    dump(sql_db.connect(os.environ["MYSQL_URL"]), out)


if __name__ == "__main__":
    main()
