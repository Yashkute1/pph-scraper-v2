"""Ask Amazon's API again about stored Amazon offers before their price is a day old.

A price is shown for 24 hours after the API confirmed it (pph/group.py). The scrape only meets some products each run, so
the server asks about every other one itself, starting at half a day. An offer the API returns without a usable price
loses its confirmation and is asked about again half a day later. Nothing here touches the scrape's own bookkeeping
(last_seen, missed_runs), which the sanity gate counts on. Needs MySQL."""
import time
from datetime import timedelta

from pph.amazon_api import MAX_ASINS, MISSING_MIN_ITEMS, ApiStop, apply, asin_of, classify, image_of
from pph.group import AMAZON
from pph.sql_db import _rows, _time

AGE = timedelta(hours=12)
AGAIN = timedelta(hours=1)        # when an answer looks broken, ask about the same offers again this much later


def due(db, now):
    """Offers to ask about: the confirmed price closest to expiring first, then those with none."""
    with db.cursor() as cur:
        return _rows(cur, "SELECT id, url, price, mrp, in_stock FROM offers WHERE store=%s AND (price_at IS NULL OR price_at<%s) "
                          "AND (api_tried IS NULL OR api_tried<%s) ORDER BY price_at IS NULL, price_at, api_tried, url",
                     (AMAZON, now - AGE, now - AGE))


def refresh(db, api, now, deadline=None, clock=time.monotonic):
    """Returns {"asked", "priced", "blanked", "note"}; asked counts distinct ASINs, the others offers."""
    by_asin = {}
    for r in due(db, now):
        a = asin_of(r["url"])
        if a:
            by_asin.setdefault(a, []).append(r)
    asins = list(by_asin)
    asked = priced = judged = empty = 0
    note, unpriced = "", []
    for i in range(0, len(asins), MAX_ASINS):
        if deadline is not None and clock() >= deadline:
            note = "time limit"
            break
        batch = asins[i:i + MAX_ASINS]
        try:
            items = api.get_items(batch)
        except ApiStop as e:
            note = str(e)
            break
        asked += len(batch)
        for a in batch:
            item = items.get(a)
            try:
                kind, price = classify(item) if item else ("absent", None)
            except Exception:
                continue                                  # one malformed item must not cost the others
            judged += 1
            empty += kind in ("absent", "missing")
            for r in by_asin[a]:
                new = apply({**r, "in_stock": bool(r["in_stock"])}, kind, price, image_of(item), now) if item else {}
                if not new.get("price_at"):
                    unpriced.append(r["id"])
                    continue
                with db.cursor() as cur:
                    cur.execute("UPDATE offers SET price=%s, mrp=%s, in_stock=%s, image=%s, price_at=%s, api_tried=%s WHERE id=%s",
                                (new["price"], new["mrp"], 1 if new["in_stock"] else 0, new["image"], _time(new["price_at"]), now, r["id"]))
                priced += 1
    # Most answers holding no offer at all means the API is broken, not that everything stopped being sold. Nothing is
    # blanked (a price still expires at a day old); these go to the back of the queue for a while.
    if judged >= MISSING_MIN_ITEMS and empty * 2 > judged:
        for oid in unpriced:
            with db.cursor() as cur:
                cur.execute("UPDATE offers SET api_tried=%s WHERE id=%s", (now - AGE + AGAIN, oid))
        ignored = f"blanks ignored: {empty} of {judged} without offers"
        return {"asked": asked, "priced": priced, "blanked": 0, "note": "; ".join(x for x in (note, ignored) if x)}
    for oid in unpriced:
        with db.cursor() as cur:
            cur.execute("UPDATE offers SET in_stock=0, price_at=NULL, api_tried=%s WHERE id=%s", (now, oid))
    return {"asked": asked, "priced": priced, "blanked": len(unpriced), "note": note}
