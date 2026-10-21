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


def _gid(title, store="amazon"):
    from pph.normalize import normalize
    o = normalize({"title": title, "price": "2999", "url": "https://x.test/" + title[:10]}, store)
    return o and o["group_id"]


@pytest.mark.parametrize("a,b", [
    # Real listings that shared one product page because their only model-like words were sizes or "pro".
    ("DEEPCOOL ASSASSIN IV 120MM CPU AIR COOLER", "DEEPCOOL Gamma Archer 120mm Single Tower CPU Air Cooler"),
    ("Enter WIRED MECHANICAL KEYBOARD PHOENIX PRO WITH RGB", "ROCCAT Vulcan TKL Pro PC Gaming Keyboard, Linear Switches"),
    ("Hogwarts Legacy | Standard Edition| PlayStation 5 (PS5) 2023", "Sonic Frontiers PS5 Game CD | Sonic Frontiers PlayStation 5"),
    ("Kingston Dual Portable 1TB USB 3.2 Gen 2 SSD", "SANDISK 1TB EXTREME PORTABLE SSD"),
    ("CORSAIR Dominator Platinum 16GB (8GB x 2) 3200MHz DDR4 RAM", "Corsair Vengeance RGB RS 16GB (2 x 8GB) 3200MHz DDR4 RAM"),
    ("Dyazo Plus Transparent Wireless Mouse", "LAPCARE Trendy Plus Ergonomic Optical Mouse"),
])
def test_vague_keys_no_longer_merge_different_products(a, b):
    assert _gid(a) and _gid(b) and _gid(a) != _gid(b)


@pytest.mark.parametrize("a,b", [
    ("Seagate Expansion 4TB Desktop External Hard Drive", "SEAGATE EXPANSION 3.5 DESKTOP 4TB EXTERNAL HDD"),
    ("MSI MAG Forge 130A AirFlow ARGB ATX Mid Tower Cabinet", "MSI Mag Forge 130A Airflow Auto RGB ATX Cabinet"),
    ("Intel Core Ultra 7 265K Desktop Processor", "Intel Core Ultra 7 265K Processor"),
    ("AMD Ryzen 5 3400G Processor with Radeon Vega 11 Graphics", "Amd Ryzen 5 3400G With Radeon Rx Vega 11 Graphics"),
])
def test_the_same_product_still_matches_across_stores(a, b):
    assert _gid(a) == _gid(b, "flipkart")


def test_a_bare_brand_is_not_a_product():
    from pph.normalize import type_of
    assert type_of("ZORBES") == "Other" and type_of("Case Club") == "Other"
    assert type_of("Playseat Seatslider") != "Other" and type_of("Elden Ring") == "Games"
    assert type_of("Mastering Rundll32.exe: A Comprehensive Guide to Windows System Management") == "Other"


def test_rollup_regroups_an_offer_whose_id_was_vague():
    from pph.normalize import recategorize
    t = "DEEPCOOL ASSASSIN IV 120MM CPU AIR COOLER"
    cat, gid = recategorize(t, "Fans & Cooling", "fans-cooling-deepcool-120mm", "Deepcool")
    assert cat == "Fans & Cooling" and gid != "fans-cooling-deepcool-120mm" and "assassin" in gid
    # a clear model number is left alone
    assert recategorize("MSI B550M-A Pro Motherboard", "Motherboard", "motherboard-msi-b550m", "MSI") == ("Motherboard", "motherboard-msi-b550m")


@pytest.mark.parametrize("title,want", [
    # found in the wrong category by the October 2026 live audit
    ("VirtuCraft VR Goggles with Wide Field of View 5.4 GHz sTR4 2 Core Processor Designed for Mobile", "Gaming Accessories"),
    ("Altivus E88 Pro HD Drone with Hover Stability 2.4 GHz AM4 4 Core Processor Designed for Workstation", "Other"),
    ("markif E88 SMOOTH FLYING DRONE FOR KIDS AM1Socket ATX AMD 320 Chipset DDR2 Motherboard for Mobile", "Other"),
    ("ZEBRONICS H61-NVM2P-i3-4GB LGA 1155Socket ATX Intel H61 Chipset DDR3 Motherboard for Desktop", "Motherboard"),
    ("5V 2A Power Supply Board (PCB) (220V AC to 5V DC SMPS Power Supply PCB Circuit)", "Other"),
    ("CARE CASE 12V 2A DC Power Adapter,Powers Supply,Charge,TFT Pin SMPS for PC,LCD Monitor,TV,LED Strip", "Other"),
    ("Corsair RM750e ATX 3.1 Gold Fully Modular White SMPS", "Power Supply"),
    ("4 DOT FOURDOT COOLINGS 120mm 5Inch Desktop Computer Cabinet Cooling Fan, 12V 2000RPM, 4Pin Motherboard Connector", "Fans & Cooling"),
    ("Sparewave GPU TUF Gaming FX505 FX566 FX705 Laptop Cooling Fan Laptop Cooler", "Fans & Cooling"),
    ("Corsair 4000D Airflow Mid Tower ATX Case with 2 Cooling Fans", "PC Case/Chassis"),
    ("CRMTECK Compatible with PS5 Vertical Stand with Cooling Fan, Controller Charging Station", "Gaming Accessories"),
    ("H61 ATX Motherboard Combo Kit with Core i3 3220 3rd Gen Processor | 4GB DDR3 RAM | Free CPU Cooling Fan", "Desktop PC"),
    ("SURADI Extended Desk Pad for Comfortable Use Setup GAMINIG MAT Cabinet with USB 2.0 and USB 3.0 Ports", "Mousepad"),
    ("Thermal Grizzly TG Putty Basic Electrically Non-Conductive Thermal Interface Material for GPU Modding", "Thermal Paste"),
    ("Toshiba N300 4TB 7200 RPM NAS Hard Drive", "HDD"),
    ("Western Digital 4TB WD Red SA500 NAS 3D NAND Internal SSD Solid State Drive", "SSD"),
    ("Synology Diskstation DS425 Plus 4-Bay NAS Enclosure", "Networking"),
    ("drivenova d320n 320 GB All in One PC's, Desktop, Laptop, Surveillance Systems Black SATA Intern...", "HDD"),
    ("GUGGU Bluetooth Speaker Support SD Card/Aux With Stereo Sound H219 10 W Bluetooth Laptop/Desktop Speaker", "Speakers"),
    ("RAYA Keyboard Cover for Samsung Galaxy Book 4 Pro 360 16 inch Keyboard Skin", "Accessories"),
    ("Poly By Plantronics Studio P5 Professional Webcam - 1080P Hd Laptop Camera - Monitor & Tripod Mount", "Webcam"),
    ("Orlov Executive 2K QHD Webcam with Dual Mic & Privacy Cover for Laptop & PC", "Webcam"),
    ("AOC CU34V5CWBK 34 Inch Curved Webcam Monitor", "Monitor"),
    ("Intel i3 (3240) 3rd Gen Processor for H61 Chipset Motherboards 3.4 GHz LGA 1155 Socket 2 Cores Desktop Processor", "Processor/CPU"),
    ("MAK All-in-One Dual Wireless Mic and LED Selfie Stick for Creators Microphone", "Microphone"),
    ("TekBud ESP32 WiFi Bluetooth Dual Core Development Board 0.24 GHz LGA1700 2 Core Processor Designed for Desktop", "Other"),
    ("PreSolve i3-6100 Processor 3.7 GHz LGA 1151 2 Core Processor Designed for Desktop", "Processor/CPU"),
    ("LipiWorld PCI 4 Digit PC Motherboard Analyser Diagnostic Card Tester AM1Socket ATX AMD 320 Chipset DDR2 Motherboard for Desktop", "Accessories"),
    ("12V 1A Switch Mode Power Supply- (SMPS)", "Other"),
    ("Electronic Spices Multi Volts Multi-Purpose SMPS Power Supply (24V,12V,5V,3.3V 1amp)", "Other"),
    ("sky enterprise shop ESD BIN PP BOX SIZE H300XL200XW100 MM BOX Cabinet with USB 2.0 Ports Compatible with Computer", "Other"),
    ("Toshiba MG08ACA16TE Internal Hard Disk Server for NAS 3.5\" 16TB", "HDD"),
    ("FINGERS FirstClass-E9 MicroATX Cabinet with USB 2.0 and USB 3.0 Ports Compatible with Computer", "PC Case/Chassis"),
    ("ASUS ROG STRIX Arion NVME M.2 SSD Enclosure Cabinet with USB 2.0 and USB 3.0 Ports Compatible with Computer", "Accessories"),
    ("Zebronics Premium Power Supply, Long Flat Cables, Silent 120mm Fan, 12V 32A, 6+2 PCIe, 4+4 CPU, 4 x SATA, 2 x MOLEX, RGB", "Power Supply"),
    ("GT 1030 4G DDR4 Gaming Graphics Card, 64 Bit 2100MHz PCI Express 3.0 x4 Video Card with Cooling Fan", "Graphics Card"),
    ("Core i3 4th Gen Desktop Processor, 2.9 GHz to 3.8 GHz, LGA 1150 Socket, 2 Cores 4 Threads, 3/4MB Cache, with Cooling Fan", "Processor/CPU"),
    ("DooBuy E97379-001 Core i3/i5/i7 Socket 1150/1155/1156 4-Pin Connector CPU Cooler Cooling Fan Processor Cooler", "Fans & Cooling"),
])
def test_audit_finds(title, want):
    assert type_of(title) == want


@pytest.mark.parametrize("title,want", [
    # consoles in their own category, games in Games, the rest in Gaming Accessories (October 2026 search check)
    ("Sony PlayStation®5 Digital Edition (slim) Console Video Game", "PlayStation"),
    ("Playstation Sony PS5 Pro 2TB SSD Gaming Console Play Station 5", "PlayStation"),
    ("Sony PlayStation®5 Digital Edition (slim) Console & PowerA Twin Charging Station for PS5 Wireless Controllers", "PlayStation"),
    ("MICROSOFT Xbox Series S 512 GB", "Xbox"),
    ("Xbox Series X 1TB Disc Edition, 4K Resolution with 120FPS, High Performance SSD 1024 GB with Wiresless Gaming Controller", "Xbox"),
    ("NINTENDO Switch Lite Portable Gaming Console for TV & Handheld Play Built-in Controllers", "Nintendo"),
    ("NINTENDO Switch 2 Gaming Console | The Ultimate 3-in-1 Gaming Powerhouse| Next Version | Play:TV, Tabletop or Handheld", "Nintendo"),
    ("Nintendo Switch 2", "Nintendo"),
    ("NVIDIA RTX Pro 6000 Blackwell Max-Q Workstation Edition 96GB Graphics Card", "Graphics Card"),
    ("AMD FirePro W4300 4GB Workstation Graphic Card", "Graphics Card"),
    ("Intel Core i7 12700F 12 Gen Desktop PC Processor 12 Core CPU with 25MB Cache and up to 4.9 GHz Clock Speed LGA", "Processor/CPU"),
    ("ROG NUC 16 Gaming Mini PC, AI Desktop | Ultra 9 290HX Plus, RTX 5080 GPU", "Desktop PC"),
    ("PS5 Marvel's Wolverine", "Games"),
    ("UNTIL DAWN (PS5)", "Games"),
    ("PS5 Cricket 26 | ps5 playstation games Blu-ray Disc | PS5 Sports Game", "Games"),
    ("Call of Duty Black Ops Cold War Xbox Game | Optimized for Xbox Series X & Xbox Series S", "Games"),
    ("PS5 Slim Console Faceplate, Cooling Vents with RGB Light, Replacement Side Plates", "Gaming Accessories"),
    ("TCOS TECH PS5 Slim Dust Proof Kit, 9Pcs Dust Plug Kit for PS5/PS5 Slim Console", "Accessories"),
    ("TMG Dust Proof Kit Compatible with Xbox Series X Console", "Gaming Accessories"),
    ("KingSpec XG7000 2TB NVMe SSD PCIe 4.0-7400MB/s Read Speed, M.2 2280 Internal SSD, Compatible with Gaming PC, Laptop, PS5 Console", "SSD"),
    ("RAZER Kraken X for Console Wired Gaming Headphones With Mic ( Pc / Mac / Xbox / PS4 / PS5 )", "Gaming Accessories"),
])
def test_consoles(title, want):
    assert type_of(title) == want


@pytest.mark.parametrize("title,want", [
    # third sweep, 20 Oct 2026
    ("ZEBRONICS ZEB-ZS500 500 Watts Computer PSU with 3 SATA Cables", "Power Supply"),
    ("Antec Atom V450 450 Watts Gaming PSU with 3 SATA Cables", "Power Supply"),
    ("ZEBRONICS Gold Power Supply with 3X SATA connectors,with 1.2m Power Cable 450 Watts Computer PSU with 3 SATA Cables", "Power Supply"),
    ("Mean Well SMPS, 48 Valt, 1.1 AMP, LRS-50-48, panel mount 50 Watts Computer PSU with 0 SATA Cables", "Other"),
    ("BALRAMA Led Controller T1000S With Sd Card 60 Watts Computer PSU with 3 SATA Cables", "Other"),
    ("skarsh Power Cable Desktops PC and Printers Monitor SMPS Power Cable Mains Power Cable 1000 Watts Computer PSU with 2 SATA Cables", "Accessories"),
    ("Sgt Wall Mounted Wooden Hook Rack / Coat Hanger Wall Mounted Wooden Hook Rack / Coat Hanger Cabinet Compatible with Computer", "Other"),
    ("Senvox World Map Keyboard Desk Mat | Large Extended Mouse Pad with Non-Slip Base Desk Mat Cabinet Compatible with Computer", "Mousepad"),
    ("LIAN LI GB-001 Anti Sag Bracket For Graphics Card", "Accessories"),
    ("ASUS Pro WS TRX50-SAGE WiFi A AMD TRX50 TR5 CEB Workstation Motherboard, PCIe 5.0 x 16, Multi-GPU Support", "Motherboard"),
    ("CORSAIR Frame 4500X RS-R ARGB Panoramic Glass Mid-Tower PC Case – Fits Dual 360mm Radiators, GPU Anti-Sag", "PC Case/Chassis"),
    ("HOKIPO Gaming Chair Cover, Stretchable, Revolving Chair, Turquoise", "Accessories"),
    ("NiTHO RAVEN Gaming Office Chair | Ergonomic Computer Chair with Linkage Armrests, Foldable Footrest, Class 3 Gas Lift", "Gaming Chair"),
    ("Zodiac Screen Guard for Universal Neo Earbud Nano Glass 100.577", "Other"),
    ("ULTRAZONE Laptop Speaker Replacement for Acer Aspire A515-51 51G A315-53 53G 1 W Laptop/Desktop Speaker", "Accessories"),
    ("NILIX Professional Computer Cleaning Tool for CPU Processor 0 GHz AM2 1 Core Processor Designed for Laptop, Desktop", "Other"),
    ("HP HS04 41Wh Laptop Battery Compatible with Laptops | 14.8V 2670mAh 4-Cell | Replacement Battery 4 Cell Laptop Battery", "Accessories"),
    ("SYARA Wireless Gaming Sports Headphones Stereo With SD Card & 5-6h Battery BackupQH143 Bluetooth", "Headset"),
    ("ANTEC Prizm 140mm ARGB Cabinet Fans and LED Controller ( Dual Pack )", "Fans & Cooling"),
    ("Etzin SAS Cable 0.4 m SATA Cable III 6Gbps Straight HDD SDD Data Cable", "Accessories"),
    ("WD Elements 6 TB External Hard Disk Drive (HDD) 5 GB/s, USB 3.0 Cable, Compatible with Windows", "HDD"),
    ("MSI EdgeXpert QSFP High-Speed Networking Cable", "Networking"),
])
def test_third_sweep(title, want):
    assert type_of(title) == want


@pytest.mark.parametrize("title,want", [
    # fourth sweep, 20 Oct 2026
    ("Rode NT-USB Mini USB Microphone", "Microphone"),
    ("Wifton USB RGB Condenser Microphone with Adjustable Stand for Podcasting Gaming Singing Microphone", "Microphone"),
    ("CAPLIC XLR Cable for Condenser Microphone Balanced 3 Pin for Studio Amplifier Mixer Speaker Cabinets", "Accessories"),
    ("GLORIOUS Panda Tactile Switches X36 Unlubed (GLO-SWT-HPANDA)", "Keyboard"),
    ("HYPERX Pudding Keycaps Double Shot PBT (Pink)", "Keyboard"),
    ("Thermal Grizzly Conductonaut Desktop Liquid Metal Paste - 1.0 Gram", "Thermal Paste"),
    ("ASUS ROG Matrix Platinum GeForce RTX 5090 OC 30th-Anniversary Edition Gaming Graphics Card, 32GB GDDR7, PCIe 5.0, 512-bit, Liquid Metal Cooling", "Graphics Card"),
    ("THRUSTMASTER T-598 Direct Drive Wheel For Playstation & PC", "Gaming Accessories"),
    ("ThrustMaster T-Flight Gaming Headset - US Air Force Edition", "Headset"),
    ("CADYCE 5X1 HDMI SWITCH 4K@60HZ WITH REMOTE & CHANGE OVER BUTTON. CA-5HDS PLUS", "Accessories"),
    ("TECNICO A1 Desktop CPU, Core i3-3470 3.2GHz, 8GB DDR3 RAM, 128GB SSD, RGB Gaming Keyboard Mouse Speakers Set, HDMI Cable", "Desktop PC"),
    ("SANDISK PROFESSIONAL 2TB PRO-BLADE TRANSPORT,SDPM2NB-002T-GBAND", "SSD"),
    ("Samsung 27\" Odyssey G5 Fast IPS Gaming Monitor | QHD 2560 x 1440 | 180 Hz | 1ms | Ports-DP,HDMI,Headphone", "Monitor"),
    ("Samsung Odyssey G5 80.0 cm (32 inch) Curved Quad HD LED Backlit VA Panel with HDR10, 1000R curvature, Ports-HDMI,DP,Headphone", "Monitor"),
    ("Bitsweb White Gaming PC Set with 22 Inch LED Monitor, Core i3 Processor, 8GB RAM, 256GB SSD", "Desktop PC"),
    ("Apple iMac M4 (16 GB Unified/256 GB SSD/macOS Sequoia/24 Inch Screen/MWUU3HN/A)", "Desktop PC"),
    ("FPS-500S SMPS 200W PS3 Power Supply | 20+4 Pin, 4+4 CPU Connector | BIS Certified | Low Noise", "Power Supply"),
    ("Geonix Optima R5 Mid Tower PC Cabinet with 200W in-Built SMPS, Micro-ATX & Mini-ITX, 240mm GPU Support", "PC Case/Chassis"),
    ("Consistent Voltedge 450W Power Supply, ATX Desktop SMPS with 8cm Fan, SMT Design, 20+4 Pin ATX, Includes 1.2M India Power Cord", "Power Supply"),
    ("Ranz Power Cord 1.5 m Power Supply Cable for CPU & UPS", "Accessories"),
    ("Varaha Neer BIS Certified Office,Study Chair | 5 Year Warranty| Curved Armrest & Smart Tilt Locking System| Class 4 Gas Lift", "Gaming Chair"),
    ("Office Chair Mat for Hardwood Floor, Desk Rug for Rolling Chair, Computer Gaming Chair Mat", "Accessories"),
    ("ishield doorbell HomeView 7 Elite HD Webcam 480p, with Microphone, Night vision", "Other"),
    ("BALRAMA Standard 15-pin VGA Cable Male to Male VGA Video Cable TV PC Computer Monitor 300 Watts Computer PSU with 2 SATA Cables", "Accessories"),
])
def test_fourth_sweep(title, want):
    assert type_of(title) == want


@pytest.mark.parametrize("title", [
    "LIAN LI O11D EVO Upright GPU Kit ( Black )",
    "MSI GeForce RTX NVLink GPU Bridge",
    "PNY NVIDIA NVLINK 2-SLOT BRIDGE FOR RTX A6000 A5000 A100 RTXA6000NVLINK-KIT (2-SLOT)",
])
def test_gpu_add_ons_are_accessories(title):
    assert type_of(title) == "Accessories"


def test_mic_with_xlr_cable_is_a_mic():
    assert type_of("Urban Infotech BM-800 Condenser Mic with XLR Cable Shock Mount and Foam Cap Microphone") == "Microphone"
    assert type_of("HYPERX XLR Cable Male-to-Female, 3 Pin, 10-Foot ( Black )") == "Accessories"


@pytest.mark.parametrize("title,want", [
    # fifth sweep, 21 Oct 2026
    ("Playstation 5 DualSense Wireless Remote for Sony ps5 Console Disc |Digital Edition Precision Bluetooth Gamepad", "Gaming Accessories"),
    ("Nintendo Switch 2 Choose Your Game Bundle, 256GB Console with Joy-Con 2, 7.9-inch 1080p HDR Display", "Nintendo"),
    ("GIGABYTE Geforce RTX 5070 Ti Gaming pci_e_x16 OC 16G Graphics Card, 16GB 256-Bit GDDR7, GV-N507TGAMING OC-16GD Video Card", "Graphics Card"),
    ("ASUS ProArt P16 OLED (2025), AMD Ryzen AI 9 HX 370, RTX 5080-16GB,64GB RAM, 2TB SSD, 16\"/40.64cm Touchscreen, 4K, 120Hz,Windows 11", "Gaming Laptop"),
    ("Apple 13-inch MacBook Air M5 chip with 10 core CPU and 8 core GPU, 16GB, 512GB SSD - Midnight", "Gaming Laptop"),
    ("Seagate Barracuda 2 TB Internal Hard Drive HDD – 8.89 cm (3.5 Inch) SATA 6 Gb/s 5400 RPM 256 MB Cache for Computer Desktop PC (ST2000DM005)", "HDD"),
    ("ULTRAZONE CPU Cooling Fan Dell Inspiron 15-5575, Inspiron 15-3583 Cooling Fan Laptop Cooler", "Fans & Cooling"),
    ("MSI X299 Raider DDR4 Intel Motherboard", "Motherboard"),
    ("DELL Inspiron 24 Core i5 (8 GB DDR4/512 GB SSD/Windows 11 Home/23.8 Inch Screen/Inspiron 5420) with MS Office", "Desktop PC"),
    ("DiskStation DS920+ NAS 64TB (4x16TB HDD, 20GB DDR4 RAM) Network Attached Storage Drive (4 Bay)", "Networking"),
])
def test_fifth_sweep(title, want):
    assert type_of(title) == want


def test_a_title_that_starts_with_a_maker_names_that_maker():
    from pph.normalize import brand_of
    assert brand_of("Sony PlayStation®5 Digital Edition (slim) Console Video Game & Ant Esports Dock5 RGB") == "Sony"
    assert brand_of("Lenovo V15, AMD Ryzen 5 7520U, 16GB RAM, 512GB SSD, 15.6\", DOS, Arctic Grey") == "Lenovo"
    assert brand_of("Intel Core i3 12100F with NVIDIA RTX 3050 custom PC") == "NVIDIA"   # chip makers keep the list order
    assert brand_of("GIGABYTE B860M AORUS ELITE WIFI6E MOTHERBOARD") == "GIGABYTE"           # same maker: id spelling kept
