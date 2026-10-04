"""Match a product to its UserBenchmark row (the `benchmarks` collection). Pure, no I/O.

CPUs and graphics cards are matched exactly on a model key taken from both sides ("rtx5060ti", "ryzen55600x"),
so a Ti card can never pick up the base card's score. Drives and memory have messier names and are matched by
the benchmark row's key appearing inside the title, longest key first."""
import re

BUCKET = {"Processor/CPU": "CPU", "Graphics Card": "GPU", "SSD": "SSD", "Memory/RAM": "RAM", "HDD": "HDD", "Pen Drive": "USB"}
EXACT = {"CPU", "GPU"}
_GPU = re.compile(r"\b(rtx|gtx|rx|arc)[\s-]*([a-z]?\d{3,4})")
_INTEL = re.compile(r"\bi([3579])[\s-]*(\d{3,5}[a-z]{0,2})\b")
_RYZEN = re.compile(r"\bryzen\s*([3579])\s*(\d{3,4}[a-z0-9]{0,3})\b")
_FILLER = re.compile(r"\b(m\.?2|nvme|ssd|hdd|ddr\d|sata|pcie|gen\d|usb|\d+\s*(tb|gb|mhz|cl\d+))\b")
_CAP = re.compile(r"\b(\d+)\s*(tb|gb)\b")


def _alnum(s):
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


def _gpu_suffix(text):
    if re.search(r"\bxtx\b", text):
        return "xtx"
    if re.search(r"\bxt\b", text):
        return "xt"
    if re.search(r"\bsuper\b|\bs\b", text):
        return "super"
    if re.search(r"\bti\b", text):
        return "ti"
    return ""


def keys_for(bucket, text, title=False):
    """Candidate keys for a benchmark model name, or for a product title when `title` is true."""
    t = str(text or "").lower()
    keys = set()
    if bucket == "GPU":
        g = _GPU.search(t)
        if g:
            tail = t[g.end():g.end() + 12] if title else t      # in a title only words right after the number count
            keys.add(_alnum(g.group(1) + g.group(2) + _gpu_suffix(tail)))
    elif bucket == "CPU":
        i = _INTEL.search(t)
        if i:
            keys.add("i" + i.group(1) + i.group(2))
        r = _RYZEN.search(t)
        if r:
            keys.add("ryzen" + r.group(1) + r.group(2))
    else:
        full = _alnum(t)
        if len(full) >= 5:
            keys.add(full)
        cap = _CAP.search(t)
        series = "".join([w for w in re.sub(r"[^a-z0-9]+", " ", _FILLER.sub(" ", t)).split() if len(w) >= 3][:2])
        if series and cap:
            keys.add(_alnum(series + cap.group(0)))
    return {k for k in keys if len(k) >= 5}


def build_lookup(docs):
    """{bucket: [(key, record)] longest key first}. With several rows per key the one with most samples wins."""
    by_bucket, totals = {}, {}
    for d in docs:
        bucket, model, score = d.get("bucket"), d.get("model"), d.get("score")
        if not bucket:
            continue
        by_bucket.setdefault(bucket, {})
        if not model or not isinstance(score, (int, float)):
            continue
        totals[bucket] = totals.get(bucket, 0) + 1
        for k in keys_for(bucket, model):
            prev = by_bucket[bucket].get(k)
            if prev is None or (d.get("samples") or 0) > (prev.get("samples") or 0):
                by_bucket[bucket][k] = d
    out = {}
    for bucket, keyed in by_bucket.items():
        out[bucket] = [(k, {"score": r["score"], "percentile": r.get("percentile"), "rank": r.get("rank"),
                            "total": totals[bucket], "model": r["model"], "bucket": bucket})
                       for k, r in sorted(keyed.items(), key=lambda kv: (-len(kv[0]), kv[0]))]
    return out


def match(title, category, lookup):
    bucket = BUCKET.get(category)
    if not bucket or not lookup or not lookup.get(bucket) or not title:
        return None
    if bucket in EXACT:
        mine = keys_for(bucket, title, title=True)
        return next((rec for key, rec in lookup[bucket] if key in mine), None)
    t = _alnum(title)
    return next((rec for key, rec in lookup[bucket] if key in t), None)
