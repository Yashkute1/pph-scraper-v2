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


# fmt: off
def type_of(title):
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
        or (_s(r"""\b\d{3,4}\s?x\s?\d{3,4}\b""",t) and _s(r"""\d{2,3}\s?hz""",t)))
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
    if _s(r"""\bdistro\b|water ?block|\breservoir\b|pump[- ]?res|hydro x|hardline|soft tubing|\bfittings?\b.{0,10}mm""",t): return 'Fans & Cooling'
    if _s(r"""wave xlr|audio interface|\bgo xlr\b""",t): return 'Microphone'
    if _s(r"""next level racing|racing seat|\bnlr\b""",t): return 'Gaming Accessories'
    if (_s(r"""\b(case|cabinet|computer case) fans?\b""",t) or _s(r"""(cooling|dc|brushless) fans?\b.{0,20}(pc case|cabinet|cpu)|\bbrushless\b.{0,12}fan|\baxial\b.{0,24}cooling|cooling device""",t)) and not _s(r"""(mid|full|mini) tower|tempered glass|side panel""",t): return 'Fans & Cooling'
    if _s(r"""^.{0,40}(cpu cooler|air cooler|tower cooler|liquid cooler|aio cooler)""",t): return 'Fans & Cooling'
    # streaming gear & mobile-gaming add-ons
    if _s(r"""stream deck|capture device|chat link|green screen|key light|ring light|gaming trigger|\bpubg\b|\bbgmi\b""",t) and not _s(r"""graphics card|\bgpu\b|\bram\b|\bssd\b|processor|motherboard|\bmonitor\b""",t): return 'Gaming Accessories'
    # network gear that says "switch" (never Nintendo Switch)
    if _s(r"""(network|ethernet|gigabit|desktop|poe|managed|unmanaged|\d+[- ]?port) switch""",t) and not _s(r"""nintendo""",t): return 'Networking'
    # NAS boxes are network storage, not desktops
    if _s(r"""\bnas\b|network[- ]attached storage""",t): return 'Networking'
    # office/home items PC stores also sell — 'Other' is dropped by normalize()/regroup
    if _s(r"""\bprinter\b|photocopier|\bscanner\b|\btoner\b|ink (tank|cartridge)|air purifier|water purifier|\bhepa\b|vacuum cleaner|\bprojector\b|\btablet\b|smart ?watch|antivirus|extension board|surge (cube|protector)|spike guard|power strip|travel adapter|car charger|power bank|electricity sav|id card|pvc card|laser pointer|wireless presenter|\bpure air\b|\binverter\b|smart notebook|syncpen|\bsmart pen\b|digital notepad|writing (pad|tablet)""",t): return 'Other'
    # digital goods (subscriptions, gift cards, game-pass) are NOT physical games or consoles
    if _s(r"""game ?pass|membership|subscription|gift card|gift voucher|e-?gift|top.?up|live gold|psn (wallet|card|credit)|prepaid|redeem code|wallet code|digital code""",t) and not _s(r"""rog\s*(xbox\s*)?ally|steam ?deck|legion go|msi claw""",t): return 'Gaming Accessories'
    # Sim-racing / flight gear is console-compatible but a PC peripheral -> Gaming Accessories.
    if _s(r"""racing wheel|sim racing|\bpedals?\b|\bshifter\b|handbrake|cockpit|wheel base|wheel stand|\bhotas\b|flight stick|sidestick|\bjoystick\b|playseat|fanatec|\bmoza\b|sim hub|wheel add|gear ?shift|sequential shifter|wheel mount|racing clamp""",t): return 'Gaming Accessories'
    # cheap retro "game stick"/emulator boxes are NOT real consoles — keep them out of the brand tabs
    if not _s(r"""nintendo|switch lite|steam ?deck|rog\s*(xbox\s*)?ally|legion go|msi claw""",t) and _s(r"""game stick|retro gam(e|ing)|retro handheld|handheld gaming console|game system|play system|tv video game|\d{2,}\s?in\s?1\b.{0,24}games?|built[- ]?in (classic )?game|\d{3,}\s*(in|\+)?\s*(built|classic|retro|video)?\s*(video )?games?|game box|gamesoul|emulator""",t): return 'Gaming Accessories'
    # handheld gaming PCs (ROG Ally, Legion Go, Steam Deck) are PCs, not consoles
    if _s(r"""rog\s*(xbox\s*)?ally|legion go|steam ?deck|msi claw""",t) and not _s(r"""headset|headphone|earbud|\bcontroller\b|gamepad|mouse|keyboard|\bcase\b|\bskin\b|charger|\bdock\b|dongle|\bcable\b|\bgrip\b|\bstand\b|memory card|micro ?sd|upgrade kit|\bfor (the )?(rog|ally|steam ?deck|legion)\b|screen protector|tempered""",t): return 'Gaming Laptop'
    # PS5/console disc drives & blu-ray add-ons are accessories, not the console itself
    if _s(r"""\bdisc drive\b|\bdisk drive\b|blu-?ray drive""",t): return 'Gaming Accessories'
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
    if _s(r"""\bemulator\b|\bgamesoul\b|open source game console|retro (old )?(video )?game|revisit childhood|\d+\s?\+?\s*(in\s?1|emulators?)\b|built-?in\s+(games|classic)""",t): return 'Gaming Accessories'
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
    if _s(r"""earbud|\btws\b|neckband|airdopes|airpods|\bin-ear\b|\d+\s?hrs? playback""",t): return 'Headset'
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
    if not laptopCtx and not _s(r"""\b(laptop|notebook) (processors?|cpus?)\b|(processor|cpu) for (laptop|notebook)""",t) and (_s(r"""\b(laptops?|notebooks?)\b""",t) or (_s(r"""\b(vivobook|zenbook|ideapad|thinkpad|thinkbook|legion|\bloq\b|nitro\s?v|predator\s?helios|tuf gaming [af]|rog zephyrus|rog strix g\d|rog flow|\bvictus\b|inspiron|\bxps\b|vostro|\baspire\b|swift\s?\d|\bkatana\b|cyborg|\bmodern\s?\d{2}|galaxy book|macbook|surface (pro|laptop|go|book)|lg gram|thin\s?1[3-8]|\bsword\b|\braider\b|titan\s?1[68]|crosshair\s?1[68]|stealth\s?1[468]|prestige\s?1[46]|creator\s?1[68]|zbook|probook|elitebook|\benvy\b|spectre|chromebook)\b""",t) and not _s(r"""\bmonitor\b|\bmouse\b|(mechanical|gaming|wired|wireless|rgb|membrane) keyboard|keyboard with|headset|headphone|earbud|\bcontroller\b|gamepad|webcam|\bmic\b|microphone|soundbar|pen ?drive|flash drive""",t)) or _s(r"""\b\d{3,5}(hx|hs)\b""",t) or (_s(r"""\b(core\s?ultra\s?[3579]|core\s?i[3579]|ryzen\s?[3579])\b|\bcore\s?[3579]\b(?=.{0,20}(gen\b|\d{3}[hu]\b|processor))""",t) and _s(r"""\b\d{2}(\.\d)?\s*(inch|cm|")\b""",t) and _s(r"""\b(fhd|wuxga|wqxga|qhd|uhd|\d{2,3}\s?hz|ips|oled)\b""",t) and not _s(r"""\bmonitor\b|gaming pc|desktop pc""",t))): return 'Gaming Laptop'
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
    hasGpu=_s(r"""(\brtx\s?\d|\bgtx\s?\d|geforce|radeon\s?rx|\brx\s?[5-9]\d{3}|arc\s?a\d)""",t)
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


def group_id(brand, mk, title, category):
    """Same part from any seller -> same id; different parts -> different ids."""
    key = str(mk or "")
    if len(re.sub(r"[^a-z0-9]", "", key, flags=re.I)) < 3:
        words = _NONALNUM.sub(" ", _DOTS.sub(" ", str(title or "").lower())).split(" ")
        key = "-".join([x for x in words if len(x) >= 3 and x not in KEY_STOP][:6])
    base = _NONALNUM.sub("-", (str(category or "") + "-" + str(brand or "") + "-" + key).lower()).strip("-")
    clean = re.sub(r"-?generic-?", "-", base, count=1).strip("-")
    return clean or _NONALNUM.sub("-", str(title or "").lower()).strip("-")[:48]


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
    in_stock = raw.get("in_stock")
    return {
        "store": store, "url": canonical_url(url), "title": title, "price": price, "mrp": mrp,
        "in_stock": True if in_stock is None else bool(in_stock), "image": raw.get("image") or "",
        "brand": brand, "category": category, "model_key": mk,
        "group_id": group_id(brand, mk, title, category), "specs": specs_of(title, category),
    }
