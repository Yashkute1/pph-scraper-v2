from pph.benchmarks import build_lookup, match

DOCS = [
    {"bucket": "CPU", "brand": "AMD", "model": "Ryzen 5 5600", "score": 88.4, "percentile": 71, "rank": 60, "samples": 9000},
    {"bucket": "CPU", "brand": "AMD", "model": "Ryzen 5 5600X", "score": 89.9, "percentile": 73, "rank": 51, "samples": 99000},
    {"bucket": "CPU", "brand": "Intel", "model": "Core i5-12400F", "score": 91.0, "percentile": 75, "rank": 44, "samples": 50000},
    {"bucket": "GPU", "brand": "Nvidia", "model": "RTX 5060", "score": 120.0, "percentile": 60, "rank": 30, "samples": 4000},
    {"bucket": "GPU", "brand": "Nvidia", "model": "RTX 5060-Ti", "score": 150.0, "percentile": 70, "rank": 20, "samples": 3000},
    {"bucket": "GPU", "brand": "Nvidia", "model": "RTX 4070 S (Super)", "score": 190.0, "percentile": 85, "rank": 9, "samples": 800},
    {"bucket": "GPU", "brand": "Asus", "model": "RTX 4070 Super Dual", "score": 188.0, "percentile": 84, "rank": 10, "samples": 100},
    {"bucket": "GPU", "brand": "AMD", "model": "RX 7800-XT", "score": 170.0, "percentile": 80, "rank": 14, "samples": 2000},
    {"bucket": "SSD", "brand": "Samsung", "model": "990 Pro M.2 2TB", "score": 400.0, "percentile": 97, "rank": 3, "samples": 700},
]
L = build_lookup(DOCS)


def test_cpu_matches_its_own_row():
    b = match("AMD Ryzen 5 5600 Desktop Processor (6 Core, AM4)", "Processor/CPU", L)
    assert (b["model"], b["score"], b["rank"], b["total"], b["bucket"]) == ("Ryzen 5 5600", 88.4, 60, 3, "CPU")


def test_longer_cpu_key_wins():
    assert match("AMD Ryzen 5 5600X Processor", "Processor/CPU", L)["model"] == "Ryzen 5 5600X"


def test_intel_key():
    assert match("Intel Core i5 12400F 12th Gen", "Processor/CPU", L)["model"] == "Core i5-12400F"


def test_ti_card_does_not_match_base_row():
    assert match("ASUS Dual GeForce RTX 5060 Ti 16GB GDDR7 OC", "Graphics Card", L)["model"] == "RTX 5060-Ti"
    assert match("MSI RTX 5060 Ventus 2X OC 8GB", "Graphics Card", L)["model"] == "RTX 5060"


def test_super_shorthand_and_most_samples_wins():
    assert match("Zotac RTX 4070 Super Twin Edge 12GB", "Graphics Card", L)["model"] == "RTX 4070 S (Super)"


def test_xt_suffix():
    assert match("Sapphire Pulse Radeon RX 7800 XT 16GB", "Graphics Card", L)["model"] == "RX 7800-XT"


def test_ssd_series_and_capacity():
    assert match("Samsung 990 Pro 2TB NVMe Internal SSD", "SSD", L)["model"] == "990 Pro M.2 2TB"
    assert match("Samsung 990 Pro 1TB NVMe Internal SSD", "SSD", L) is None


def test_unknown_category_or_no_match():
    assert match("Corsair K70 keyboard RTX 5060", "Keyboard", L) is None
    assert match("AMD Ryzen 7 9800X3D", "Processor/CPU", L) is None
    assert match("", "Processor/CPU", L) is None
    assert match("AMD Ryzen 5 5600", "Processor/CPU", None) is None


def test_bad_rows_are_skipped():
    assert build_lookup([{"bucket": "CPU", "model": "", "score": 1}, {"bucket": "CPU", "model": "Ryzen 5 5600"}]) == {"CPU": []}


def test_ti_title_is_not_given_the_base_score_when_no_ti_row_exists():
    only_base = build_lookup([d for d in DOCS if d["model"] == "RTX 5060"])
    assert match("ASUS Dual GeForce RTX 5060 Ti 16GB", "Graphics Card", only_base) is None
    only_5600 = build_lookup([d for d in DOCS if d["model"] == "Ryzen 5 5600"])
    assert match("AMD Ryzen 5 5600X Processor", "Processor/CPU", only_5600) is None


def test_suffix_words_far_from_the_number_are_ignored_in_titles():
    assert match("MSI GeForce RTX 5060 Gaming Trio 8GB with Super Alloy Power II", "Graphics Card", L)["model"] == "RTX 5060"
