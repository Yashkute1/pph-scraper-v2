"""Same product, different stores' titles -> one page. Real titles from the live catalogue (October 2026)."""
from pph.merge import codes, merge_map


def page(gid, title, price, category, brand):
    return {"group_id": gid, "title": title, "price": price, "category": category, "brand": brand}


def joined(*offers):
    return merge_map(list(offers))


def test_codes_skip_sizes_specs_and_certificates():
    assert codes("Crucial P3 Plus 1TB PCIe 4.0 3D NAND NVMe M.2 SSD (CT1000P3PSSD8)") == {"ct1000p3pssd8"}
    assert codes("Shoptron SN8025V12 DC Cooling Fan, 80x80x25mm, 12V 0.25A") == {"sn8025v12"}
    assert not codes("ANT ESPORTS MKWM2023 WIRELESS COMBO R-41211141, ETA-SD-20221009067") - {"mkwm2023"}
    assert not codes("ACER NITRO V15 [CI7-13620H/16GB/512GB SSD/15.6\"/8GB-RTX5050 GRAPHICS] 44000DPI LGA1155")


def test_same_ssd_from_three_stores_is_one_page():
    m = joined(page("ssd-crucial-1tb-2280-ct1000p3pssd8-p3-plus", "Crucial P3 Plus 1TB PCIe M.2 2280 SSD (CT1000P3PSSD8)", 16960, "SSD", "Crucial"),
               page("ssd-crucial-1tb-3d-ct1000p3pssd8-p3-plus", "Crucial P3 Plus 1TB PCIe 4.0 3D NAND NVMe M.2 SSD CT1000P3PSSD8", 15999, "SSD", "Crucial"),
               page("ssd-crucial-1tb-ct1000p3pssd8-p3-plus", "CRUCIAL P3 PLUS 1TB M.2 NVME PCIE GEN 4.0 INTERNAL SSD (CT1000P3PSSD8)", 17000, "SSD", "Crucial"))
    assert set(m) == {"ssd-crucial-1tb-2280-ct1000p3pssd8-p3-plus", "ssd-crucial-1tb-3d-ct1000p3pssd8-p3-plus"}
    assert set(m.values()) == {"ssd-crucial-1tb-ct1000p3pssd8-p3-plus"}


def test_short_model_name_needs_close_prices():
    a = page("power-supply-ant-esports-450-vs450l", "Ant Esports VS450L - 450 Watt Non-Modular Power Supply", 2000, "Power Supply", "Ant Esports")
    b = page("power-supply-ant-esports-vs450l", "Ant Esports VS450L SMPS", 2010, "Power Supply", "Ant Esports")
    assert joined(a, b) == {"power-supply-ant-esports-450-vs450l": "power-supply-ant-esports-vs450l"}
    assert joined(a, dict(b, price=2600)) == {}


def test_cards_with_different_memory_or_lines_stay_apart():
    g16 = page("gpu-a", "Gigabyte RTX 4060 Ti Gaming OC 16GB Graphic Card GV-N406TGAMING OC-16GD", 56022, "Graphics Card", "Gigabyte")
    g8 = page("gpu-b", "Gigabyte RTX 4060 Ti Gaming OC 8GB Graphic Card GV-N406TGAMING OC-8GD", 40501, "Graphics Card", "Gigabyte")
    elite = page("gpu-c", "Gigabyte AORUS GeForce RTX 4070 Ti ELITE 12G Graphic Card GV-N407TAORUS E-12GD", 99122, "Graphics Card", "Gigabyte")
    master = page("gpu-d", "Gigabyte AORUS GeForce RTX 4070 Ti MASTER 12G Graphic Card GV-N407TAORUS M-12GD", 79749, "Graphics Card", "Gigabyte")
    assert joined(g16, g8) == {} and joined(elite, master) == {}


def test_laptops_join_only_on_a_full_sku_with_the_same_config():
    a = page("lap-a", "LENOVO LOQ 83JE00U4IN [CI7-13700HX/16GB/1TB SSD/WIN11 HOME/15.6\"/8GB-RTX5060]", 187990, "Gaming Laptop", "Lenovo")
    b = page("lap-b", "LENOVO LOQ 83JE00U7IN [CI7-13700HX/16GB/1TB SSD/WIN11 HOME/15.6\"/8GB-RTX5050]", 140990, "Gaming Laptop", "Lenovo")
    c = page("lap-c", "Lenovo LOQ 83JE00U4IN Core i7 13700HX 16GB 1TB RTX 5060", 179990, "Gaming Laptop", "Lenovo")
    assert joined(a, b) == {}
    assert joined(a, c) == {"lap-c": "lap-a"}


def test_console_bundles_and_sizes_stay_apart():
    plain = page("ps-a", "SONY PS5 Console Digital (Slim) CFI-2008B01 1024 GB", 49990, "PlayStation", "Sony")
    cod = page("ps-b", "SONY PS5 Console Digital (Slim) CFI-2008B01 1 TB with Call of Duty Black OPS6", 49990, "PlayStation", "Sony")
    again = page("ps-c", "Sony PS5 Digital Slim Console CFI-2008B01 1TB", 50990, "PlayStation", "Sony")
    assert joined(plain, cod) == {}
    assert joined(plain, again) == {"ps-c": "ps-a"}


def test_different_brands_never_join():
    a = page("mon-a", "Samsung 27 inch Monitor LS27C310EAWXXL", 12100, "Monitor", "Samsung")
    b = page("mon-b", "Generic stand for LS27C310EAWXXL", 12000, "Monitor", "Generic")
    c = page("mon-c", "Acer 27 inch LS27C310EAWXXL", 12000, "Monitor", "Acer")
    assert joined(a, c) == {}
    assert joined(a, b) == {"mon-b": "mon-a"}     # a listing with no brand can join a branded one on a long code
