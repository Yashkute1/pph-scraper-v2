import pytest
from pph.facets import facets_of


@pytest.mark.parametrize("title,category,specs,want", [
    ("ASUS Dual GeForce RTX 5060 Ti 16GB GDDR7 OC Edition", "Graphics Card", {}, {"series": "RTX 5060 Ti", "memory": "16 GB"}),
    ("Sapphire Pulse Radeon RX 7800 XT 16 GB", "Graphics Card", {}, {"series": "RX 7800 XT", "memory": "16 GB"}),
    ("Zotac GeForce RTX 4070 SUPER Twin Edge 12GB", "Graphics Card", {}, {"series": "RTX 4070 Super", "memory": "12 GB"}),
    ("Intel Arc B580 Limited Edition 12GB", "Graphics Card", {}, {"series": "Arc B580", "memory": "12 GB"}),
    ("MSI GT 710 2GB", "Graphics Card", {}, {"series": "GT 710", "memory": "2 GB"}),
    ("Some unbranded display adapter", "Graphics Card", {}, {}),
    ("AMD Ryzen 5 5600 Processor", "Processor/CPU", {"socket": "AM4"}, {"series": "Ryzen 5", "socket": "AM4"}),
    ("Intel Core i5-12400F", "Processor/CPU", {"socket": "LGA1700"}, {"series": "Core i5", "socket": "LGA1700"}),
    ("Intel Core Ultra 7 265K", "Processor/CPU", {"socket": "LGA1851"}, {"series": "Core Ultra 7", "socket": "LGA1851"}),
    ("MSI B650M Gaming WiFi", "Motherboard", {"socket": "AM5", "chipset": "B650", "form_factor": "Micro-ATX", "ram_type": "DDR5", "m2_slots": 2},
     {"socket": "AM5", "chipset": "B650", "form_factor": "Micro-ATX", "ram_type": "DDR5"}),
    ("Corsair Vengeance 32GB (2x16GB) DDR5 6000MHz", "Memory/RAM", {"ram_type": "DDR5"}, {"capacity": "32 GB", "ram_type": "DDR5"}),
    ("Samsung 990 Pro 2TB NVMe M.2 SSD", "SSD", {}, {"capacity": "2 TB"}),
    ("WD Blue 500 GB SATA SSD", "SSD", {}, {"capacity": "500 GB"}),
    ("Seagate Barracuda 4TB HDD", "HDD", {}, {"capacity": "4 TB"}),
    ("Corsair RM750e 750W 80 Plus Gold", "Power Supply", {"wattage": 750}, {"wattage": "750 W", "rating": "80+ Gold"}),
    ("Deepcool PF450 450W", "Power Supply", {"wattage": 450}, {"wattage": "450 W"}),
    ('LG UltraGear 27GS75Q 27 inch QHD 180Hz', "Monitor", {}, {"size": "27 inch", "refresh": "180 Hz"}),
    ('BenQ GW2490 23.8" IPS 100 Hz', "Monitor", {}, {"size": "24 inch", "refresh": "100 Hz"}),
    ("Logitech G102 mouse", "Mouse", {}, {}),
    (None, "SSD", None, {}),
])
def test_facets(title, category, specs, want):
    assert facets_of(title, category, specs) == want
