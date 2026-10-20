"""Turn a raw scraped listing into a clean offer: price, brand, category, model key, group id.

Pure functions, no I/O. The category rules in ``type_of`` and the data in
``_rules`` were ported from the retired Node scraper and are pinned by a golden
parity test (tests/test_normalize.py) - change them only with a test.
"""
import re
from functools import lru_cache
from urllib.parse import urlsplit, parse_qs

from ._rules import (BRANDS, BRAND_CANON, TYPE_RULES, PRICE_CAP, ACCESSORY_KW, KEY_STOP, KEY_VARIANT, KEY_AIB,
                     MB_CHIPSETS, M2_BY_TIER, JUNK_TITLE, NON_PC, GAME_TITLES, JUNK)

A = re.ASCII
_WS = re.compile(r"\s+")            # unicode-aware on purpose: collapses nbsp etc. like JS \s
_WSA = re.compile(r"\s+", A)
_DOTS = re.compile(r"\.{3,}|\u2026")
_NONALNUM = re.compile(r"[^a-z0-9]+")
_PRICE = re.compile(r"[0-9]{1,3}(?:[,\s][0-9]{2,3})+(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?")


@lru_cache(maxsize=None)
def _c(p, f):
    return re.compile(p, f | A)


def _s(p, s, f=0):
    return _c(p, f).search(s) is not None


def _round(n):
    return int(n + 0.5)


def parse_price(raw):
    """First price-like number in ``raw`` as whole rupees; 0 when there is none."""
    if raw is None or isinstance(raw, bool):
        return 0
    if isinstance(raw, (int, float)):
        return _round(raw) if raw == raw and abs(raw) != float("inf") else 0
    m = _PRICE.search(str(raw).strip())
    if not m:
        return 0
    n = float(re.sub(r"[,\s]", "", m.group(0)))
    if n in (99999, 999999):         # store "price unavailable" sentinels
        return 0
    return _round(n)


def _title_case(s):
    return re.sub(r"\b\w", lambda m: m.group(0).upper(), str(s).lower(), flags=A)


def brand_of(title):
    """Canonical brand found in ``title`` ('' when none)."""
    t = " " + _WSA.sub(" ", re.sub(r"[^A-Z0-9. ]+", " ", str(title or "").upper())) + " "
    for b in BRANDS:
        if " " + b + " " in t:
            return BRAND_CANON.get(b) or _title_case(b)
    return ""


def buildScore(t):
    n = 0
    if _s(r"""(ryzen|core\s+i[3579]|core\s+ultra|threadripper|pentium|celeron|\bxeon\b|\bultra\s?[3579]\s?\d{3}k?\b|\bc?i[3579]-?\d{4,5}[a-z]{0,2}\b)""", t): n += 1
    if _s(r"""(\brtx\s?\d|\bgtx\s?\d|geforce|radeon|\brx\s?[5-9]\d{3}|arc\s+a\d)""", t): n += 1
    if _s(r"""(\bddr[45]\b|\d+\s?gb\s+ram|\bram\b)""", t): n += 1
    if _s(r"""(\bssd\b|\bnvme\b|\bhdd\b|\d+\s?tb\b)""", t): n += 1
    return n



# Flipkart appends its own spec sheet to some titles: "... DDR2 2 GB NVIDIA Chipset 0 bit 0 MHz Graphics Card" or
# "... 2 GB Servers Black SATA Internal Solid State Drive (SSD)". Sellers file drones, VR boxes and gimbals there, so
# the tail says nothing about what the item is. It is cut off and the head decides.
_FK_GPU = re.compile(r"\s+(?:g?ddr\d\w*\s+)?[\d.]+\s*[gm]b\s+[\w/&-]+(?:\s+[\w/&-]+)?\s+chipset\s+\d+\s*bit\s+[\d.]+\s*mhz\s+graphics card\b.*$")
_FK_SSD = re.compile(r"\s+[\d.]+\s*(?:gb|tb)\s+servers?\s+\w+\s+(?:sata|m\.2|pcie|nvme)\s+internal solid state drive\b.*$")
_JUNK_HEAD = (r"\bdrones?\b|\bgimbals?\b|stabili[sz]er|\bairplane\b|fighter jet|\brc\b|remote control (car|plane|toy)|\btoy\b|"
              r"\bquadcopter\b|selfie stick|\btripod\b|phone holder|\bfpv\b")
_RAM_SIZE = r"\b\d{1,3}\s?gb\s?\(\d+\s?x\s?\d+\s?gb\)|\b\d{1,3}\s?gb\b.{0,14}\b(ram|ddr\d|memory)\b|\b(ram|ddr\d)\b.{0,6}\b\d{1,3}\s?gb\b|\b\d{1,3}\s?gb\s?\/|\(\s?\d{1,3}\s?gb\b"
_DISK_SIZE = r"\b\d+\s?(gb|tb)\b.{0,16}\b(ssd|hdd|nvme|m\.2|hard dis[kc]|storage)\b|\b(ssd|hdd|nvme)\b.{0,6}\b\d+\s?(gb|tb)\b"
_CPU = (r"\b(ryzen\s?[3579]|core\s?2\s?(duo|quad)|\bdual core\b|\bquad core\b|\b(processor|cpu)\s+i[3579]\b|core[\s-]?(\(tm\)|™)?\s?i[3579]|\ba(4|6|8|10|12)[- ]\d{4}|core\s?ultra|\bultra\s?[3579]\s?\d{3}|xeon|threadripper|pentium|celeron|athlon|"
        r"\bc?i[3579][- ]?\d{3,5}[a-z]{0,3}\b|\bi[3579]\s?\d{1,2}(th|nd|rd|st)\s?gen)")
_SYSTEM = (r"gaming (pc|computer|desktop|rig)|desktop (pc|computer|tower|cpu)|\bpc build\b|custom pc|computer system|tower pc|mini pc|"
           r"micro pc|\bnuc\b|thinkcentre|optiplex|prodesk|elitedesk|veriton|all[- ]?in[- ]?one|\baio pc\b|\bpc\b.{0,12}\b(kit|combo|setup)\b|"
           r"combo kit|motherboard combo|\bcombo\b.{0,40}(core|i[3579]|ryzen|processor|cpu)|(core|i[3579]|ryzen|processor|cpu).{0,40}\bcombo\b|"
           r"assembled|pre-?assembled|pre-?built|full (pc )?setup|complete (pc|computer|setup|system)|workstation pc")
_PART_HEAD = (r"graphics card|graphic card|\bgpu\b|\bssd\b|\bnvme\b|\bram\b|memory|power supply|\bpsu\b|\bsmps\b|cabinet|\bcase\b|chassis|"
              r"cooler|\bfans?\b|monitor|keyboard|mouse|\bups\b|speaker|headset|webcam|hard (disk|drive)|\bhdd\b|motherboard")
_LAPTOP = r"\b(laptops?|notebooks?|chromebook|macbook)\b"
_MOBILE_CPU = (r"\br[3579]-\d{3}\b|\b[12]\d{2}(hx|h|u|v)\b|\b(c?i[3579][- ]?)?1[0-4]\d{2,3}\s?(hx|hs|h|u|p)\b|\bc?i[3579]-?\d{4,5}(hx|hs|h|u|p)\b|ryzen\s(ai\s)?[3579]\s\d{3}(?![\d/])\b|\b\d{4}h[qk]\b|\b(r[3579][- ]?)?[5-9]\d{3}(hx|hs|h|u)\b|\bultra\s?[3579][- ]?\d{3}(hx|h|v|u)\b|"
               r"\bcore\s?[3579][- ]?\d{3}[uh]\b|\b(ryzen ai|ai\s?[3579])\s?\d{3}\b|\b\d{3}hx\b")


_LAPTOP_MODELS = (r"\b(vivobook|zenbook|ideapad|thinkpad|thinkbook|yoga|legion|loq|nitro\s?v?|predator|helios|tuf (gaming )?[af]\d{2}|"
                  r"rog (zephyrus|strix g|flow)|strix g\d{2}|victus|omen (transcend|\d{2})|inspiron|\bxps\b|vostro|latitude|alienware m|aspire|swift|"
                  r"katana|cyborg|modern\s?\d{2}|prestige|stealth|raider|titan|vector|crosshair|sword|bravo|venture|thin (gf|a)\d{2}|gf63|gp\d{2}|gs\d{2}|"
                  r"galaxy book|macbook|surface (pro|laptop)|gram|zbook|probook|elitebook|envy|spectre|pavilion (plus|\d{2}|x360)|chromebook|"
                  r"dell g\d{2}|\bg1[56]\b|expertbook|creator|\bv1[456]\b)\b")


def _system(t):
    """A whole computer or a board + CPU + memory kit, not a single part."""
    if (_s(_LAPTOP, t) or _s(_LAPTOP_MODELS, t)) and not _s(r"all[- ]?in[- ]?one|\baio\b|desktop|tower|mini pc|\bnuc\b", t):
        return False
    if _s(_PART_HEAD, t[:40]) and not _s(_CPU, t[:40]) and not _s(r"gaming pc|desktop pc|custom pc|mini pc|\bcombo\b|\bkit\b", t[:40]):
        return False
    words = _s(_SYSTEM, t)
    ram, disk, cpu = _s(_RAM_SIZE, t), _s(_DISK_SIZE, t), _s(_CPU, t)
    # a part that says which computers it fits ("Desktop PC RAM", "Upgrade for Laptop, Desktop PC", "All in One PC's")
    if not cpu and _s(r"solid state|internal ssd|hard dis[kc] drive|\bu?dimm\b|so-?dimm|\b(pc|desktop|computer)\s+(ram|memory)\b|"
                      r"for (gaming |desktop )?(pc|computer|desktop|laptop)|all in one pc'?s|pc\d-\d{4,5}", t):
        return False
    kit = _s(r"motherboard|mainboard|\b[bhzq]\d{2,3}m?\b", t) and cpu and ram and _s(r"\bcombo\b|\bkit\b|assembled|\+|bundle", t)
    if _s(r"pre-?\s?built|custom pc|\bpc build\b|gaming pc|desktop pc|computer system", t) and ram and disk:
        return True
    whole = cpu and ram and (disk or _s(r"\binch screen\b|\d{2}\s?inch (screen|monitor|led)", t)) and _s(r"win(dows)?\s?1[01]|\bdos\b|ubuntu|linux|wi-?fi|\bhdmi\b|graphics|keyboard|\brtx\s?a?\d{4}|\brx\s?\d{4}|\bgtx\s?\d{3,4}|\b\d{4}\s?xt\b", t)
    lead = _s(r"gaming (pc|desktop|computer)|desktop (pc|computer|cpu|tower)|custom pc|mini pc|computer", t[:40])
    return bool(kit or (words and (ram or disk) and (cpu or lead)) or (words and cpu and lead) or whole)


# Console categories hold the consoles themselves and their official controllers; games go to Games and the rest
# (stands, covers, dust kits) to Gaming Accessories, wherever the general rules first put them.
_CONSOLE_ACC = re.compile(r"controller|dualsense|dualshock|joy-?con|gamepad|charging|charger|\bstand\b|cover|skin|sticker|\bcase\b|\bbag\b|"
                          r"headset|cable|\bfan\b|\bdock\b|wheel|joystick|\bgrip|thumb|remote|camera|\bvr\b|portal|plug|dust|mount|holder|"
                          r"\bfor (sony |the |your )?(ps[45]|playstation|xbox|nintendo|switch)|compatible|protector|screen guard|tempered|"
                          r"\bkit\b|\bssd\b(?!.{0,25}(console|all-?digital))|nvme|expansion card|memory card|battery|\bpad\b|pedal|yoke|cleaning", A)
_GAME_HINT = re.compile(r"\bgame\b(?!\s*(controller|pad|chair|stand|console|card))|\bgames\b(?!\s*console)|edition|\(ps[45]\)|\| ?ps[45]|"
                        r"\bpegi\b|\bdlc\b|digital (code|key)|\bkey\b|code in a box|\bupgrade\b|game (cd|disc|chip)|\bcd\b|\bdisc\b(?! (edition|drive))", A)


def _console(t):
    """'PlayStation' / 'Xbox' / 'Nintendo' when the listing is the console itself (a bundle counts), else ''.
    The console must lead the title, and accessory words only count before a bundle marker ("& charging station")."""
    head = re.sub(r"^\W*(new |latest |original |genuine |sony |microsoft |playstation sony |gaming console:\s*)+", "", t.strip())
    head = re.sub(r"\(?games? not included\)?", " ", head)
    bare = re.fullmatch(r"(nintendo switch( 2| oled| lite)?|playstation ?5( slim| pro)?|ps ?5( slim| pro)?|xbox series [xs])\W*", re.sub(r"\([^)]*\)", " ", head).strip())
    if bare:
        return 'Nintendo' if 'switch' in head else 'Xbox' if 'xbox' in head else 'PlayStation'
    cut = re.search(r"\s(&|\+|with|bundle|combo)\s", head)
    pre = head[:cut.start()] if cut else head
    if _CONSOLE_ACC.search(re.sub(r"\b(ssd|nvme)\b", " ", pre)) or _s(r"headphone|earphone|\bmic\b|microphone|speaker|\bmonitor\b|tv box|retro|emulator|game (stick|box)|"
                                       r"faceplate|shell|plate|replacement|\bjeu\b|console edition|game chip|game card only|"
                                       r"(?<!console )(?<!video )\bgames?\b(?! console)|blu-?ray|\bcd\b|delivery|download|disc drive|\bdrive\b(?! combo)", pre):
        return ''
    if re.match(r"(playstation ?(®|\(r\))?\s?5|ps ?5)\b", head) and _s(r"\bconsole\b|\bslim\b|digital|disc|\bcfi-?\d{4}|\bpro\b|\d+\s?(gb|tb)\b", head):
        return 'PlayStation'
    if re.match(r"(playstation ?4|ps ?4)\b", head) and _s(r"\bconsole\b|\bslim\b|\bpro\b.{0,20}\d+\s?(gb|tb)|\d+\s?(gb|tb)\b", head):
        return 'PlayStation'
    if re.match(r"xbox (series [xs]|one [sx]?)\b", head) and _s(r"\bconsole\b|\d+\s?(gb|tb)\b|all-?digital|disc edition", head):
        return 'Xbox'
    if re.match(r"(nintendo\s+)?(sw\s+)?switch( 2| oled| lite)?\b|nintendo switch", head) and head.startswith(("nintendo", "switch")) \
            and _s(r"\bconsole\b|oled|\blite\b|\d+\s?gb\b|bundle|joy-?con", head):
        return 'Nintendo'
    return ''


def type_of(title):
    """The site category for a listing title, or "Other" when it is not a PC product."""
    cat = _rules_console(title, _type_of(title))
    # A bare brand ("ZORBES", "Case Club") lands in the catch-all; it says nothing about what the product is.
    if cat == "Components" and len(re.findall(r"[a-z0-9]+", str(title).lower())) < 3:
        return "Other"
    # books about computers are not computers
    if re.search(r"comprehensive guide|\bpaperback\b|\bhardcover\b|\bkindle edition\b|\bebook\b|\bhandbook\b", str(title), re.I):
        return "Other"
    return cat


# Flipkart lists toys and gadgets with a made-up spec ending: "... 5.4 GHz sTR4 2 Core Processor Designed for Mobile" or
# "... AM1Socket ATX AMD 320 Chipset DDR2 Motherboard for Mobile". The ending says nothing; the start says what it is.
_FK_CPU = re.compile(r"\d+(\.\d+)? ghz \S+ \d+ core processor designed for (desktop|mobile|server|workstation|laptop)", A)
_FK_BOARD = re.compile(r"\S*socket (e-?atx |micro ?atx |mini ?itx |atx )?(amd |intel )?\S+ chipset ddr\d motherboard for (mobile|desktop|server)", A)
_COOLING_FAN = r"(cooling|cabinet|pwm|cpu|case|exhaust|motherboard|laptop|replacement) (cooling )?fan\b|\bfan cpu\b|\bcooling pad\b|laptop cooler\b|card cooler\b"
_TOWER = r"\b(mid|full|mini|micro)[- ]?tower\b|\batx (mid )?(tower|case|cabinet)|\bcabinet with\b|\bcase with\b|\bchassis\b|aquarium|\b\d fans?\b.{0,20}(included|pre-?installed)"


def _audit_fixes(t):
    """Listings the October 2026 live audit found in the wrong place; checked before the general rules."""
    if _s(r"degreaser|stain remover|kitchen chimney|kitchen organi[sz]er|airtight|hair straightener|straightener comb|coat hanger|lens cleaning wipes|"
          r"badminton|cricut|vinyl permanent|doorbell|\b(dash|desk) ?(&|and)? ?(lap|desk)? ?.{0,10}usb .{0,20}fan\b|usb (dual head |twin ?breeze |rotatable )?fan\b.{0,40}(dash|desk|lap)", t):
        return 'Other'
    # a monitor whose port list says "Headphone" or "Speaker" is still a monitor
    if _s(r"^.{0,60}\b(gaming |curved |ips |oled |4k |business )?monitor\b", t) and _s(r"\d{2}(\.\d)?\s?(inch|\"|cm)|\d{2,3}\s?hz", t) \
            and not _s(r"monitor (stand|arm|mount|light|riser|cable|adapter|bracket)|stand for|light ?bar|mounting|webcam|\bmic\b|microphone|headset with|"
                  r"pc set|computer set|desktop (pc|computer)|gaming pc|\bcore\s?i\d|\bi[3579][- ]\d{3,5}|\bryzen\b|\d+\s?gb ram|\bcpu\b", t):
        return 'Monitor'
    # panels named by size and panel type only ("Samsung Odyssey G5 ... (32 inch) Curved ... VA Panel ... Ports-HDMI,DP,Headphone")
    if _s(r"\d{2}(\.\d)?\s?inch\)?.{0,60}\b(va|ips|tn) panel\b", t) and not _s(r"laptop|notebook|\bcore\s?i\d|ryzen|\btv\b|television|tablet|projector", t):
        return 'Monitor'
    if _s(r"\b(rode|shure|audio-technica|blue yeti|hyperx quadcast|fifine|maono|boya)\b.{0,60}microphone|^.{0,50}\b(usb|condenser|studio|podcast|gaming|dynamic) (mic|microphone)\b", t) \
            and not _s(r"(mic|microphone) (stand|arm|holder|cable|pop filter|windscreen|foam|cover|clip|mount)\b|stand for (mic|microphone)|headset|headphone|earphone|webcam|speaker|\bcable\b", t[:60]):
        return 'Microphone'
    if _s(r"keyboard switches|(linear|tactile|clicky) switches|\bkeycaps?\b(?!.{0,20}keyboard)", t) and not _s(r"mechanical keyboard|gaming keyboard|\bkeyboard\b.{0,20}(with|rgb)", t):
        return 'Keyboard'
    if _s(r"liquid metal|thermal conductivity paste|conductonaut", t) and not _s(r"cooler|\bfan\b|graphics card|\bgpu\b|\brtx\b|laptop", t):
        return 'Thermal Paste'
    if _s(r"thrustmaster|hotas|flight (yoke|stick|throttle|pedals?)|rudder pedals|game ?stick\b|retro (game|gaming) console|tca (officer|captain)", t) and not _s(r"cover|stand for|mount for|headset|headphone", t):
        return 'Gaming Accessories'
    if _s(r"hdmi (splitter|switch|cable|extender)|displayport cable|^\W*\S+( \S+)? xlr (cable|cble)|\bdp cable|cable (set|combs?)|sleeved (extension )?cable|extension cable kit", t) \
            and not _s(r"monitor\b.{0,40}\d{2,3}\s?hz|\bcore\s?i\d|\bi[3579]-\d{3,5}|ryzen|\d+\s?gb (ddr\d )?ram", t):
        return 'Accessories'
    if _s(r"pro-?blade|ssd mag\b", t):
        return 'SSD'
    if _s(r"chair mat\b|mat for (rolling|office) chairs?", t):
        return 'Accessories'
    # a desktop SMPS ("SMPS 200W PS3 Power Supply | 20+4 Pin") is still a power supply, cord included or not
    if _s(r"\b(smps|power supply)\b", t[:80]) and _s(r"20\s?\+\s?4 ?pin|\batx\b", t) and not _s(r"cable|extension|adapter|convert|tester|bracket|cabinet|\bcase\b|tower|chassis", t[:80]):
        return 'Power Supply'
    if _s(r"power cord|power supply cable", t) and not _s(r"\bups\b.{0,20}(va|watt)|\d{3,4}\s?va|ps[345]|playstation|xbox|nintendo", t):
        return 'Accessories'
    # Flipkart desktop listings read like laptops: "(8 GB DDR3/500 GB/Windows 10 Pro/1 GB/18.5 Inch Screen"
    if _s(r"\b(1[89]|2[0-9])(\.\d)? inch screen\b", t) and not _s(r"laptop|notebook|\bthin and light\b|tablet", t):
        return 'Desktop PC'
    # Flipkart's "... 200 Watts Computer PSU with 2 SATA Cables" ending also lands on LED controllers, mains cords and CCTV
    # adapters; only a head that is itself a PC power supply keeps it in power supplies.
    m = re.search(r"\d+ watts (computer |gaming |server )?psu with \d+ sata cables", t, A)
    if m:
        head = t[:m.start()]
        if _s(r"\batx\b|80\s?\+|80 plus|bronze|gold|platinum|modular", head): return 'Power Supply'
        if _s(r"(power|mains|ac) (cable|cord|lead)|cable cord|power cable|vga cable|hdmi cable|video cable", head): return 'Accessories'
        if _s(r"\bled\b|cctv|dimmer|din rail|\bvdc\b|\d+\s?v(olt|alt)?s?\b|\d+(\.\d+)?\s?a(mp)?s?\b|adapt[eo]r|charger|transformer|controller|strip|rainproof|"
              r"panel mount|regulated|mean ?well|\blrs-|\bmdr-|converter|dc[- ]?dc|channel", head) \
                and not _s(r"\batx\b|80\s?\+|80 plus|bronze|gold|platinum|modular", head):
            return 'Other'
        return 'Power Supply'
    # Flipkart's "... Cabinet Compatible with Computer" ending on hooks, drawers and brushes
    m = re.search(r"\bcabinet compatible with (computer|gaming console)", t, A)
    if m and not _s(r"\batx\b|tower|gaming cabinet|airflow|tempered glass|\bargb\b|\brgb\b|\bitx\b|mesh|\bcase\b|pc cabinet", t[:m.start()]):
        head = t[:m.start()]
        if _s(r"\bmat\b|desk ?pad|mouse ?pad|workspace pad", head): return 'Mousepad'
        if _s(r"\bfan\b|cooler", head): return 'Fans & Cooling'
        return 'Accessories' if _s(r"keyboard|cleaning|brush", head) else 'Other'
    # parts and add-ons sold for a product, not the product
    if _s(r"anti[- ]?sag (bracket|support|stand)|vertical (gpu |graphics card )?(bracket|mount)( kit)?|gpu (support )?(holder|bracket|stand)|graphics card (holder|support bracket|bracket)|"
          r"upright gpu kit|\bnvlink\b|\bsli bridge|gpu bridge", t) \
            and not _s(r"gddr\d|\d+\s?gb\b.{0,20}graphics card|motherboard|tower|cabinet|\bcase\b|chassis", t):
        return 'Accessories'
    if _s(r"hard disk skin|hdd skin|(sata|sas) (data )?cable|hdd cable|ssd (adapter|bracket|mounting)|m\.?2 (nvme )?(adapter|converter)|nvme (adapter|converter)|"
          r"(ssd|hdd|nvme) (dock|enclosure|external case)|external case.{0,20}(hdd|ssd)|2\.5 to 3\.5", t) and not _s(r"\b\d+\s?(gb|tb)\b.{0,30}(internal|external) (ssd|hard)|portable ssd|external hard drive\b(?!.{0,10}(case|enclosure))", t):
        return 'Accessories'
    if _s(r"chair cover|gas lift (cylinder|replacement)|replacement.{0,20}gas (lift|cylinder)|chair (cylinder|wheels?|castors?)|armrest pads?|seat (cushion|slipcover)|cushion set", t) and not _s(r"^\W*\S+( \S+)? (gaming|office|ergonomic) chair\b(?!.{0,6}cover)", t) \
            and not _s(r"lumbar support|big and tall|executive (office )?chair|bis certified|\d+ years? warranty|tilt lock", t):
        return 'Accessories'
    if _s(r"screen guard|tempered glass|screen protector", t) and _s(r"earbud|airpods|watch|phone|mobile|tab\b|tablet", t):
        return 'Other'
    if _s(r"laptop speaker replacement|speaker replacement for|optical (splitter|adapter)|toslink", t):
        return 'Accessories'
    if _s(r"\bqsfp|\bsfp\+?\b.{0,20}(cable|module)|interconnect cable|dac cable", t):
        return 'Networking'
    if _s(r"replacement battery|laptop battery|battery for (hp|dell|lenovo|asus|acer)", t) and not _s(r"\bups\b|inverter", t):
        return 'Accessories'
    if _s(r"usb (2|3)\S* header|header (port|cable)|pci rear panel|power (sharing )?cable.{0,40}(atx|eps|pin)|\d+[- ]pin (male|female) to", t) and not _s(r"\bpsu\b.{0,10}with|power supply (unit|\d)", t[:40]):
        return 'Accessories'
    if _s(r"mouse.{0,15}keyboard combo|keyboard.{0,15}mouse combo", t) and _s(r"combo motherboard", t):
        return 'Keyboard'
    if _s(r"(bluetooth|wireless|wired) (headphones?|earphones?|neckband)|headphones?\b.{0,30}(sd card|fm)", t) and _s(r"sd card", t):
        return 'Headset'
    if _s(r"t-?1000s|ws281\d|pixel (led )?controller|led strip controller|dimmer|dimming controller", t) and not _s(r"\bfan|cooler|argb|\brgb\b.{0,20}(fan|cooler)", t):
        return 'Other'
    # workstation and bare graphics cards ("NVIDIA RTX PRO 6000 Blackwell Workstation Edition 96GB") are not PCs
    if not _FK_GPU.search(t) and _s(r"graphics? card|\bgpu\b|video card", t) and _s(r"gddr\d|\b\d{1,2}\s?gb\b|quadro|firepro|rtx (pro|a\d{3,4})", t) \
            and not _s(r"\b\d+\s?gb\s?(ram|ddr\d)|\bram\b|\bssd\b|\bhdd\b|windows|win ?1[01]|mini pc|\bnuc\b|gaming pc|desktop pc\s*(\||,|with)|laptop|notebook|motherboard|cooler|fan\b.{0,10}cool|holder|bracket\b(?! included)|riser|cable|\bstand\b|support|converter", t):
        return 'Graphics Card'
    if _s(r"desktop pc processor|\bprocessor\b.{0,20}\b\d+ core cpu", t) and _s(_CPU, t[:40]) and not _s(_RAM_SIZE, t):
        return 'Processor/CPU'
    # Flipkart's "... Cabinet with USB 2.0 and USB 3.0 Ports Compatible with Computer" ending on bins, pens and organisers
    m = re.search(r"cabinet with usb 2\.?\s?0( and usb 3\.?\s?0)? ports compatible with (computer|gaming console)", t, A)
    if m:
        head = t[:m.start()]
        if _s(r"\bmat\b|desk ?pad|mouse ?pad|workspace pad", head): return 'Mousepad'
        if _s(r"\bbin\b|\bbox\b|laser|\bpen\b|organi[sz]er|divider|presenter|clicker|remote|holder|\btray\b|multi ?purpose", head): return 'Other'
    m = _FK_CPU.search(t)
    if m:
        head = t[:m.start()]
        real = _s(r"ryzen|core\s?i[3579]|\bi[3579][- ]?\d{3,5}|core 2|xeon|pentium|celeron|athlon|threadripper|core\s?ultra", head)
        return 'Processor/CPU' if real else 'Gaming Accessories' if _s(r"\bvr\b|virtual reality|3d glasses", head) else 'Other'
    m = _FK_BOARD.search(t)
    if m:
        head = t[:m.start()]
        if _s(r"diagnostic|tester|analy[sz]er|debug card|post card", head): return 'Accessories'
        if _s(r"motherboard|\b[abhxz]\d{2,3}[a-z]?\b|\blga\b", head): return 'Motherboard'
        return 'Gaming Accessories' if _s(r"\bvr\b|virtual reality|3d glasses", head) else 'Other'
    # bare power supply circuit boards and 12 V adapters are electronics spares, not PC power supplies
    if _s(r"power supply (board|pcb|module|circuit)|smps (bare )?circuit|bare circuit|bread ?board power|\bpcb\b.{0,30}(smps|power supply)|"
          r"\d+\s?v(olts?)? \d+(\.\d+)?\s?a(mps?)?\b.{0,40}(dc )?(power )?(adapter|adaptor)|dc power (adapter|adaptor)|"
          r"(smps|power supply|adapter|adaptor|led driver).{0,60}(\b\d+(\.\d+)?\s?v\b[ ,]{0,3}\d+(\.\d+)?\s?a(mp)?\b|\b\d+(\.\d+)?\s?a(mp)?\b[ ,]{0,3}\d+(\.\d+)?\s?v\b|\d+v,\s?\d+v)|"
          r"(\b\d+(\.\d+)?\s?v\b[ ,]{0,3}\d+(\.\d+)?\s?a(mp)?\b|\b\d+(\.\d+)?\s?a(mp)?\b[ ,]{0,3}\d+(\.\d+)?\s?v\b).{0,60}(smps|power supply|adapter|adaptor|led driver)|"
          r"(smps|power supply).{0,40}(cctv|led strip|ro water|purifier)|led driver|\d+v\s?\d+\s?amp|\b\d+\s?ch(annel)? smps", t) and not _s(r"cooling fan|\bfan\b.{0,10}cooler|\bups\b|battery backup", t) \
            and not _s(r"\batx\b|\b[3-9]\d0\s?w(att)?\b|\b1\d{3}\s?w(att)?\b|80\s?\+|80 plus|modular|pcie|pci-e|6\+2|4\+4|bronze|gold", t):
        return 'Other'
    if _s(r"thermal (silicone |silicon |conductive |cunductive )?(pads?|putty)\b|conductive pad|\btg putty\b|fever patch", t) and not _s(r"laptop stand", t):
        return 'Thermal Paste'
    if _s(r"gaming (surface )?mat\b|gaminig mat|desk ?(pad|mat)\b|workspace mat|surface mat", t) and not _s(r"chair|cabinet with (fan|glass)", t[:30]):
        return 'Mousepad'
    cpu_first = _s(_CPU, t[:40]) and 0 <= t.find("processor") < t.find("fan")
    gpu_card = _s(r"\bgddr\d|\d+\s?gb\b.{0,30}(graphics|video) card|(graphics|video) card.{0,60}(\d+\s?gb|pci express|\d+ bit)", t)
    if _s(_COOLING_FAN, t) and not _s(_TOWER, t) and not _s(_RAM_SIZE, t) and not cpu_first and not gpu_card \
            and not _s(r"\bups\b|inverter|table fan|ceiling fan|pedestal|air purifier|neck fan|enclosure|thermal (paste|compound|grease)|power supply|\bpsu\b|\d{3}\s?w\b|"
                       r"\bps[2345]\b|playstation|xbox|nintendo|\bswitch\b|motherboard (combo|kit)|combo kit|\bkit\b.{0,40}(processor|\bi[3579]\b)", t):
        return 'Fans & Cooling'
    if _s(r"keyboard (cover|skin|protector)|webcam (privacy )?cover|camera privacy cover|privacy cover for|hard (drive|disk) (bay )?caddy|"
          r"2nd hard drive|hard disk case|hdd (enclosure|caddy)|ssd enclosure", t) \
            and not (_s(r"\bweb ?cam(era)?\b", t[:40]) and _s(r"\b(1080p|720p|2k|4k|qhd|fhd|full hd|microphone)\b", t)):
        return 'Accessories'
    if _s(r"\b\d+\s?(gb|tb)\b.{0,80}(all in one pc'?s|surveillance systems)", t) and _s(r"sata|internal|hard|\bhdd\b|\bintern", t):
        return 'SSD' if _s(r"\bssd\b|solid state", t) else 'HDD'
    if _s(r"\bnas\b.{0,30}(internal )?(hard (disk )?drive|\bhdd\b|\bssd\b|solid state)|(hard (disk|drive)|\bhdd\b).{0,30}\bnas\b|ironwolf|\bwd red\b|red pro\b.{0,40}hard", t) \
            and not _s(r"diskstation|\bbay\b|enclosure|\bds\d{3,4}|\bts-\d", t):
        return 'SSD' if _s(r"\bssd\b|solid state", t) else 'HDD'
    if _s(r"^\s*\S+\s+bluetooth speaker|\bbluetooth speaker\b.{0,30}(sd card|aux|stereo)", t):
        return 'Speakers'
    if _s(r"\bwebcam\b", t[:70]) and not _s(r"webcam cover|privacy cover for", t) and not _s(r"\bmonitor\b", t[:70]):
        return 'Webcam'
    if _s(r"\bmicrophone\s*$", t) and _s(r"\bmic\b|selfie|wireless", t):
        return 'Microphone'
    if _s(r"\b(intel )?(core )?i[3579]\s?\(?\d{4}\)?\b.{0,40}processor for (h\d{2}|[abhxz]\d{3}|lga|am\d)|processor for (h\d{2}|[abhxz]\d{3}) (board|chipset|motherboard)", t) \
            and not _s(_RAM_SIZE, t):
        return 'Processor/CPU'
    return None


def _rules_console(title, cat):
    t = ' ' + _WS.sub(' ', _DOTS.sub(' ', str(title).lower())) + ' '
    if cat == 'Other':
        return cat
    con = _console(t)
    if con:
        return con
    if cat in ('PlayStation', 'Xbox', 'Nintendo'):
        if _s(r"dualsense|dualshock|joy-?con|xbox (wireless|elite|core) controller|pro controller", t) and not _s(r"charging|charger|stand|cover|skin|grip|case\b|thumb|dock", t):
            return cat
        if _GAME_HINT.search(t) and not _s(r"controller|\bstand\b|cover|skin|dust|\bkit\b|yoke|wheel|pedal|headset|cable|charg|\bcase\b|\bbag\b|grip|mount|holder", t):
            return 'Games'
        if _s(r"\bssd\b|nvme|m\.2", t): return 'SSD'
        return 'Gaming Accessories'
    # a game that the general rules could not place ("PS5 Marvel's Wolverine", "UNTIL DAWN (PS5)")
    if cat == 'Components' and _s(r"\b(ps ?[345]|playstation ?[345]|xbox (series|one)|nintendo switch|switch 2)\b", t) and not _CONSOLE_ACC.search(t) \
            and not _s(r"hdmi|adapter|converter|capture|\bcard\b|monitor|\btv\b", t):
        return 'Games'
    return cat


def _type_of(title):
    t = ' ' + _WS.sub(' ', _DOTS.sub(' ', str(title).lower())) + ' '
    if _s(r"fidget|stress relief|(keyboard|switch|keycap|toy)\s?key ?chain|key ?chain\s?(toy|fidget)", t) and not _s(r"pen ?drive|flash drive|usb drive|memory stick", t):
        return 'Other'
    fix = _audit_fixes(t)
    if fix:
        return fix
    fk = _FK_GPU.search(t) or _FK_SSD.search(t)
    if fk:
        head = t[:fk.start()] + ' '
        if _s(r"\bvr\b|virtual reality|3d glasses", head): return 'Gaming Accessories'
        if _s(_JUNK_HEAD, head): return 'Other'
        gpu = r"\b(rtx|gtx|gt|rx|arc|geforce|radeon|quadro|vga|gpu|graphics|zotac|zt-|msi|asus|gigabyte|sapphire|powercolor|xfx|inno3d|palit|galax|colorful|zebronics|nextron|asrock|pny|evga|maxsun|yeston|biostar)\b|\b(gt|rx|gtx|rtx)?\s?-?\d{3,4}\b|\bgv-|dual-"
        if _s(r"(graphics?|gpu|card)\s+(cooler|fan)|cooling fan", head): return 'Fans & Cooling'
        if _s(r"graphics? card|\b(gt|gtx|rtx|rx)\s?-?\d{3,4}\b", head) and not _s(r"\bfan\b|cooler|cooling", head[:30]) and not _s(r"stand|holder|bracket|support|riser", head): return 'Graphics Card'
        if _s(r"\bfan\b|cooler|cooling", head): return 'Fans & Cooling'
        if _s(r"riser|splitter|expansion card|extender|\bstand\b|holder|bracket|adapter|converter|\bm\.2\b|nvme|\bssd\b", head): return 'Accessories'
        if fk.re is _FK_GPU:
            return 'Graphics Card' if _s(gpu, head) and not _s(r"\be\d{2,3}\b|stylus|\bpen\b", head) else 'Other'
        return _rules_type(head)
    if _s(r"diagnostic (card|tool|tester|analy[sz]er)|post card|debug card|\btester\b|analy[sz]er", t) and not _s(_CPU, t) and not _s(r"\bups\b|\bva\b", t): return 'Accessories'
    if _s(r"(mid|full|mini|micro|super)[- ]?tower|pc case|computer case|gaming case|atx case|\bcabinet\b(?!\s+(cooler|compatible|stand|support|fan))|\bchassis\b", t[:70]) \
            and not _s(r"cabinet (cooler|compatible)|display cabinet|\bheat ?sinks?\b|enclosure", t) \
            and not _s(r"cabinet (fans?|cooler|cooling|lock|handle|stand)|\bfans?\b.{0,20}cabinet|carrying|backpack|\bbag\b|cover|\bstand\b|clean|tv cabinet|kitchen|keyboard|mouse|speaker|\bups\b|bracket|holder|mount\b|riser", t[:60]) \
            and not _s(r"^\W*(\w+\W+){0,2}(cpu |case |cabinet )?(fans?|cooler)\b|\b(case|cabinet|pc|computer|chassis)\s+fans?\b|cooling fans?\b.{0,30}\b(for|pc)\b|\bfans?\b.{0,25}\bfor\b.{0,15}(pc |computer )?(case|cabinet)|\bmat\b|mouse ?pad|air duster|\bpsu\b|power supply|\bsmps\b", t) \
            and not _s(_CPU, t) and not _s(_RAM_SIZE, t):
        return 'PC Case/Chassis'
    if _s(r"thermal (conductive|paste|compound|grease)|grease paste|conductive grease|heat ?sink (paste|compound)", t[:60]) \
            and not _s(r"^\W*(\w+\W+){0,3}(cpu |air |liquid )?(cooler|fan)\b|processor|\bcpu\b.{0,6}(with|\+)|liquid|\baio\b", t[:40]):
        return 'Thermal Paste'
    if _s(r"\b\d{3,4}\s?w\b.{0,40}(80\s?\+|80 plus|bronze|gold|platinum|titanium|modular|\bsmps\b|\bpsu\b|power supply)|(80\s?\+|80 plus)\s?(bronze|gold|platinum|titanium).{0,40}\b\d{3,4}\s?w\b", t) \
            and not _s(r"cabinet|\bcase\b|chassis|\bups\b|\bcable\b|tester|\b\d{3,4}\s?va\b|gaming pc|desktop pc|\bnas\b|\bbay\b|rack|graphics card|motherboard", t) and not _s(_CPU, t):
        return 'Power Supply'
    if _s(r"^.{0,50}(stock fan|cpu fan|cooling fan|heat ?sink)", t) and not _s(r"graphics? card|\bssd\b|\bnvme\b|\bm\.2\b|solid state|\bddr\d|dimm|\bram\b|paste|compound|grease|ps[345]|playstation|xbox", t) \
            and not (_s(_CPU, t) and _s(_RAM_SIZE, t)):
        return 'Fans & Cooling'
    if _s(r"\b(ps[345]|playstation|xbox|nintendo)\b", t) and _s(r"cooling fans?|cooler|cooling (station|stand|system|dock)", t) \
            and not _s(r"^\W*sony|game (cd|disc)|games? cd|computer|\bpc\b|\bdvr\b|router|receiver|tv box|av cabinet", t):
        return 'Gaming Accessories'
    if _s(r"smart (led |qled |oled |google |android )?tv\b|\btelevision\b|\b(qled|oled|led) tv\b", t) and not _s(r"monitor|tv stick|tv box|console|nintendo|playstation|xbox|remote|projector", t):
        return 'Other'
    if _s(r"multifunction (printer|laser|inkjet)?|imageclass|laserjet|inkjet|ink tank|\bprinter\b", t) and not _s(r"3d printed|printer cable|\bfor\b.{0,10}printer", t): return 'Other'
    if _s(r"live streamer|streaming kit|stream(ing)? deck", t) and not _s(r"\bmic\b|microphone|headset|webcam|\bcam\b", t): return 'Gaming Accessories'
    if _s(r"\b(1[24]0|[89]0|200)\s?mm\b.{0,40}\b(argb|rgb|pwm|fans?)\b", t[:70]) and not _s(_CPU, t) and not _s(r"radiator|aio|liquid|cabinet|\bcase\b|tower|cooler|power supply|\bsmps\b|\bpsu\b", t[:50]):
        return 'Fans & Cooling'
    if _s(r"\bdock(ing)?\b.{0,30}(usb|type-?c|display|hdmi|station)|(usb|type-?c|thunderbolt).{0,30}\bdock(ing)?\b", t) and not _s(r"ps[345]|playstation|xbox|nintendo|controller|\bssd\b|enclosure|laptop\b.{0,10}(with|\+)|monitor|\binch\b", t):
        return 'Accessories'
    # Flipkart's headphone spec tail ("... RTL Chipset Bluetooth & Wired")
    if _s(r"\b\w+ chipset bluetooth|bluetooth (&|and) wired\s*$", t) and not _s(r"speaker|soundbar", t): return 'Headset'
    # Flipkart labels drives "... Internal Solid State Drive (SSD)" whatever their compatibility list says (NAS, servers)
    if _s(r"internal solid state drive \(ssd\)", t) and not _s(_CPU, t) and not _s(r"enclosure|caddy|adapter|heat ?sink|cooling pad|reader|\bdock", t): return 'SSD'
    # drives that only mention the PCs they fit ("... Hard Disk Drive ... All in One PC's, Desktop, Laptop")
    if _s(r"hard dis[kc] drive|\(hdd\)|\binternal hdd\b|\bexternal hdd\b", t) and not _s(_CPU, t) and not _s(r"\bssd\b.{0,20}(capacity|/)|win(dows)?\s?1[01]", t):
        return 'Accessories' if _s(r"caddy|enclosure|\bcase\b|docking|dock\b|cover only|adapter|converter", t) else 'HDD'
    # all-in-one PCs before laptops: a screen and a laptop-class CPU do not make a laptop
    if _s(r"all[- ]?in[- ]?one|\baio\b.{0,6}(pc|desktop|computer)|\b(pavilion|ideacentre|inspiron) aio\b", t) and _s(_CPU, t) \
            and not _s(r"cooler|liquid|water|printer|keyboard|mouse|speaker", t):
        return 'Desktop PC'
    # laptops named only by a mobile CPU code and their spec sheet ("DELL G15 ... 12500H - (16 GB/512 GB SSD/Windows 11 ...")
    if _s(_MOBILE_CPU, t) and (_s(_RAM_SIZE, t) or _s(_DISK_SIZE, t)) and (_s(r"win(dows)?\s?1[01]|\bdos\b|\d{2}(\.\d)?\s?(\"|inch|cm)|\bfhd\b|\bwuxga\b|\bips\b|\bhz\b|laptop", t) or _s(_LAPTOP_MODELS, t)) \
            and not _s(r"mini pc|\bnuc\b|desktop|tower|all[- ]?in[- ]?one|\baio\b|monitor|\bbarebone|motherboard|mainboard", t):
        return 'Gaming Laptop'
    # a laptop listing with its memory, storage and Windows ("Surface Pro ... (16 GB/512 GB SSD/Windows 11 Home) ... 2 in 1 Laptop")
    if (_s(_LAPTOP, t) or _s(_LAPTOP_MODELS + r"|surface pro|surface laptop", t)) and _s(_RAM_SIZE, t) and _s(_DISK_SIZE, t) \
            and _s(r"win(dows)?\s?1[01]|\bdos\b|macos|chrome ?os", t) and not _s(r"all[- ]?in[- ]?one|\baio\b|desktop|tower|mini pc|\bnuc\b|monitor", t):
        return 'Gaming Laptop'
    if _system(t):
        return 'Desktop PC'
    # memory "for laptop" and portable screens are not laptops
    if _s(r"\bddr[2345]l?\b|so-?dimm|\b\d+\s?gb\b.{0,20}\bram\b", t) and _s(_LAPTOP, t) and not _s(_CPU, t) \
            and not _s(r"win(dows)?\s?1[01]|\bssd\b|\binch\b|\bhz\b|motherboard|mainboard|mouse ?pad", t):
        return 'Memory/RAM'
    if _s(r"portable (gaming |touch ?screen |oled )?monitor|external monitor|travel monitor|monitor for laptop|laptop (screen )?monitor|second screen", t) \
            and not _s(_CPU, t) and not _s(r"\barm\b|mount|bracket|light ?bar|stand for|cleaner|privacy|cable\b|adapter|webcam", t):
        return 'Monitor'
    # a CPU named up front and called a processor is a processor, whatever board or chipset it says it fits
    if _s(_CPU, t[:48]) and _s(r"processor|\bcpu\b|\bapu\b", t) and not _s(_RAM_SIZE, t) \
            and not _s(r"\bcombo\b|\bkit\b|bundle|laptop|notebook|\binch\b|win(dows)?\s?1[01]|\bfhd\b|series (cpu|processor)|\b[abxzh]\d{3}[a-z]?\b.{0,30}(socket|series)", t) and not _s(_LAPTOP_MODELS, t) and not _s(r"motherboard|mainboard", t[:40]) \
            and not (_s(r"cooler|liquid|\baio\b|\bfan\b|heat ?sink", t) and not _s(r"(cooler|fan)[^,)]{0,15}not included|without (a )?(cooler|fan)", t)):
        return 'Processor/CPU'
    # a Ryzen "G" chip "with Radeon (RX) Vega graphics" names its built-in graphics, not a graphics card
    if _s(r"ryzen\s?[3579]\s?\d{4}ge?\b", t[:40]) and _s(r"with radeon( rx)?( vega)?( \d+)? graphics|with radeon (rx )?vega", t) \
            and not _s(_RAM_SIZE, t) and not _s(r"\bcombo\b|\bkit\b|bundle|laptop|notebook|motherboard|mainboard|\bssd\b", t):
        return 'Processor/CPU'
    return _rules_type(title)



# fmt: off
def _rules_type(title):
    t = ' ' + _WS.sub(' ', _DOTS.sub(' ', str(title).lower())) + ' '
    # mousepads FIRST (before the accessory list) so they get their own tab instead
    # of drowning in Accessories.
    if _s(r"""\bvr box\b|\bvr headset\b|virtual reality|\bpsvr\b|playstation vr|meta quest|\boculus\b""",t): return 'Gaming Accessories'
    if _s(r"""mouse ?pad|mouse ?mat|deskmat|deskspread|desk ?mat\b""",t) and not _s(r"""\bdpi\b|\d\s?buttons?\b""",t): return 'Mousepad'
    if _s(r"""\bmouse\b""",t) and _s(r"""\bdpi\b|\d\s?buttons?\b|side buttons?|silent click""",t) and not _s(r"""mouse (pad|mat)\b.{0,10}$""",t): return 'Mouse'
    # accessory words ("stand", "backpack", "palm rest") often describe a BUNDLED
    # extra ("monitor with stand", "laptop with backpack", "keyboard with wrist
    # rest") — only file under Accessories when the product itself isn't clearly
    # a device, or the accessory word LEADS the title.
    headAcc=_s(r"""keycap|keyboard switch|switch (set|puller)|stabilizer|wrist rest|palm rest|\bcover\b|\bskin\b|\bstands?\b|holder|\bbag\b|sleeve|cooling pad|riser|dust""",t[:30])
    acHit=any(k in t for k in ACCESSORY_KW) or _s(r"""\bstands?\b|\bmounts?\b""",t) or _s(r"""mounting (frame|kit|bracket|plate)""",t)
    deviceEvidence = ((_s(r"""\bkeyboard\b""",t) and _s(r"""mechanical|membrane|backlit|backlight|hot-?swap|\btkl\b|semi-?mech|anti-?ghost""",t))
        or (_s(r"""\bmouse\b""",t) and _s(r"""\bdpi\b|\d\s?buttons|side buttons?|silent click|optical|ergonomic""",t))
        or (_s(r"""webcam|web ?cam""",t) and _s(r"""1080|720|4k|auto ?focus|sensor|fps|\bmic\b""",t))
        or (_s(r"""\bmonitor\b""",t) and _s(r"""\d{2,3}\s?hz|fhd|qhd|uhd|ips|\d{3,4}x\d{3,4}""",t))
        or ((_s(r"""\b(laptop|notebook)\b""",t) or _s(r"""\bc?i[3579]-?\d{4,5}(hx|hs|h|u|k|kf)?\b""",t) or _s(r"""ryzen\s?[3579]\s?\d{4}|\br[3579]-?\d{4}u?\b""",t)) and _s(r"""\bssd\b|\bram\b|win\s?1[01]|\d+\s?gb\b|\brtx\b|\bgtx\b|\bhx\b""",t))
        or (_s(r"""\b\d{3,4}\s?x\s?\d{3,4}\b""",t) and _s(r"""\d{2,3}\s?hz""",t))
        or (not _s(r"""cable|extension|sleeved|diagnostic|post card|debug|clean|dust remover|heat ?sink|cooler|cooling|reader|enclosure|caddy|adapter|carrying|backpack|\bbag\b|panel mount|din rail|led driver|mean ?well|\bvalt\b|\bvolt\b|\bstand\b|holder|compatible with|bill fork""",t) and _s(r"""motherboard|mainboard|(mid|full|mini|micro)[- ]tower|\bcabinet\b|pc case|computer case|\bchassis\b|\bups\b|\b\d{3,4}\s?va\b|uninterrupt|power supply|\bpsu\b|internal (ssd|solid[- ]state)|\bnvme\b.{0,30}\b(ssd|solid[- ]state)""",t))
        or _s(r"""(mid|full|mini|micro|super)[- ]?tower|pc cabinet|gaming cabinet|pc case|computer case|sff computer case|\bchassis\b""",t[:50])
        or (_s(r"""\b\d{2}(\.\d{1,2})?\s?(inch|"|cm)""",t) and _s(r"""\b(ips|va|tn|oled|qhd|fhd|uhd|wqhd|\d{2,3}\s?hz|hdr\d*|full hd|quad hd|ultra hd|led backlit)\b""",t) and not _s(r"""\b(arm|mount|bracket|riser)\b""",t[:40])))
    if acHit and (headAcc or not deviceEvidence): return 'Accessories'
    # wifi/bluetooth dongles & NAS boxes -> Networking (before generic buckets)
    if _s(r"""(wi-?fi|wifi|802\.11|bluetooth).{0,60}(adapter|receiver|dongle)|\bax\d{4}\b.{0,60}(usb|adapter)""",t): return 'Networking'
    if _s(r"""\b(qnap|synology|asustor)\b""",t) and _s(r"""\bts-|\btl-|\bds\d|\bas\d|nas|\bbay\b""",t): return 'Networking'
    # cables are accessories, not "Components"
    if _s(r"""\b(hdmi|display ?port|dvi|vga|usb(-c)?|type-?c|aux|toslink|optical audio|cat ?[5-8]e?|ethernet|lan|patch)[\s-]{0,6}cable\b|\bcable\b.{0,14}\bmeters?\b|charging cable""",t): return 'Accessories'
    # custom-loop watercooling parts
    if _s(r"""\benclosure\b|\bcasing\b|(ssd|hdd|drive) case\b""",t): return 'Accessories'
    if _s(r"""usb.{0,20}\bhub\b|\bhub\b.{0,12}(usb|type-?c)""",t): return 'Accessories'
    if _s(r"""\b(usb(-c)?|type-?c|hdmi|vga|dvi|display ?port)\b.{0,24}adapter""",t) and not _s(r"""wi-?fi|wifi|bluetooth|802\.11""",t): return 'Accessories'
    if _s(r"""\bcharger\b""",t) and not _s(r"""car charger|travel|charging dock|charging station|controller""",t): return 'Accessories'
    if not _s(r"""graphics card|graphic card|\brtx\s?\d|\bgtx\s?\d|\bradeon rx""",t) and _s(r"""\bdistro\b|water ?block|\breservoir\b|pump[- ]?res|hydro x|hardline|soft tubing|\bfittings?\b.{0,10}mm""",t): return 'Fans & Cooling'
    if _s(r"""wave xlr|audio interface|\bgo xlr\b""",t): return 'Microphone'
    if _s(r"""next level racing|racing seat|\bnlr\b""",t): return 'Gaming Accessories'
    if (_s(r"""\b(case|cabinet|computer case) fans?\b""",t) or _s(r"""(cooling|dc|brushless) fans?\b.{0,20}(pc case|cabinet|cpu)|\bbrushless\b.{0,12}fan|\baxial\b.{0,24}cooling|cooling device""",t)) and not _s(r"""(mid|full|mini) tower|tempered glass|side panel""",t): return 'Fans & Cooling'
    if _s(r"""^.{0,40}(cpu cooler|air cooler|tower cooler|liquid cooler|aio cooler)""",t) and not _s(r"""\bssd\b|\bnvme\b|solid state""",t[:60]): return 'Fans & Cooling'
    # streaming gear & mobile-gaming add-ons
    if _s(r"""stream deck|capture device|chat link|green screen|key light|ring light|gaming trigger|\bpubg\b|\bbgmi\b""",t) and not _s(r"""graphics card|\bgpu\b|\bram\b|\bssd\b|processor|motherboard|\bmonitor\b""",t): return 'Gaming Accessories'
    # network gear that says "switch" (never Nintendo Switch)
    if _s(r"""(network|ethernet|gigabit|desktop|poe|managed|unmanaged|\d+[- ]?port) switch""",t) and not _s(r"""nintendo""",t): return 'Networking'
    # NAS boxes are network storage, not desktops
    if _s(r"""\bnas\b|network[- ]attached storage""",t): return 'Networking'
    # office/home items PC stores also sell — 'Other' is dropped by normalize()/regroup
    if _s(r"""\bprinter\b|photocopier|\bscanner\b|\btoner\b|ink (tank|cartridge)|air purifier|water purifier|\bhepa\b|vacuum cleaner|\bprojector\b|\btablet\b|smart ?watch|antivirus|extension board|surge (cube|protector)|spike guard|power strip|travel adapter|car charger|power bank|electricity sav|id card|pvc card|laser pointer|wireless presenter|\bpure air\b|\binverter\b|smart notebook|syncpen|\bsmart pen\b|digital notepad|writing (pad|tablet)""",t): return 'Other'
    # digital goods (subscriptions, gift cards, game-pass) are NOT physical games or consoles
    if _s(r"""game ?pass|membership|subscription|gift card|gift voucher|e-?gift|\btop.?up\b|live gold|psn (wallet|card|credit)|prepaid|redeem code|wallet code|digital code""",t) and not _s(r"""rog\s*(xbox\s*)?ally|steam ?deck|legion go|msi claw""",t): return 'Gaming Accessories'
    # Sim-racing / flight gear is console-compatible but a PC peripheral -> Gaming Accessories.
    if _s(r"""racing wheel|sim racing|\bpedals?\b|\bshifter\b|handbrake|cockpit|wheel base|wheel stand|\bhotas\b|flight stick|sidestick|\bjoystick\b|playseat|fanatec|\bmoza\b|sim hub|wheel add|gear ?shift|sequential shifter|wheel mount|racing clamp""",t): return 'Gaming Accessories'
    # cheap retro "game stick"/emulator boxes are NOT real consoles — keep them out of the brand tabs
    if not _s(r"""nintendo|switch lite|steam ?deck|rog\s*(xbox\s*)?ally|legion go|msi claw""",t) and _s(r"""game stick|retro gam(e|ing)|retro handheld|handheld gaming console|game system|play system|tv video game|\d{2,}\s?in\s?1\b.{0,24}games?|built[- ]?in (classic )?game|\d{3,}\s*(in|\+)?\s*(built|classic|retro|video)?\s*(video )?games?|game box|gamesoul|emulator""",t): return 'Gaming Accessories'
    # handheld gaming PCs (ROG Ally, Legion Go, Steam Deck) are PCs, not consoles
    if _s(r"""rog\s*(xbox\s*)?ally|legion go|steam ?deck|msi claw""",t) and not _s(r"""headset|headphone|earbud|\bcontroller\b|gamepad|mouse|keyboard|\bcase\b|\bskin\b|charger|\bdock\b|dongle|\bcable\b|\bgrip\b|\bstand\b|memory card|micro ?sd|upgrade kit|\bfor (the )?(rog|ally|steam ?deck|legion)\b|screen protector|tempered""",t): return 'Gaming Laptop'
    # PS5/console disc drives & blu-ray add-ons are accessories, not the console itself
    if _s(r"""\bdisc drive\b|\bdisk drive\b|blu-?ray drive""",t) and _s(r"""ps5|playstation|xbox|console|blu-?ray""",t) and not _s(r"""hard dis[kc] drive|\bhdd\b""",t): return 'Gaming Accessories'
    if _s(r"""playstation portal|remote player|\bportal\b.*ps5|ps5.*\bportal\b""",t): return 'Gaming Accessories'
    # [r23] real Switch 2 hardware sold without the word "console" ("Online Game ...
    # 4K Dock, Joy-Con 2, GameChat") or with "Built-in GameChat" phrasing
    if _s(r"""nintendo\s+switch\s*2\b""",t) and _s(r"""\b(4k dock|4k hdr|hdr lcd|joy-?con 2|gamechat|tabletop|handheld modes?|256 ?gb)\b""",t) and not _s(r"""game (cd|disc|cartridge)\b|physical cartridge|cartridge edition|\bcase\b|\bcover\b|\bskin\b|protector|pouch|\bgrip\b|charg|\bstand\b|\bstrap\b|memory card|micro ?sd|\bfor (nintendo|switch)\b""",t): return 'Nintendo'
    if _s(r"""\bjoy.?cons?\b""",t) and not _s(r"""console|gamechat|4k dock|tabletop|\bswitch\b.{0,14}(oled|lite|console|2\b)""",t): return 'Gaming Accessories'
    # ── r17: physical console GAMES/discs — even when the title carries "console"
    # (edition label) or "gaming console" (compatibility blurb). Disc/cartridge media
    # words are the tell; real console SKUs never say "game cd/disc" or "physical cartridge".
    if (_s(r"""\b(ps[345]|playstation|xbox|nintendo)\b""",t)) and (_s(r"""\bgames?\s*(cd|disc|dvd)\b|\bgame\s*(cd|disc|dvd|cartridge)\b|\bphysical\s+(cartridge|cd|disc|games?)\b|\bcartridge\s+edition\b""",t)): return 'Games'
    # r17: console REPAIR / replacement parts are accessories, not the console itself.
    if (_s(r"""\b(ps[345]|playstation|xbox|nintendo)\b""",t)) and (_s(r"""\b(replacement|connector|socket|interface|ribbon|flex cable|hdmi port|charging port|power board|reader board|repair|faceplate|housing|shell case|conductive film|thumbstick module)\b""",t)): return 'Gaming Accessories'
    # r17: brand-squatting CLONES ("MICROMINI Nintendo Switch Lite ... Built-in
    # Controls", "620-in-1" retro boxes) borrow a real console name but are toys.
    if (_s(r"""\b(nintendo|ps[345]|playstation|xbox)\b""",t)) and (_s(r"""built-?in\s+(controls?\b|games?\b|classic\b)|\bmicromini\b|\b\d+\s?in\s?1\b|\b\d{3,}\s*(classic|retro|video|built-?in)?\s*games?\b|\bhandheld game console\b""",t)): return 'Gaming Accessories'
    # ── r18: multi-system retro EMULATOR clones ("GAMESOUL", "620-in-1", "open
    # source game console", "20+ emulator") squat the console tabs by listing every
    # platform as compatible. Real Sony/MS/Nintendo consoles never say these.
    if _s(r"""\bemulator\b|\bgamesoul\b|open source game console|retro (old )?(video )?game|revisit childhood|\d{2,}\s?\+?\s*(in\s?1|emulators?)\b|\d\s?\+?\s*emulators?\b|built-?in\s+(games|classic)""",t): return 'Gaming Accessories'
    if (_s(r"""\bconsole\b|handheld|game ?box|game ?stick|game ?player""",t)) and ((sum(_s(p,t) for p in (r"\bps[1-5]\b|playstation", r"\bxbox\b", r"\bnintendo\b|\bswitch\b")))>=2) and not _s(r"""\b(sony|microsoft)\b""",t[:32]): return 'Gaming Accessories'
    # r18b: console cases / pouches / screen-protectors / thumb-grips that merely
    # NAME a console are accessories (previously fell into the Components dump).
    if (_s(r"""\b(ps[45]|playstation|xbox|nintendo|joy-?cons?|dualsense|dualshock)\b|rog\s*(xbox\s*)?ally|steam ?deck|legion go""",t)) and (_s(r"""protective case|carrying case|carry case|travel case|hard case|storage case|silicone case|rugged (armor )?case|controller case|console case|\bcase for\b|\bcover\b|screen protector|screen guard|tempered glass|\bthumb ?grips?\b|grip caps?|analog caps?|carrying bag|controller skin|console skin|dust cover for|\bpouch\b""",t)): return 'Gaming Accessories'
    # Real consoles only (strict) — "PS5/Xbox compatible" peripherals must not count.
    if (_s(r"""playstation\s*[45]|\bps[45]\b|xbox\s*series\s*[sx]|xbox\s*one|nintendo\s*switch""",t)) and _s(r"""\bconsole\b|digital edition|\bslim\b|\boled\b|\blite\b|gaming console""",t) and not _s(r"""wheel|pedal|cover|skin|charg|cable|holder|\bstand\b|\bmount\b|grip|adapter|controller|headset|hub|tray|clamp|game add|external|expansion|memory card|micro ?sd|\bcase\b|protector|tempered|glass|screen guard|pouch|carry|sleeve|silicon|sticker|decal|\bwrap\b|thumb|remote player|\bportal\b""",t):
        if _s(r"""xbox""",t): return 'Xbox'
        if _s(r"""nintendo|switch""",t): return 'Nintendo'
        return 'PlayStation'
    # Physical games / discs for a console -> Games (CDs). Two nets: the literal word
    # "game", OR a known franchise ("Yakuza Kiwami 3 PS5 (2026)" has no word "game").
    if _s(r"""\b(ps[345]|playstation|xbox|nintendo)\b""",t) and not _s(r"""wheel|pedal|add-?on|hub|cockpit|\bstand\b|\bmount\b|\bsim\b|controller|gamepad|joystick|joy.?con|joypad|\bskin\b|\bcover\b|\bcase\b|\bgrip\b|charg|cable|headset|earbud|\bconsole\b|\bssd\b|memory card|micro ?sd|adapter|\bmic\b|webcam|monitor""",t) and (_s(r"""\b(game|games)\b""",t) or bool(GAME_TITLES.search(t)) or _s(r"""\bpegi\b|\besrb\b|(standard|deluxe|launch|day one|gold|ultimate|collector'?s|steelbook|definitive|anniversary) edition""",t)): return 'Games'
    if bool(GAME_TITLES.search(t)) and len(t.strip())<48 and not _s(r"""console|controller|headset|\bskin\b|\bcase\b|poster|figure|\bcable\b|\btoy\b""",t): return 'Games'
    # UPS before anything desktop-ish — "600VA UPS for Desktop PCs" is a UPS, not a PC.
    if (_s(r"""\bups\b|uninterruptible|line[- ]interactive|power backup|\b\d{3,4}\s?va\b""",t)) and not _s(r"""mouse|keyboard|headset|laptop bag|va panel|\bips\b|\bmonitor\b|curved|\bhz\b|\bms\b""",t): return 'UPS'
    # PSUs "for Desktop PC": power-supply words LEADING the title beat the prebuilt rule
    if _s(r"""^.{0,36}(\bsmps\b|\bpsu\b|power supply|\d{3,4}\s?watts?\b)""",t) and not _s(r"""\b(c?i[3579]-?\d|ryzen\s?[3579]|rtx|gtx)\b""",t[:36]): return 'Power Supply'
    # Motherboards before the prebuilt heuristic — spec-sheet titles ("H110, DDR4,
    # NVMe, supports i3/i5/i7") name many parts and would trip buildScore.
    if _s(r"""motherboard|mainboard|\bmobo\b""",t): return 'Motherboard'
    if _s(r"""\b(b[45678]\d0m?e?|x[5678]\d0e?|z[6789]\d0|h[567]\d0)(-[a-z]{1,2})?\b""",t) and _s(r"""wi-?fi|am[45]\b|lga\s?\d|\batx\b|micro-?atx|mini-?itx|q-release|pcie [45]\.0""",t) and not _s(r"""laptops?|notebooks?|\bram\b kit|\bssd\b|graphics card|\bpsu\b|power supply""",t): return 'Motherboard'
    # flash/memory cards live with pen drives, not the Components dump
    if _s(r"""micro ?sdx?c?\b|\bsd card\b|\bsdxc\b|\bsdhc\b|memory card|compact ?flash""",t): return 'Pen Drive'
    # earbuds/TWS/neckbands belong with headsets ("60HRS Playback" = audio tell)
    if _s(r"""earbud|\btws\b|neckband|airdopes|airpods|\bin-ear\b|\d+\s?hrs? playback""",t) and not _s(r"""speaker|soundbar|sound bar|party ?box""",t): return 'Headset'
    # [r21] "GAMING HEADSET ... with Mic" is a headset — the bare ' mic ' keyword must not win
    if _s(r"""headset|headphone""",t) and not _s(r"""\bmicrophone\b|condenser|\bxlr\b|boom arm|podcast mic""",t): return 'Headset'
    # chairs that don't literally say "gaming chair"
    if _s(r"""\bchair\b""",t) and not _s(r"""\bmat\b|cover|cushion for""",t): return 'Gaming Chair'
    # Accessories that merely mention laptop/notebook (adapter, mouse "for laptop",
    # sleeve, webcam...) aren't laptops.
    # components SOLD "for laptops" are components, not laptops:
    # laptop RAM / SODIMMs
    # external/portable drives ("for PC laptop Mac") are drives, not laptops
    if (_s(r"""\b(external|portable)\b.{0,16}\b(hdd|hard ?dis[kc]|hard ?drive)\b|\b(hdd|hard ?drive)\b.{0,10}\b(external|portable)\b""",t)) and not _s(r"""\bssd\b|solid state""",t): return 'HDD'
    if _s(r"""\b(external|portable)\b.{0,16}\bssd\b|\bssd\b.{0,12}\b(external|portable)\b|portable solid state""",t): return 'SSD'
    # all-in-one desktops (24-inch screen + laptop CPU) are desktops, not laptops/monitors
    if _s(r"""all[- ]?in[- ]?one|ideacentre aio|\bimac\b""",t) and not _s(r"""cooler|liquid|printer|print|scan""",t) and (_s(r"""\bc?i[3579]-?\d|\bryzen\b|celeron|pentium|core ultra|core i[3579]""",t) or not _s(r"""\bssd\b|\bnvme\b|solid state|\bram\b|\bddr\d?\b|\bhdd\b|hard drive|graphics|pen ?drive|flash drive""",t)): return 'Desktop PC'
    # [r21] mobile-CPU code + screen/OS evidence = laptop (bracket-spec store titles)
    if _s(r"""(\bc?i[3579]-?\d{4,5}(hx|hs|h|u|p)\b|\br[3579]-?\d{4}(hs|h|u)\b|\bcore\s?[3579]-?\d{3}[uvh]\b|\bultra\s?[3579]-?\d{3}v\b)""",t) and _s(r"""\b\d{2}(\.\d)?\s?("|\u201d|inch|cm)|win\s?1[01]\b|\bdos\b|ms ?office|ms24""",t) and not _s(r"""all[- ]?in[- ]?one|\baio\b|\bimac\b|desktop|tower|\bpc\b|monitor|\bprocessor\b|graphics card""",t): return 'Gaming Laptop'
    if _s(r"""\blaptop ram\b|\bnotebook ram\b|\blaptop memory\b|\bnotebook memory\b|(ram|memory) for (laptop|notebook)|\bsod?imm\b|so-?dimm|\bsdram\b|\bddr[2345]l?\b.{0,16}\bgb\b.{0,30}\b(laptops?|notebooks?)\b""",t) and not _s(r"""\bc?i[3579]-?\d|\bryzen\s?[3579]|core ultra|celeron|pentium|legion|\bloq\b|ideapad|thinkpad|vivobook|zenbook|victus|aspire|inspiron|\bhx\b|win\s?1[01]|\b1[0-9]th gen\b|\bcore\s?[3579]\b|\bnits\b|\b\d\.\d{1,2}\s?kg\b""",t): return 'Memory/RAM'
    # internal/NVMe SSDs listed as laptop/desktop-compatible (real laptops always
    # name a CPU — those are protected by the exclusion)
    if _s(r"""\b(internal|nvme|m\.2|sata) ssd\b|\bssd\b.{0,14}\b(internal|nvme|m\.2)\b""",t) and _s(r"""\b(laptops?|notebooks?)\b""",t) and not _s(r"""\bc?i[3579]-?\d|\bryzen\s?[3579]|\br[3579]-?\d{4}|core ultra|celeron|pentium|athlon|\bhx\b|win\s?1[01]|\b1[0-9]th gen\b|\bcore\s?[3579]\b|\bnits\b|\b\d\.\d{1,2}\s?kg\b""",t): return 'SSD'
    # pastes mentioning laptops ("HY510 ... for laptop CPU")
    if _s(r"""thermal (paste|compound|grease)|heat ?sink (compound|paste)""",t) and _s(r"""\b(laptops?|notebooks?)\b""",t): return 'Thermal Paste'
    # "mouse/keyboard/charger FOR laptop" is a peripheral, not a laptop — suppress
    # the laptop branch below and let the normal rules name the device itself.
    laptopCtx=_s(r"""\b(laptops?|notebooks?|chromebooks?|macbook)\b""",t) and _s(r"""\b(adapters?|chargers?|stylus|sleeves?|bags?|backpacks?|cooling pads?|docking|hubs?|mouse|mice|keyboards?|webcams?|speakers?|headsets?|headphones?|earphones?|mics?|microphones?|lavalier|collar|controllers?|gamepads?|joysticks?|tripods?|skins?|stickers?|tables?|desks?|locks?|pens?|ssds?|nvme|storage|hdds?|flash drives?|pen ?drives?|memory cards?)\b""",t) and not _s(r"""\bc?i[3579]-?\d|\bryzen\s?[3579]|\br[3579]-?\d{4}u?|core ultra|\brtx\b|\bgtx\b|radeon|celeron|pentium|athlon|\bn\d{4}\b|win\s?1[01]|\b1[0-9]th gen\b|\bcore\s?[3579]\b|\bnits\b|\b\d\.\d{1,2}\s?kg\b""",t)
    # Laptops — even with a discrete GPU / mobile CPU — are laptops, not prebuilt desktops.
    # MUST run before the CPU+GPU prebuilt heuristic below or every gaming laptop becomes "Desktop PC".
    # \b\d{3,5}(hx|hs)\b catches mobile CPUs ("13620HX", "ULTRA9-290HX").
    if not laptopCtx and not _s(r"""\b(laptop|notebook) (processors?|cpus?)\b|(processor|cpu) for (laptop|notebook)""",t) and (_s(r"""\b(laptops?|notebooks?)\b""",t) or (_s(r"""\b(vivobook|zenbook|ideapad|thinkpad|thinkbook|legion|\bloq\b|nitro\s?v|predator\s?helios|tuf gaming [af]|rog zephyrus|rog strix g\d|rog flow|\bvictus\b|inspiron|\bxps\b|vostro|\baspire\b|swift\s?\d|\bkatana\b|cyborg|\bmodern\s?\d{2}|galaxy book|macbook|surface (pro|laptop|go|book)|lg gram|thin\s?1[3-8]|\bsword\b|\braider\b|titan\s?1[68]|crosshair\s?1[68]|stealth\s?1[468]|prestige\s?1[46]|creator\s?1[68]|zbook|probook|elitebook|\benvy\b|spectre|chromebook)\b""",t) and not _s(r"""\bmonitor\b|\bmouse\b|(mechanical|gaming|wired|wireless|rgb|membrane) keyboard|keyboard with|headset|headphone|earbud|\bcontroller\b|gamepad|webcam|\bmic\b|microphone|soundbar|pen ?drive|flash drive""",t)) or _s(r"""(?<![a-z]-)\b\d{4,5}(hx|hs)\b|\b\d{3}hx\b""",t) or (_s(r"""\b(core\s?ultra\s?[3579]|core\s?i[3579]|ryzen\s?[3579])\b|\bcore\s?[3579]\b(?=.{0,20}(gen\b|\d{3}[hu]\b|processor))""",t) and _s(r"""\b\d{2}(\.\d)?\s*(inch|cm|")\b""",t) and _s(r"""\b(fhd|wuxga|wqxga|qhd|uhd|\d{2,3}\s?hz|ips|oled)\b""",t) and not _s(r"""\bmonitor\b|gaming pc|desktop pc""",t))): return 'Gaming Laptop'
    # AMD APUs ("Ryzen 5 8600G ... with Radeon Graphics") and any single processor are CPUs,
    # not GPUs or prebuilt PCs — integrated graphics must NOT trigger Desktop/GPU classification.
    if _s(r"""\bprocessor\b""",t) and _s(r"""(ryzen|core\s?i[3579]|core\s?ultra|athlon|threadripper|pentium|celeron|\bxeon\b|\bi[3579][- ]?\d{3,5}\b)""",t) and not _s(r"""(gaming|desktop) pc.{0,26}(with rgb|with \d+\s?gb|featuring|tower|cabinet|full set|complete set)|pre.?built|barebone|\bcombo\b|\bbundle\b|motherboard|mainboard|mini tower|\bcabinet\b""",t): return 'Processor/CPU'
    # Monitors that don't literally say "monitor" (e.g. "27 inch 4K UHD IPS display").
    if (_s(r"""\bmonitor\b""",t) and not _s(r"""speaker|soundbar|full set|complete set""",t)) or (_s(r"""\b\d{3,4}\s?x\s?\d{3,4}\b""",t) and _s(r"""\d{2,3}\s?hz""",t) and _s(r"""cd\/?m|ips|\bva\b|\btn\b|curved|\d ?ms\b""",t) and not _s(r"""laptop|notebook|\btv\b|television""",t)) or (_s(r"""\b\d{2}(\.\d)?\s*(inch|"|\u201d|cm)\b""",t) and _s(r"""\b(ips|va panel|tn panel|oled|qhd|uhd|wqhd|fhd|2k|4k|\d{2,3}\s?hz|curved|gaming display)\b""",t) and not _s(r"""laptop|notebook|\btv\b|television|tablet|projector|core\s?i|\bcore\s?[3579]\b|1[0-9]th gen|ryzen|processor""",t)): return 'Monitor'
    # RAM in hyphen/UDIMM forms the keyword rule misses ("DDR5-5600 UDIMM").
    if _s(r"""\b(ddr[345]-?\d|udimm|so-?dimm)\b""",t) and (_s(r"""\b\d{1,3}\s?gb\b""",t) or _s(r"""\bram\b|\bcl\d\d\b|mhz""",t)) and not _s(r"""\bssd\b|nvme|graphics|laptop|notebook|motherboard|mainboard""",t): return 'Memory/RAM'
    # CPUs bundled "with thermal paste (free)" are CPUs — decide by what LEADS the
    # title: a CPU model up front wins over a paste mention later on.
    if _s(r"""thermal (paste|compound|grease)|\bmx-?[46]\b|kryonaut""",t) and _s(r"""(ryzen\s?[3579]|core\s?i[3579]|core\s?ultra|\bi[3579][- ]?\d{3,5})""",t[:34]): return 'Processor/CPU'
    # paste/compound products (incl. "heat sink compound") — unless it's actually a
    # cooler or CPU that merely bundles paste (both handled above).
    if _s(r"""thermal (paste|compound|grease)|heat ?sink (compound|paste)|\bmx-?[46]\b|kryonaut""",t) and not _s(r"""cooler|freezer|aio|cooling fan|case fan|hyper\s?212|peerless|\bnh-[du]\b|\bfan\b""",t[:32]): return 'Thermal Paste'
    # speakers described as 'for Desktop PC' must not hit the prebuilt rule
    if _s(r"""\b(cabinet|mid tower|full tower|pc case|computer case)\b""",t) and _s(r"""\batx\b|\bitx\b|tempered|tower|side panel|\bchassis\b""",t) and not _s(r"""^.{0,30}\bfans?\b|laptop""",t): return 'PC Case/Chassis'
    if _s(r"""\bspeakers?\b|soundbar|sound bar""",t) and not _s(r"""speaker (stand|mount|wire|cable)|built-?in speaker|integrated speaker|touchpad|controller|gamepad""",t): return 'Speakers'
    # components whose TITLE LEADS with the part ("Crucial T500 ... SSD for Gaming
    # PC") must not be captured by prebuilt words in their compatibility text
    h40 = t[:42]
    if not _s(r"""\bc?i[3579]-?\d|\bryzen\b|core ultra|(?<!for )(gaming|desktop) pc|\btower\b""",h40):
        if _s(r"""graphics card|graphic card|\bgeforce\b|\brtx\s?\d|\bgtx\s?\d|\bradeon\b""",h40): return 'Graphics Card'
        if _s(r"""\bssd\b|\bnvme\b|\bm\.2\b|solid state""",h40): return 'SSD'
        if _s(r"""\bhdd\b|hard ?(disk|drive)""",h40): return 'HDD'
        if _s(r"""\bram\b|\bddr[2345]l?\b|\bdimm\b""",h40): return 'Memory/RAM'
    # peripherals sold "for Desktop PC" are peripherals — the prebuilt words in their
    # compatibility text must not capture them (only when NO cpu model is present)
    if not _s(r"""\bc?i[3579]-?\d|\bi[3579]\b|\bryzen\b|core ultra|celeron|pentium|xeon""",t):
        for pty,pkeys in [['Keyboard',['keyboard']],['Mouse',[' mouse']],['Webcam',['webcam','web cam']],['Microphone',['microphone','condenser mic','usb mic',' mic ']],['Headset',['headset','headphone','earphone']],['Speakers',['speaker','soundbar']],['Pen Drive',['pen drive','pendrive','flash drive','usb drive']]]:
            if any(k in t for k in pkeys): return pty
    hasCpu=_s(r"""(ryzen|core\s+i[3579]|core\s+ultra|threadripper|\bxeon\b|\bultra\s?[3579]\s?\d{3}k?\b|\bc?i[3579]-?\d{4,5}[a-z]{0,2}\b)""",t)
    hasGpu=_s(r"""(\brtx\s?\d|\bgtx\s?\d|geforce|radeon\s?rx(?!\s?vega)|\brx\s?[5-9]\d{3}|arc\s?a\d)""",t)
    # prebuilt detection BEFORE component matching: explicit words, CPU+GPU, or 3+ parts.
    # [r19] bare DDR DIMM/UDIMM modules ("DIMM Desktop PC Module") are RAM, not prebuilts
    if _s(r"""\b(u|so-?)?dimm\b(?!\s*slots?)""",t) and _s(r"""\bddr[2345]l?\b""",t) and not _s(r"""motherboard|mainboard""",t): return 'Memory/RAM'
    if _s(r"""(gaming pc(?! (processor|cpu|memory|module|ram|dimm))|desktop pc(?! (processor|cpu|memory|module|ram|dimm))|pre-?built|gaming desktop(?! (processor|cpu|memory|module|ram|dimm))|\bpc build\b|barebone|\bworkstation\b|super ?computer)""",t) or (hasCpu and hasGpu) or buildScore(t)>=3: return 'Desktop PC'
    for ty,keys in TYPE_RULES:
        if laptopCtx and ty=='Gaming Laptop': continue
        if any(k in t for k in keys): return ty
    return 'Components'
# fmt: on


def model_key(title):
    """Seller-stable key: model numbers, variant suffixes and (for GPUs/boards) the model line."""
    t = " " + _DOTS.sub(" ", str(title).lower()) + " "
    is_gpu = _s(r"\b(rtx|gtx|arc)\s*\d|\brx\s*\d{3,4}|\bgeforce\b|\bradeon\b", t)
    keep_aib = is_gpu or _s(r"\bmotherboard\b|\bmainboard\b|\b[abxzh]\d{3}e?m?\b", t)
    t = re.sub(r"(\d{3,4})\s*(ti|super|xtx|xt|gre)\b", r"\1\2", t, flags=A)
    t = re.sub(r"(\d+)\s*(gb|tb)\b", r"\1\2", t, flags=A)
    t = re.sub(r"\bddr\s*([2345])\b", r"ddr\1", t, flags=A)
    t = _NONALNUM.sub(" ", t)
    tk = [x for x in t.split(" ") if 2 <= len(x) <= 16 and (
        (keep_aib and x in KEY_AIB) or (x not in KEY_STOP and (_s(r"\d", x) or x in KEY_VARIANT)))]
    if is_gpu:
        tk = [x for x in tk if not _s(r"^\d{1,3}gb$", x) and not x.startswith("gddr")]
    return "-".join(sorted(set(tk)))[:90]


# Key parts that say what size or kind a thing is, not which model it is: "120mm", "1tb", "16gb", "v2", "1080p", "ps5".
_VAGUE = re.compile(r"^(\d+(\.\d+)?(mm|cm|mb|gb|tb|kg|hz|mhz|ghz|rpm|mah|pcs|inch|ft|ml|mbps|gbps|db|w)|\d{1,3}g|v\d+|\d{3,4}p|[248]k"
                    r"|(19|20)\d\d|ps[1-5]|usb\d?|ddr\d|gddr\d|wifi\d|\d)$")
# Words that describe the kind of product rather than name it, left out when a name is needed to tell parts apart.
_DESC = frozenset("""cpu gpu air cooler cooling liquid fan fans case cabinet chassis tower mid full atx matx itx eatx micro mini gaming gamer
    wireless wired bluetooth usb black white red blue grey gray silver pink green purple yellow orange rgb argb led mouse mice keyboard
    mechanical optical headset headphone headphones earphones earbuds mic microphone speaker speakers computer desktop laptop monitor
    edition series new original pack combo set kit cable adapter portable external internal solid state drive ssd hdd hard disk memory ram
    power supply psu modular fully semi bronze gold platinum titanium rated certified processor motherboard card graphics thermal paste
    compound grease chair office ergonomic adjustable heatsink heat sink single dual stand cover dust protective premium high quality
    compatible support supports universal multi purpose type pad mat large extended size inch display screen gamepad controller console
    accessories accessory wifi router network udimm dimm sodimm nvme sata gen light dark""".split())
# Sizes that read like model numbers: fan and radiator millimetres, screen lines.
_SIZE_NUMBERS = frozenset(["120", "140", "240", "280", "360", "420", "480", "720", "1080", "1440", "2160"])


def _vague_key(key, branded):
    """True when nothing in the key names a model: no part like "rm750" or "x870", and no bare number with a known brand."""
    for t in str(key or "").split("-"):
        if not t or _VAGUE.match(t):
            continue
        if re.search(r"[a-z]", t) and re.search(r"\d", t):
            return False
        if re.fullmatch(r"\d{3,5}", t) and t not in _SIZE_NUMBERS and (branded or len(t) >= 4):
            return False
    return True


def _name_words(title, brand, key=""):
    """Up to three words that name the product ("assassin", "kryonaut"), sorted so word order between stores does not matter.
    Part codes are left out: one store prints them and the next does not."""
    skip = set(_NONALNUM.sub(" ", str(brand or "").lower()).split()) | set(str(key).split("-"))
    out = []
    for w in _NONALNUM.sub(" ", str(title or "").lower()).split():
        if len(w) < 3 or w in KEY_STOP or w in _DESC or w in skip or re.search(r"\d", w) or w in out:
            continue
        out.append(w)
        if len(out) == 3:
            break
    return sorted(out)


def group_id(brand, mk, title, category):
    """Same part from any seller -> same id; different parts -> different ids."""
    key = str(mk or "")
    if len(re.sub(r"[^a-z0-9]", "", key, flags=re.I)) < 3:
        words = _NONALNUM.sub(" ", _DOTS.sub(" ", str(title or "").lower())).split(" ")
        key = "-".join([x for x in words if len(x) >= 3 and x not in KEY_STOP][:6])
    elif _vague_key(key, str(brand or "Generic") != "Generic"):
        # "120mm" or "pro" alone would put every brand's 120 mm cooler or "Pro" keyboard on one page.
        key = "-".join([key] + _name_words(title, brand, key))
    base = _NONALNUM.sub("-", (str(category or "") + "-" + str(brand or "") + "-" + key).lower()).strip("-")
    clean = re.sub(r"-?generic-?", "-", base, count=1).strip("-")
    return clean or _NONALNUM.sub("-", str(title or "").lower()).strip("-")[:48]


def recategorize(title, category, gid, brand=None):
    """Category and group id for a stored offer under the current rules: None when it is not a PC product any more.
    Usually only the category part of the id changes ("motherboard-..." to "desktop-pc-..."), so the rest stays as it was
    made. An id built from a vague key ("120mm", "pro") is made again, so unrelated parts stop sharing one page."""
    new = type_of(title)
    if new == "Other":
        return None
    if brand is not None:
        b = "Generic" if not brand or brand in _LATE_NAMES else brand
        mk = model_key(title)
        if len(re.sub(r"[^a-z0-9]", "", mk)) >= 3 and _vague_key(mk, b != "Generic"):
            fresh = group_id(b, mk, title, new)
            if fresh != gid:
                return new, fresh
    if new == category:
        return category, gid
    old_prefix = _NONALNUM.sub("-", str(category or "").lower()).strip("-")
    new_prefix = _NONALNUM.sub("-", new.lower()).strip("-")
    gid = str(gid or "")
    return new, (new_prefix + gid[len(old_prefix):] if old_prefix and gid.startswith(old_prefix) else gid)


def specs_of(title, category):
    """Compatibility facts readable from the title (socket, RAM type, form factor, wattage)."""
    raw = str(title or "")
    t = " " + raw.lower() + " "
    specs = {}
    m = re.search(r"ryzen\s*[3579]\s*(\d)\d{3}", t, A)
    if "threadripper" in t:
        specs["socket"] = "sTR5" if _s(r"\b[79]\d{3}\b", t) else "sTRX4"
    elif m:
        specs["socket"] = "AM5" if m.group(1) >= "7" else "AM4"
    elif _s(r"core\s*ultra", t):
        specs["socket"] = "LGA1851"
    else:
        m = re.search(r"\bi[3579]-?\s*(\d{2})\d{2,3}", raw, A | re.I)
        if m:
            g = int(m.group(1))
            if 12 <= g <= 14: specs["socket"] = "LGA1700"
            elif g in (10, 11): specs["socket"] = "LGA1200"
            elif g in (8, 9): specs["socket"] = "LGA1151"
    cm = re.search(r"\b([ABXZHW]\d{3}E?|WRX\d0|TRX\d0)\b", raw, A | re.I)
    chip = cm.group(1).upper() if cm else None
    ref = MB_CHIPSETS.get(chip) if chip else None
    if ref:
        specs["chipset"] = chip
        specs.setdefault("socket", ref[0])
    if "ddr5" in t: specs["ram_type"] = "DDR5"
    elif "ddr4" in t: specs["ram_type"] = "DDR4"
    elif ref: specs["ram_type"] = ref[1]
    if _s(r"mini[- ]itx|\bitx\b|\b[abxzhw]\d{3}e?-i\b", t): specs["form_factor"] = "Mini-ITX"
    elif _s(r"micro[- ]atx|\bm[- ]?atx\b|matx|\b[abxzhw]\d{3}e?m\b", t): specs["form_factor"] = "Micro-ATX"
    elif _s(r"\be[- ]?atx\b", t): specs["form_factor"] = "E-ATX"
    elif _s(r"\batx\b", t): specs["form_factor"] = "ATX"
    elif category == "Motherboard": specs["form_factor"] = "ATX"
    if category == "Motherboard" and ref:
        ff = specs.get("form_factor")
        specs["ram_slots"] = 2 if ff == "Mini-ITX" else (8 if ff == "E-ATX" else 4)
        m2 = M2_BY_TIER.get(ref[2]) or 2
        specs["m2_slots"] = min(m2, 2) if ff == "Mini-ITX" else m2
        hi = ref[2] == "high"
        specs["pcie_x16"] = 1 if ff == "Mini-ITX" else ((2 if hi else 1) if ff == "Micro-ATX" else (3 if hi else 2))
    wm = re.search(r"(\d{3,4})\s*w(att)?\b", t, A)
    if wm and category == "Power Supply": specs["wattage"] = int(wm.group(1))
    tm = re.search(r"\btdp[:\s]*(\d{2,3})\s*w", t, A)
    if tm: specs["tdp"] = int(tm.group(1))
    return specs


_ASIN = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})")
_KEEP_QUERY = {"flipkart.com": ("pid",), "theitdepot.com": ("route", "product_id")}


def canonical_url(url):
    """One URL per listing: lower-case host, no tracking parameters, no fragment."""
    u = urlsplit(str(url or "").strip())
    host = u.netloc.lower()
    if "amazon." in host:
        m = _ASIN.search(u.path)
        if m:
            return f"https://{host}/dp/{m.group(1)}"
    out = f"{(u.scheme or 'https').lower()}://{host}{u.path}"
    for dom, keys in _KEEP_QUERY.items():
        if host.endswith(dom):
            q = parse_qs(u.query)
            kept = "&".join(f"{k}={q[k][0]}" for k in keys if k in q)
            if kept:
                out += "?" + kept
    return out


_LATE_BRANDS = (("EVM", "EVM"), ("CONSISTENT", "Consistent"), ("CONSISTEN", "Consistent"), ("SIMMTRONICS", "Simmtronics"), ("FRONTECH", "Frontech"), ("ZEBRONICS", "Zebronics"))
_LATE_NAMES = frozenset(name for _, name in _LATE_BRANDS)


def _late_brand(title):
    t = " " + re.sub(r"[^A-Z0-9]+", " ", str(title or "").upper()) + " "
    return next((name for key, name in _LATE_BRANDS if " " + key + " " in t), "")


def _canon_brand(raw_brand, title):
    if raw_brand and str(raw_brand).strip():
        rb = str(raw_brand).strip()
        return brand_of(rb) or BRAND_CANON.get(rb.upper()) or brand_of(title) or _title_case(rb)
    return brand_of(title)


def normalize(raw, store):
    """Raw adapter offer -> clean offer dict, or None when it is not a usable PC product."""
    if not raw:
        return None
    title = re.sub(r"^sponsored\s+", "", _WS.sub(" ", str(raw.get("title") or "")), flags=re.I).strip()
    if not title or len(title) < 6 or not _s(r"[a-z]{3}", title, re.I):
        return None
    if JUNK.search(title) or JUNK_TITLE.search(title) or NON_PC.search(title):
        return None
    price = parse_price(raw.get("price"))
    mrp_raw = raw.get("mrp")
    mrp = parse_price(mrp_raw if mrp_raw is not None else raw.get("price"))
    category = type_of(title)
    if category == "Other":
        return None
    if price > PRICE_CAP.get(category, 2500000):
        return None
    price, mrp = price or mrp, mrp or price
    url = str(raw.get("url") or "").strip()
    if price <= 0 or not url:
        return None
    brand = _canon_brand(raw.get("brand"), title)
    if category == "PlayStation": brand = "Sony"
    elif category == "Xbox": brand = "Microsoft"
    elif category == "Nintendo": brand = "Nintendo"
    brand = brand or "Generic"
    mk = model_key(title)
    gid = group_id(brand, mk, title, category)
    # Brands added after launch name the part on the site but stay out of the group id, so existing part addresses keep working.
    if brand == "Generic":
        brand = _late_brand(title) or brand
    in_stock = raw.get("in_stock")
    return {
        "store": store, "url": canonical_url(url), "title": title, "price": price, "mrp": mrp,
        "in_stock": True if in_stock is None else bool(in_stock), "image": raw.get("image") or "",
        "brand": brand, "category": category, "model_key": mk,
        "group_id": gid, "specs": specs_of(title, category),
    }
