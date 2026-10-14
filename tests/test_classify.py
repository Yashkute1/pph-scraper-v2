"""Category rules, pinned with real store titles that were filed in the wrong place before October 2026."""
import pytest

from pph.normalize import type_of

CASES = [
    # whole computers and board + CPU + memory kits are not motherboards, processors or graphics cards
    ("CHIST Gaming Desktop PC – AMD Ryzen 5 5600 Processor | 32GB DDR4 3200MHz RAM | 512GB NVMe SSD | B450 Motherboard | 650W 80+ Bronze Power Supply", "Desktop PC"),
    ("H61 Motherboard Combo Kit with Core i3 3rd Gen 3.30GHz | 4GB DDR3 RAM | CPU Fan | LGA1155 ATX Desktop Motherboard Processor Combo", "Desktop PC"),
    ("CPU WALA Core i5 8500 Combo Kit + 16GB DDR4 RAM 8th Gen CPU LGA1151Socket Micro-ATX Intel H310 Chipset DDR4 Motherboard for Desktop", "Desktop PC"),
    ("ShopSmart Core™ i7-2600 Quad Core Processor [JWO-N5] Core™ i7 - 2600 Processor | Gaming PC | RGB-Majesty-N5 (8 GB RAM/Intel UHD 2000 Graphics/1 TB HDD)", "Desktop PC"),
    ("SymX RS3 ( Intel i5 12400F / NVIDIA RTX 3050 8GB / 16GB RAM DDR4 / 500GB M.2 NVME Gen4 SSD ) Custom PC Build ( For Flight Simulator & Racing", "Desktop PC"),
    ("Magnus | i7 14700K/32GB 6000Mhz RGB DDR5/ RTX 5070 Ti 16GB/1TB M.2 SSD", "Desktop PC"),
    ("HP Z2 G13 700W,INTEL CORE I7-14700 5.40G 33MB 20 C,32GB (1X32GB),512GB PCIE M.2 SSD + 1TB 7200RPM SATA,NVIDIA RTX A4000 16 GB,DVD", "Desktop PC"),
    ("HP PAVILION AIO PC,INTEL CORE I7 13700T,27 INCH FHD 3 SIDED MICRO-EDGE DISPLAY/16GB RAM/1TB SSD/WIN 11/MSO", "Desktop PC"),
    # ...but a part that says which PCs it fits stays a part
    ("Core i3-4170 (i3 4th Generation Processor) 3.70 Ghz for LGA 1150 Socket Desktop Processor for Desktop Pc (Silver) (Supports H81 Motherboard)", "Processor/CPU"),
    ("Intel (R) Core(TM) i5-10400F 10th Gen Desktop Processor 6 CORES/ 12 Threads 2.9 GHz (UP to 4.3 GHZ) Without Processor Graphics", "Processor/CPU"),
    ("Intel Core i5 14600K (CPU Cooler Fan not Included) 3.5 GHz Upto 5.3 GHz LGA1700 Socket 14 Cores 20 Threads 24 MB Smart Cache Desktop Processor", "Processor/CPU"),
    ("AMD A8-9600 Bristol Ridge Quad-Core 3.1 GHz Socket AM4 65W AMD Radeon R7 Graphics Desktop Processor AD9600AGABBOX", "Processor/CPU"),
    ("A-Tech 8GB DDR4 2400MHz DIMM PC4-19200 UDIMM Non-ECC 2Rx8 1.2V CL17 288-Pin Desktop Computer RAM Memory Upgrade Module", "Memory/RAM"),
    ("AX650 256GB 2.5 Inch SATA III Internal SSD, 6Gb/s Solid State Drive, High-Speed 3D NAND Flash, Fast Boot & Data Transfer, Upgrade for Laptop, Desktop PC", "SSD"),
    ("MSI S270 240 GB All in One PC's, Desktop, Laptop, Network Attached Storage, Servers Black SATA III Internal Solid State Drive (SSD) (SPATIUM S270 SATA)", "SSD"),
    ("ASROCK X570S PG RIPTIDE AMD RYZEN 5000 SERIES CPU(SOCKET AM4)", "Motherboard"),
    ("Sapphire Nitro+ B850M WiFi AMD B850 Chipset Micro-ATX Gaming Motherboard, AM5 Socket, DDR5 256GB up to 8000 MHz — Supports Ryzen 9000/8000/7000 Series", "Motherboard"),
    ("ANTEC Atom B650 650W 80+ Bronze Non Modular ATX Power Supply", "Power Supply"),
    # laptops named only by their chip and spec sheet, and 2-in-1s, are laptops
    ("DELL G15 Intel Core i5 12th Gen 12500H - (8 GB/512 GB SSD/Windows 11 Home/4 GB Graphics/NVIDIA GeForce RTX 3050)", "Gaming Laptop"),
    ("HP Omen Intel Core i5 7th Gen 7300HQ - (8 GB/1 TB HDD/128 GB SSD/Windows 10 Home/4 GB Graphics/NVIDIA GeForce GTX 1050)", "Gaming Laptop"),
    ("ACER NITRO V16S AI NH.QZYSI.001 [R7-260/16GB/1TB SSD/WIN11 HOME/16.0\"/8GB-RTX5060 GRAPHICS/1 YEAR(S)/BLACK]", "Gaming Laptop"),
    ("ASUS VIVOBOOK FLIP CORE I5 12TH GEN - (16 GB/512 GB SSD/WINDOWS 11 HOME) TP3402ZA-LZ511WS 2 IN 1 LCD LAPTOP (14 INCH, QUIET BLUE)", "Gaming Laptop"),
    ("MICROSOFT Surface Pro 12\" Core 8 with Microsoft 365 for 6 Months* Snapdragon X Plus - (16 GB/512 GB SSD/Windows 11 Home) Surface Pro 2 in 1 Laptop", "Gaming Laptop"),
    ("CRUCIAL 8GB DDR4-3200MHZ LAPTOP CL22 RAM CB8GS3200", "Memory/RAM"),
    ("Arzopa Z3FC 40.89 cm (16 inch) Quad HD IPS Panel Monitor (2.5K QHD Portable Gaming Monitor for Laptop 106% sRGB IPS Display USB-C & HDMI)", "Monitor"),
    # Flipkart's made-up spec tails ("... DDR2 2 GB NVIDIA Chipset 0 bit 0 MHz Graphics Card")
    ("flyx E88 Pro 4K Elite Drone with Smart Sensor & Precision Gyro Hold DDR2 2 GB NVIDIA Chipset 0 bit 0 MHz Graphics Card", "Other"),
    ("Gimora M1 Professional 3-Axis Gimbals Stabilizer for Smartphone Video Recording DDR5 2 GB AMD/ATI Chipset 0 bit 0 MHz Graphics Card", "Other"),
    ("Fyntra 3D VR Glasses For Android Mobile Phones DDR5 2 GB AMD/ATI Chipset 0 bit 0 MHz Graphics Card", "Gaming Accessories"),
    ("LipiWorld VER011-PRO Riser Card 10 Capacitors PCI-E 1X to 16X Riser Card GDDR4 16 GB NVIDIA Chipset 64 bit 120 MHz Graphics Card", "Accessories"),
    ("GIGABYTE GV-N3050WF2OCV2-6GD GDDR6 6 GB NVIDIA Chipset 96 bit 1477 MHz Graphics Card", "Graphics Card"),
    ("ZOTAC ZT-T20600H-10M GDDR6 6 GB NVIDIA Chipset 192 bit 1680 MHz Graphics Card", "Graphics Card"),
    ("ZEB ZEBRONICS GT730 4GD3 Graphic Card with Heatsink and Fan GDDR3 4 GB NVIDIA Chipset 64 bit 1333 MHz Graphics Card", "Graphics Card"),
    ("Electronic Spices FD5010U12S 12V 0.22AMP for hd7350 For Raedon AMD graphic card cooler cooling fan GDDR5X 1 GB AMD Radeon Chipset 64 bit 6000 MHz Graphics Card", "Fans & Cooling"),
    ("Blaupunkt BH71 Moksha Hybrid ANC 360 Spatial Audio with Head Tracking I RTL Chipset Bluetooth & Wired", "Headset"),
    ("Electronic Spices White Thermal Conductive Grease Paste for CPU GPU Chipset Cooling 10G", "Thermal Paste"),
    # words that mean something else in a product title
    ("320GB 2.5 Inch Internal Hard Disk Drive, High-Speed Storage Drive Compatible for Desktop, Laptop and Computer Systems", "HDD"),
    ("EVM 128GB M.2 SATA SSD 2280 | Internal Solid State Drive | Up to 520MB/s Read 370MB/s Write | Laptop Desktop Upgrade | 5 Year Warranty (EVMM2/128GB)", "SSD"),
    ("Portronics SoundDrum P Wireless with 6-7 hrs Playback Time, Handsfree Calling, 20 W Bluetooth Speaker", "Speakers"),
    ("ASUS GeForce RTX 3090 EKWB 24GB Nvidia Graphic Card With Water Block", "Graphics Card"),
    ("Samsung Odyssey G5 68.58 cm (27 inch) Quad HD LED Backlit VA Panel with HDR10, Height Adjustable Stand, Flat Gaming Monitor (LS27CG510EWXXL)", "Monitor"),
    ("MSI MAG Forge 320R Airflow Mid-Tower PC Case - ATX Capacity, RTX 40 GPU Support, ARGB Fans, Magnetic Dust Filters, Tempered Glass", "PC Case/Chassis"),
    ("CORSAIR 3500X ARGB Mid-Tower ATX Dual Chamber PC Case – Panoramic Tempered Glass – Reverse Connection Motherboard Compatible", "PC Case/Chassis"),
    ("Karnage Sunbeam 120mm ARGB PC Case Fan | 22 ARGB LEDs | 9-Blade Design | Hydraulic Bearing | 800-2200 RPM PWM", "Fans & Cooling"),
    ("Sparewave Replacement Internal CPU/GPU Cooling Fan HP Omen 15-AX 15AX Pavilion 15-BC 15BC Cooling Fan Laptop Cooler", "Fans & Cooling"),
    ("Foxin 600W Uninterrupted Power Supply System FPS 1001 - 1000VA 220 V Line-interactive Rack-mount Model UPS with Overload Protection 3 Outlet", "UPS"),
    ("LIAN LI Strimer Plus V2 24-Pin ARGB Motherboard Extension Cable", "Accessories"),
    ("Mechanical Keyboard Switch Keycap Keychain | Pastel Color Acrylic Keyring with Clicky Keyboard Switch | Portable Stress Relief Fidget Toy", "Other"),
    ("KEXIN 32GB USB Flash Drive 5 Pack, Swivel USB 2.0 Memory Stick Thumb Drive with Keychain Design, Portable Pen Drives for PC, Laptop", "Pen Drive"),
    ("Nintendo Switch 2 Choose Your Game Bundle, 256GB Console with Joy-Con 2, 7.9-inch 1080p HDR Display, Up to 120 fps, 4K TV output", "Nintendo"),
    ("Taiko No Tatsujin Rhythm Festival PS5 Game CD | Drum-Based Rhythm Music Game | Best PS5 Game for Rhythm Fans", "Games"),
]


@pytest.mark.parametrize("title,want", CASES, ids=[c[0][:40] for c in CASES])
def test_category(title, want):
    assert type_of(title) == want


def test_recategorize_swaps_only_the_category_part_of_the_id():
    from pph.normalize import recategorize
    pc = "CHIST Gaming Desktop PC – AMD Ryzen 5 5600 Processor | 32GB DDR4 3200MHz RAM | 512GB NVMe SSD | B450 Motherboard"
    assert recategorize(pc, "Motherboard", "motherboard-chist-5600-b450") == ("Desktop PC", "desktop-pc-chist-5600-b450")
    assert recategorize("MSI B550M-A Pro Motherboard", "Motherboard", "motherboard-msi-b550m") == ("Motherboard", "motherboard-msi-b550m")
    assert recategorize("flyx E88 Pro 4K Drone DDR2 2 GB NVIDIA Chipset 0 bit 0 MHz Graphics Card", "Motherboard", "x") is None
