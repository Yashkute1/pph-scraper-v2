"""Join product pages that are the same product listed differently by different stores. Pure, no I/O.

Group ids come from the words in each title, so one store's "Crucial P3 Plus 1TB M.2 2280 SSD (CT1000P3PSSD8)" and
another's "CRUCIAL P3 PLUS 1TB NVME GEN 4.0 INTERNAL SSD (CT1000P3PSSD8)" get two pages. What they share is the
manufacturer's part code, and that is what joins them here, with checks that keep different products apart."""
import re
from collections import defaultdict
from statistics import median

_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")    # slashes separate spec lists ("265k/32gb/1tb"), not codes
# Sizes, speeds, generations and platform names: they appear in many different products' titles.
_NOISE = re.compile(r"^(\d+(gb|tb|mb|mm|cm|hz|mhz|ghz|w|v|a|ah|mah|p|k|ms|inch|in|th|nd|rd|st|nm|rpm|pcs|ft|m|dpi|fps|mp|wh|whr|mt|mts|gbps|mbps|kbps)"
                    r"|\d+(x\d+)+[a-z]*|\d{4,5}[a-z]{0,3}|lga\d+|am\d|fm\d\+?|(i\d)+|(r\d)+|ddr\d+|lpddr\d+|gddr\d+x?|pcie\d+|gen\d+x?\d*|usb\d+[a-z]?|wifi\d+e?|ps\d|rtx\d+[a-z]*|gtx\d+[a-z]*"
                    r"|rx\d+[a-z]*|win\d+|windows\d+|cl\d+|[a-z]\d{1,4}|\d{1,4}[a-z]{1,3}|[a-z]\d{1,3}[a-z]?|[a-z]{2}\d{1,2}[a-z]?)$")
# Processor, card and memory names written like codes ("ultra9-290hx", "ci7-13650hx", "rtx5070ti"): specs, not part numbers.
_SPEC = re.compile(r"^(ultra|ci|core|ryzen|rtx|gtx|rx|arc|ddr|lpddr|gddr|win|intel|amd|nvidia|geforce|radeon)\d"
                   r"|^r\d{8}$|^eta")    # Indian BIS (R-41211141) and ETA certificate numbers cover a maker's whole range
# The chip a card, processor or board is built on. Two pages naming different chips are different products whatever
# part codes they share (a seller's code can cover a whole range).
_CHIP = {
    "Graphics Card": re.compile(r"\b(?:rtx|gtx|rx|arc)?\s?([a-z]?\d{3,4})\s?(ti super|ti|super|xtx|xt|gre)?\b"),
    "Processor/CPU": re.compile(r"\b(\d{4,5}(?:x3d|kf|ks|k|f|x|g|t)?)\b"),
    "Motherboard": re.compile(r"\b([abhxzq]\d{3}e?)(?:m|i)?\b"),
}
# Words inside a "code" that show it is a spec run together, not a part number ("6gb-rtx4050", "3770-processor").
# Checked per hyphen-separated part, so a real code that happens to contain "ssd" ("ct1000p3pssd8") is kept.
_WORDY = re.compile(r"(processor|gaming|series|edition|inch|black|white|generation|graphics|wireless|monitor|laptop|desktop"
                    r"|\d+(gb|tb|ghz|mhz)|(rtx|gtx|win)\d*|ssd|hdd|ram)$")
_CAPACITY = re.compile(r"\b(\d{2,4}|[1-8])\s?(gb|tb)\b")
# Card lines: two cards on the same chip from one brand are different products when their lines differ.
_LINES = ("aero", "eagle", "windforce", "aorus elite", "aorus master", "xtreme", "master", "elite", "gaming oc", "ventus", "suprim",
          "inspire", "shadow", "gaming x", "trio", "tuf", "strix", "prime", "dual", "proart", "twin edge", "amp", "trinity",
          "solid", "ichill", "x3", "pulse", "nitro", "hellhound", "red devil", "steel legend", "challenger", "phantom gaming",
          "fighter", "ex", "white", "low profile", "sff")
_CONSOLES = {"PlayStation", "Xbox", "Nintendo"}
_SCREEN = re.compile(r"\b(1[0-9]|2[0-9]|3[0-9])(?:\.\d)?\s?(?:inch|in)\b")
_CPU = re.compile(r"\b(?:c?i[3579]|ultra\s?[3579]|r[3579]|ryzen\s?[3579])\s?(\d{3,5}[a-z]{0,2})\b")
STRONG = 8              # a code this long is a manufacturer part number ("ct1000p3pssd8", "ls27b610eqwxxl")
SHORT = 6               # a shorter model name ("vs450l", "rm850i") also needs prices that agree
SHORT_PRICE = 1.15
MAX_PRICE = 1.5         # pages further apart than this are different products whatever their titles share


def codes(title):
    """Part codes in a title, hyphens removed: "CB-GK-16" -> "cbgk16"."""
    out = set()
    for tok in _TOKEN.findall(str(title or "").lower()):
        c = re.sub(r"[-/]", "", tok)
        digits, letters = sum(ch.isdigit() for ch in c), sum(ch.isalpha() for ch in c)
        if len(c) >= SHORT and digits >= 2 and letters >= 2 and not _NOISE.match(c) and not _SPEC.match(c) \
                and not any(_WORDY.match(part) for part in tok.split("-")):
            out.add(c)
    return out


def _distinct(cs):
    """Codes that are not part of another code: "ls34c650tawxx" and "ls34c650tawxxl" count once."""
    cs = sorted(cs, key=len, reverse=True)
    keep = []
    for c in cs:
        if not any(c in k for k in keep):
            keep.append(c)
    return keep


# Laptops and PCs share processor, card and memory names across many configurations; only a full SKU joins them.
_CONFIGURED = {"Gaming Laptop", "Desktop PC"}
SKU = 10


def merge_map(offers):
    """{group_id: kept group_id} for pages that are the same product. offers: dicts with group_id, title, category,
    brand and price. A page whose own listings carry two unrelated codes is mixed already and joins nothing."""
    info = defaultdict(lambda: {"codes": defaultdict(int), "prices": [], "cat": None, "brand": None, "n": 0, "chips": set(),
                                 "caps": set(), "lines": set(), "bundle": set()})
    for o in offers:
        g = o.get("group_id")
        if not g or not o.get("price"):
            continue
        i = info[g]
        i["n"] += 1
        i["prices"].append(o["price"])
        i["cat"] = i["cat"] or o.get("category")
        b = o.get("brand") or "Generic"
        if b != "Generic":
            i["brand"] = b
        for c in codes(o.get("title")):
            i["codes"][c] += 1
        low = " " + re.sub(r"[^a-z0-9]+", " ", str(o.get("title") or "").lower()) + " "
        i["caps"] |= {_gb(n, u) for n, u in _CAPACITY.findall(low)}
        if o.get("category") in _CONFIGURED:
            i["caps"] |= {f"{n}in" for n in _SCREEN.findall(low)} | {f"cpu{c}" for c in _CPU.findall(low)}
        if o.get("category") == "Graphics Card":
            i["lines"] |= {w for w in _LINES if f" {w} " in low}
        if o.get("category") in _CONSOLES:
            i["bundle"].add(_bundle(low))
        rx = _CHIP.get(o.get("category"))
        if rx:
            i["chips"] |= {"".join(m).replace(" ", "") for m in rx.findall(str(o.get("title") or "").lower())
                           if not re.fullmatch(r"(19|20)\d\d|\d{3}", m[0] if isinstance(m, tuple) else m)}
    by_code = defaultdict(list)
    for g, i in info.items():
        cs = _distinct(i["codes"])
        if len(cs) > 1 and len({c for c in cs if len(c) >= SHORT}) > 1 and i["n"] > 1:
            # more than one listing and more than one code: either a mixed page or a code plus a model name
            # ("rm850i" and "cp9020083"). Use only codes most of its listings agree on.
            cs = [c for c in cs if i["codes"][c] * 2 > i["n"]] or []
        i["mid"] = median(i["prices"])
        for c in cs:
            if i["cat"] in _CONFIGURED and (len(c) < SKU or sum(ch.isalpha() for ch in c) < 3):
                continue
            by_code[(i["cat"], c)].append(g)

    parent = {}

    def find(g):
        while parent.get(g, g) != g:
            g = parent[g]
        return g

    members = defaultdict(set)
    for (cat, code), groups in sorted(by_code.items()):
        if len(groups) < 2:
            continue
        groups = sorted(groups)
        for g in groups[1:]:
            a, b = find(groups[0]), find(g)
            if a == b:
                continue
            ia, ib = info[groups[0]], info[g]
            if ia["brand"] and ib["brand"] and ia["brand"].lower() != ib["brand"].lower():
                continue
            lo, hi = sorted([ia["mid"], ib["mid"]])
            limit = MAX_PRICE if len(code) >= STRONG else SHORT_PRICE
            if hi > lo * limit:
                continue
            ca = set().union(*(info[x]["chips"] for x in (members[a] or {a})))
            cb = set().union(*(info[x]["chips"] for x in (members[b] or {b})))
            if ca and cb and not (ca & cb):
                continue
            if _conflict(info, members[a] or {a}, members[b] or {b}, exact=cat in _CONFIGURED):
                continue
            # the whole joined page must stay within the price limit, so a chain cannot drift to another product
            ga = members[a] or {a}
            gb = members[b] or {b}
            mids = [info[x]["mid"] for x in ga | gb]
            if max(mids) > min(mids) * MAX_PRICE:
                continue
            keep, drop = sorted([a, b], key=_keep_order)
            parent[drop] = keep
            members[keep] = ga | gb
            members.pop(drop, None)
    return {g: find(g) for g in parent if find(g) != g}


def _gb(n, unit):
    return int(n) * (1024 if unit == "tb" else 1)


def _bundle(low):
    """What a console comes with besides itself ("call of duty", "fortnite"); Astro's Playroom is on every PS5."""
    low = re.sub(r"astro s playroom|astros playroom|astro playroom", " ", low)
    m = re.search(r" with (?!\d)(.+?)(?: full game| voucher|$)", low) or re.search(r" ([a-z0-9 ]{3,30}?) bundle ", low)
    words = [w for w in (m.group(1).split() if m else []) if w not in {"the", "and", "yes", "game", "full", "slim", "console"}]
    return " ".join(words[:3])


def _conflict(info, ga, gb, exact=False):
    """Two sets of pages that read as different products: different capacities (8 GB vs 16 GB card, 825 GB vs 1 TB
    console), different card lines (Aero vs Gaming OC), or different console bundles."""
    def union(key, gs):
        return set().union(*(info[x][key] for x in gs))
    ca, cb = union("caps", ga), union("caps", gb)
    ka, kb = {x for x in ca if isinstance(x, int)}, {x for x in cb if isinstance(x, int)}
    if ka and kb and not (ka & kb):
        return True
    if exact and ca and cb:
        # a PC or laptop: one title may leave a spec out, but the sizes one lists must all be in the other, and the
        # processors and screens named must agree
        sa, sb = {x for x in ca if isinstance(x, int)}, {x for x in cb if isinstance(x, int)}
        if sa and sb and not (sa <= sb or sb <= sa):
            return True
        for kind in ("cpu", "in"):
            xa = {x for x in ca if isinstance(x, str) and (x.startswith(kind) if kind == "cpu" else x.endswith(kind))}
            xb = {x for x in cb if isinstance(x, str) and (x.startswith(kind) if kind == "cpu" else x.endswith(kind))}
            if xa and xb and not (xa & xb):
                return True
    la, lb = union("lines", ga), union("lines", gb)
    if la and lb and not (la & lb):
        return True
    ba, bb = union("bundle", ga), union("bundle", gb)
    if (ba or bb) and ba != bb:
        return True
    return False


def _keep_order(g):
    """The page that stays: one with a brand in its id before a generic one, then the shorter id, then alphabetical,
    so the same set of pages always keeps the same address."""
    return ("generic" in g, len(g), g)
