"""Filter values for the website's listing pages, read from the title and the compatibility specs. Pure.

Values are short display strings ("RTX 5060 Ti", "16 GB"). A value that cannot be read is left out, never guessed."""
import re

_GPU = re.compile(r"\b(rtx|gtx|gt|rx|arc)[\s-]*([a-z]?\d{3,4})\b(?:[\s-]*(ti|super|xtx|xt)\b)?(?:[\s-]*(super)\b)?", re.I)
_GB = re.compile(r"\b(\d{1,3})\s*gb\b", re.I)
_CAP = re.compile(r"\b(\d{1,4})\s*(tb|gb)\b", re.I)
_INCH = re.compile(r"\b(\d{2}(?:\.\d)?)\s*(?:\"|”|''|-?\s*inch(?:es)?\b)", re.I)
_HZ = re.compile(r"\b(\d{2,3})\s*hz\b", re.I)
_RATING = re.compile(r"80\s*(?:\+|plus)\s*(bronze|silver|gold|platinum|titanium|white)", re.I)
_FAMILY = {"rtx": "RTX", "gtx": "GTX", "gt": "GT", "rx": "RX", "arc": "Arc"}
_SUFFIX = {"ti": "Ti", "super": "Super", "xt": "XT", "xtx": "XTX"}
_COPY = {"Motherboard": ("socket", "chipset", "form_factor", "ram_type"), "Processor/CPU": ("socket",), "Memory/RAM": ("ram_type",)}


def _cpu_series(t):
    m = re.search(r"\bryzen\s*([3579])\b", t, re.I)
    if m:
        return "Ryzen " + m.group(1)
    if re.search(r"threadripper", t, re.I):
        return "Threadripper"
    m = re.search(r"\bcore\s*ultra\s*([3579])\b", t, re.I)
    if m:
        return "Core Ultra " + m.group(1)
    m = re.search(r"\bi([3579])[\s-]*\d{3,5}", t, re.I)
    if m:
        return "Core i" + m.group(1)
    return None


def facets_of(title, category, specs):
    t, specs, out = str(title or ""), specs or {}, {}
    if category == "Graphics Card":
        m = _GPU.search(t)
        if m:
            words = [_FAMILY[m.group(1).lower()], m.group(2).upper()] + [_SUFFIX[s.lower()] for s in m.groups()[2:] if s]
            out["series"] = " ".join(words)
        gb = [int(x) for x in _GB.findall(t) if int(x) <= 48]
        if gb:
            out["memory"] = f"{gb[0]} GB"
    elif category == "Processor/CPU":
        s = _cpu_series(t)
        if s:
            out["series"] = s
    elif category in ("Memory/RAM", "SSD", "HDD", "Pen Drive"):
        m = _CAP.search(t)
        if m:
            out["capacity"] = f"{int(m.group(1))} {m.group(2).upper()}"
    elif category == "Power Supply":
        if specs.get("wattage"):
            out["wattage"] = f"{specs['wattage']} W"
        m = _RATING.search(t)
        if m:
            out["rating"] = "80+ " + m.group(1).capitalize()
    elif category == "Monitor":
        m = _INCH.search(t)
        if m and 10 <= float(m.group(1)) <= 60:
            out["size"] = f"{round(float(m.group(1)))} inch"
        m = _HZ.search(t)
        if m:
            out["refresh"] = f"{int(m.group(1))} Hz"
    for key in _COPY.get(category, ()):
        if specs.get(key):
            out[key] = str(specs[key])
    return out
