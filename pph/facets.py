"""Filter values for the website's listing pages, read from the title and the compatibility specs. Pure.

Values are short display strings ("RTX 5060 Ti", "16 GB"). A value that cannot be read is left out, never guessed."""
import re

from ._rules import MB_CHIPSETS

_GPU = re.compile(r"\b(rtx|gtx|gt|rx|arc)[\s-]*([a-z]?\d{3,4})\b(?:[\s-]*(ti|super|xtx|xt)\b)?(?:[\s-]*(super)\b)?", re.I)
_GB = re.compile(r"\b(\d{1,3})\s*gb\b", re.I)
_CAP = re.compile(r"\b(\d{1,4})\s*(tb|gb)\b", re.I)
_INCH = re.compile(r"\b(\d{2}(?:\.\d)?)\s*(?:\"|”|''|-?\s*inch(?:es)?\b)", re.I)
_HZ = re.compile(r"\b(\d{2,3})\s*hz\b", re.I)
_RATING = re.compile(r"80\s*(?:\+|plus)\s*(bronze|silver|gold|platinum|titanium|white)", re.I)
_FAMILY = {"rtx": "RTX", "gtx": "GTX", "gt": "GT", "rx": "RX", "arc": "Arc"}
_SUFFIX = {"ti": "Ti", "super": "Super", "xt": "XT", "xtx": "XTX"}
_BOARD = re.compile(r"\b([ABXZHQW]\d{3}E?|WRX\d0|TRX\d0)(?:[MIN])?(?![A-Z0-9])", re.I)
_SOCKET = re.compile(r"\b(?:LGA\s?-?\s?(\d{4})|(AM[45])|socket\s(\d{4}))\b", re.I)
_PSU_MODEL = re.compile(r"(?<![\d.])(\d{3,4})(?![\d.]|\s?(?:mm|rpm|hz|gb|tb))", re.I)
_PSU_SIZES = set(range(300, 1001, 50)) | {1050, 1100, 1200, 1250, 1300, 1350, 1500, 1600, 2000}
_MIXED_RAM = {"LGA1700"}          # these boards exist in both DDR4 and DDR5 versions, so the chipset cannot tell us
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
    t, specs, out = re.sub(r"[™®©]", " ", str(title or "")), dict(specs or {}), {}
    if category == "Motherboard" and not specs.get("chipset"):
        m = _BOARD.search(t)
        ref = MB_CHIPSETS.get(m.group(1).upper()) if m else None
        if ref:
            specs["chipset"] = m.group(1).upper()
            specs.setdefault("socket", ref[0])
            if re.search(r"ddr[45]", t, re.I) is None:
                specs.pop("ram_type", None)
                if ref[0] not in _MIXED_RAM:
                    specs["ram_type"] = ref[1]
    if category == "Processor/CPU" and not specs.get("socket"):
        m = _SOCKET.search(t)
        if m:
            specs["socket"] = m.group(2).upper() if m.group(2) else "LGA" + (m.group(1) or m.group(3))
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
        watts = specs.get("wattage") or next((int(n) for n in _PSU_MODEL.findall(t) if int(n) in _PSU_SIZES), None)
        if watts:
            out["wattage"] = f"{watts} W"
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
