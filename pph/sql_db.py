"""All MySQL / MariaDB access (Hostinger). Same behaviour as store_db.py, which does the same for MongoDB.

Tables: offers (one row per store listing), products (the site's one row per part, rebuilt by the roll-up),
product_facets and product_stores (the part's filter values and stores, so the site can filter and count without
reading JSON), scrape_runs, benchmarks and legacy_redirects. Lists and objects are stored as JSON text.

The roll-up builds fresh copies of the three product tables and swaps them in with one RENAME, so the site never
reads a half-written catalogue."""
import json
from datetime import datetime, timedelta
from urllib.parse import unquote, urlsplit

from .benchmarks import build_lookup
from .group import rollup
from .normalize import recategorize
from .store_db import BATCH, DELETE_AFTER, MISSED_LIMIT, _history, gate, offer_id  # noqa: F401  (shared rules)

SIZE_BUDGET = int(2.5 * 1024 ** 3)       # Hostinger gives each database 3 GB

OFFER_COLS = ["id", "store", "url", "title", "price", "mrp", "in_stock", "image", "brand", "category", "model_key",
              "group_id", "specs", "history", "last_seen", "first_seen", "missed_runs"]
PRODUCT_COLS = ["group_id", "title", "brand", "category", "category_slug", "brand_slug", "image", "best_price",
                "best_store", "best_url", "mrp", "any_stock", "store_count", "stores", "offers", "low_90d", "updated_at",
                "specs", "facets", "drop_pct", "spread_pct", "benchmark"]
JSON_PRODUCT = {"stores", "offers", "specs", "facets", "benchmark"}

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS offers (
      id CHAR(24) NOT NULL PRIMARY KEY, store VARCHAR(32) NOT NULL, url VARCHAR(2048) NOT NULL, title VARCHAR(1000) NOT NULL,
      price INT NOT NULL, mrp INT NULL, in_stock TINYINT(1) NOT NULL DEFAULT 1, image VARCHAR(2048) NOT NULL DEFAULT '',
      brand VARCHAR(120) NULL, category VARCHAR(64) NULL, model_key VARCHAR(191) NULL, group_id VARCHAR(191) NULL,
      specs TEXT NULL, history MEDIUMTEXT NULL, last_seen DATETIME NULL, first_seen DATETIME NULL, missed_runs INT NOT NULL DEFAULT 0,
      KEY store_missed (store, missed_runs), KEY store_seen (store, last_seen), KEY group_id (group_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS products (
      group_id VARCHAR(191) NOT NULL PRIMARY KEY, title VARCHAR(1000) NOT NULL, brand VARCHAR(120) NULL, category VARCHAR(64) NULL,
      category_slug VARCHAR(64) NOT NULL DEFAULT '', brand_slug VARCHAR(120) NOT NULL DEFAULT '', image VARCHAR(2048) NOT NULL DEFAULT '',
      best_price INT NOT NULL, best_store VARCHAR(32) NOT NULL, best_url VARCHAR(2048) NOT NULL DEFAULT '', mrp INT NULL,
      any_stock TINYINT(1) NOT NULL, store_count INT NOT NULL, stores TEXT NOT NULL, offers MEDIUMTEXT NOT NULL, low_90d INT NULL,
      updated_at DATETIME NOT NULL, specs TEXT NULL, facets TEXT NULL, drop_pct DOUBLE NOT NULL DEFAULT 0, spread_pct DOUBLE NOT NULL DEFAULT 0,
      benchmark TEXT NULL,
      KEY cat_popular (category_slug, any_stock, store_count, best_price), KEY cat_price (category_slug, any_stock, best_price),
      KEY cat_brand (category_slug, brand_slug, any_stock, store_count), KEY popular (any_stock, store_count, best_price),
      KEY deals_drop (any_stock, drop_pct), KEY deals_spread (any_stock, spread_pct)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS product_facets (
      group_id VARCHAR(191) NOT NULL, k VARCHAR(32) NOT NULL, v VARCHAR(120) NOT NULL,
      PRIMARY KEY (group_id, k), KEY kv (k, v)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS product_stores (
      group_id VARCHAR(191) NOT NULL, store VARCHAR(32) NOT NULL, PRIMARY KEY (group_id, store), KEY store (store)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS scrape_runs (
      id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, store VARCHAR(32) NOT NULL, started DATETIME NOT NULL, finished DATETIME NULL,
      status VARCHAR(16) NOT NULL, fetched INT NOT NULL DEFAULT 0, written INT NOT NULL DEFAULT 0, previous_count INT NOT NULL DEFAULT 0,
      note VARCHAR(255) NOT NULL DEFAULT '', KEY store_started (store, started)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS benchmarks (
      id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, bucket VARCHAR(16) NULL, `rank` INT NULL, doc TEXT NOT NULL, KEY bucket_rank (bucket, `rank`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS group_redirects (
      old_id VARCHAR(191) NOT NULL PRIMARY KEY, group_id VARCHAR(191) NOT NULL, created DATETIME NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS legacy_redirects (
      old_id VARCHAR(64) NOT NULL PRIMARY KEY, group_id VARCHAR(191) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
]


def connect(url):
    """mysql://user:password@host:3306/database -> a pymysql connection that commits each statement."""
    import pymysql
    u = urlsplit(url)
    return pymysql.connect(host=u.hostname, port=u.port or 3306, user=unquote(u.username or ""), password=unquote(u.password or ""),
                           database=u.path.lstrip("/"), charset="utf8mb4", autocommit=True, connect_timeout=20, cursorclass=_retry_cursor(),
                           read_timeout=600, write_timeout=600)


def _iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(d, datetime) else d


def _json(v):
    return json.dumps(v, default=_iso, ensure_ascii=False, separators=(",", ":"))


def _rows(cur, sql, args=None):
    cur.execute(sql, args)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


MAX_STMT = 512 * 1024        # bytes per statement; shared hosts often reset connections that send very large packets
GONE = 2006                  # "server has gone away": the statement could not be sent, so it never ran


def _retry_cursor():
    """A cursor that reopens a connection the host has dropped and sends the statement again. Only error 2006 is
    retried: the statement was never delivered, so sending it again cannot apply it twice."""
    import pymysql

    class RetryCursor(pymysql.cursors.Cursor):
        max_stmt_length = MAX_STMT

        def execute(self, query, args=None, _tries=4):
            for attempt in range(_tries):
                try:
                    return super().execute(query, args)
                except pymysql.err.OperationalError as e:
                    if e.args[0] != GONE or attempt == _tries - 1:
                        raise
                    import time
                    time.sleep(2 * (attempt + 1))
                    self.connection.ping(reconnect=True)
    return RetryCursor


def _many(cur, sql, rows):
    for i in range(0, len(rows), BATCH):
        cur.executemany(sql, rows[i:i + BATCH])


def ensure_indexes(db):
    with db.cursor() as cur:
        for s in SCHEMA:
            cur.execute(s)


def _upsert_offers(cur, rows):
    cols = ", ".join(OFFER_COLS)
    marks = ", ".join(["%s"] * len(OFFER_COLS))
    update = ", ".join(f"{c}=VALUES({c})" for c in OFFER_COLS if c not in ("id", "first_seen"))
    _many(cur, f"INSERT INTO offers ({cols}) VALUES ({marks}) ON DUPLICATE KEY UPDATE {update}", rows)


def offer_row(oid, o):
    return [oid, o["store"], o["url"], o["title"], o["price"], o.get("mrp"), 1 if o.get("in_stock", True) else 0, o.get("image") or "",
            o.get("brand"), o.get("category"), o.get("model_key"), o.get("group_id"), _json(o.get("specs") or {}),
            _json(o.get("history") or []), o.get("last_seen"), o.get("first_seen") or o.get("last_seen"), int(o.get("missed_runs") or 0)]


def write_store(db, store, offers, now, blocked, started=None, note="", complete=True):
    """See store_db.write_store: the same gate, the same aging, the same run record."""
    ensure_indexes(db)
    unique = {}
    for o in offers:
        oid = offer_id(store, o["url"])
        if oid not in unique or o["price"] < unique[oid]["price"]:
            unique[oid] = o
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM offers WHERE store=%s AND missed_runs<%s", (store, MISSED_LIMIT))
        previous = cur.fetchone()[0]
        ok, status = gate(len(unique), previous, blocked)
        if ok and not complete:
            ok, status = False, "partial"
        run = {"store": store, "started": started or now, "finished": now, "status": status, "fetched": len(unique),
               "written": 0, "previous_count": previous, "note": note}
        if unique and status != "failed":
            cur.execute("SELECT id, history FROM offers WHERE store=%s", (store,))
            existing = {r[0]: r[1] for r in cur.fetchall()}
            day = now.strftime("%Y-%m-%d")
            rows = []
            for oid, o in unique.items():
                old = json.loads(existing[oid]) if existing.get(oid) else []
                doc = dict(o, last_seen=now, first_seen=now, missed_runs=0,
                           history=_history(old, day, o["price"], o.get("in_stock", True)))
                rows.append(offer_row(oid, doc))
            _upsert_offers(cur, rows)
            run["written"] = len(rows)
        if ok:
            # Every offer this run saw now has last_seen = now, so "unseen" is everything older for this store.
            unseen = "store=%s AND (last_seen IS NULL OR last_seen<%s)"
            cur.execute(f"UPDATE offers SET missed_runs=missed_runs+1 WHERE {unseen}", (store, now))
            cur.execute(f"UPDATE offers SET in_stock=0 WHERE {unseen} AND missed_runs>=%s", (store, now, MISSED_LIMIT))
            cur.execute(f"DELETE FROM offers WHERE {unseen} AND last_seen<%s", (store, now, now - DELETE_AFTER))
        cur.execute("INSERT INTO scrape_runs (store, started, finished, status, fetched, written, previous_count, note) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (store, run["started"], now, status, run["fetched"], run["written"], previous, (note or "")[:255]))
    return run


def stale_stores(db, stores, now, hours):
    cutoff = now - timedelta(hours=hours)
    with db.cursor() as cur:
        out = []
        for s in stores:
            cur.execute("SELECT MAX(started) FROM scrape_runs WHERE store=%s AND status='ok'", (s,))
            last = cur.fetchone()[0]
            if not last or last < cutoff:
                out.append(s)
        return out


def read_offers(db):
    """Offers in the shape group.rollup expects (the same as a MongoDB document)."""
    with db.cursor() as cur:
        rows = _rows(cur, "SELECT id, store, url, title, price, mrp, in_stock, image, brand, category, group_id, specs, history, last_seen FROM offers")
    for r in rows:
        r["_id"] = r.pop("id")
        r["in_stock"] = bool(r["in_stock"])
        r["specs"] = json.loads(r["specs"]) if r["specs"] else {}
        r["history"] = json.loads(r["history"]) if r["history"] else []
    return rows


def read_benchmarks(db):
    with db.cursor() as cur:
        cur.execute("SELECT doc FROM benchmarks")
        return [json.loads(r[0]) for r in cur.fetchall()]


def product_row(r):
    return [_json(r.get(c)) if c in JSON_PRODUCT else (1 if r.get(c) else 0) if c == "any_stock" else r.get(c) for c in PRODUCT_COLS]


def write_products(db, rows):
    """Build the three product tables beside the live ones, then swap them in with one atomic RENAME."""
    ensure_indexes(db)
    with db.cursor() as cur:
        for t in ("products", "product_facets", "product_stores"):
            cur.execute(f"DROP TABLE IF EXISTS {t}_new")
            cur.execute(f"DROP TABLE IF EXISTS {t}_old")
            cur.execute(f"CREATE TABLE {t}_new LIKE {t}")
        _many(cur, f"INSERT INTO products_new ({', '.join(PRODUCT_COLS)}) VALUES ({', '.join(['%s'] * len(PRODUCT_COLS))})",
              [product_row(r) for r in rows])
        _many(cur, "INSERT INTO product_facets_new (group_id, k, v) VALUES (%s,%s,%s)",
              [[r["group_id"], str(k)[:32], str(v)[:120]] for r in rows for k, v in (r.get("facets") or {}).items() if v not in (None, "")])
        _many(cur, "INSERT IGNORE INTO product_stores_new (group_id, store) VALUES (%s,%s)",
              [[r["group_id"], s] for r in rows for s in r.get("stores") or []])
        cur.execute("RENAME TABLE products TO products_old, products_new TO products, product_facets TO product_facets_old, "
                    "product_facets_new TO product_facets, product_stores TO product_stores_old, product_stores_new TO product_stores")
        for t in ("products", "product_facets", "product_stores"):
            cur.execute(f"DROP TABLE IF EXISTS {t}_old")


def size_bytes(db):
    with db.cursor() as cur:
        cur.execute("SELECT COALESCE(SUM(data_length + index_length), 0) FROM information_schema.TABLES WHERE table_schema = DATABASE()")
        return int(cur.fetchone()[0])


def trim_history(db, keep=30):
    with db.cursor() as cur:
        cur.execute("SELECT id, history FROM offers")
        rows = [(json.dumps(json.loads(h)[-keep:], separators=(",", ":")), i) for i, h in cur.fetchall() if h and len(json.loads(h)) > keep]
        _many(cur, "UPDATE offers SET history=%s WHERE id=%s", rows)


def recategorize_offers(db, now):
    """Apply the current category rules to every stored offer, so a rule fix reaches the site at the next roll-up
    instead of store by store. Offers that are no longer PC products are removed. A part whose id changes keeps its
    old address working: the site sends it on to the new one."""
    with db.cursor() as cur:
        cur.execute("SELECT id, title, category, group_id FROM offers")
        rows = cur.fetchall()
        changed, gone, moved = [], [], {}
        for oid, title, cat, gid in rows:
            r = recategorize(title, cat, gid)
            if r is None:
                gone.append((oid,))
            elif r != (cat, gid):
                changed.append((r[0], r[1], oid))
                if r[1] != gid:
                    moved[gid] = r[1]
        _many(cur, "UPDATE offers SET category=%s, group_id=%s WHERE id=%s", changed)
        _many(cur, "DELETE FROM offers WHERE id=%s", gone)
        _many(cur, "REPLACE INTO group_redirects (old_id, group_id, created) VALUES (%s,%s,%s)",
              [(old, new, now) for old, new in moved.items() if old and new and old != new])
        # an address that was sent on and is now a product again needs no redirect
        cur.execute("DELETE r FROM group_redirects r JOIN offers o ON o.group_id = r.old_id")
    return {"recategorized": len(changed), "removed": len(gone), "redirects": len(moved)}


def write_rollup(db, now):
    """See store_db.write_rollup: rebuild the products from current offers; keep the old ones if there are none."""
    ensure_indexes(db)
    try:
        benchmarks = build_lookup(read_benchmarks(db))
    except Exception:
        benchmarks = None
    fixed = recategorize_offers(db, now)
    rows = rollup(read_offers(db), now, benchmarks)
    out = {"products": len(rows), "skipped": False, "bytes": None, "trimmed": False, **fixed}
    if not rows:
        out["skipped"] = True
        return out
    write_products(db, rows)
    try:
        out["bytes"] = size_bytes(db)
        if out["bytes"] > SIZE_BUDGET:
            trim_history(db)
            out["trimmed"] = True
    except Exception:
        pass
    return out
