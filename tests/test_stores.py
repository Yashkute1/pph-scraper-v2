from pph.stores import STORES
from pph.adapters import ADAPTERS

NAMES = ["elitehubs", "vishalperipherals", "pcstudio", "primeabgb", "vedantcomputers", "mdcomputers", "theitdepot", "flipkart", "amazon"]


def test_all_nine_stores_configured():
    assert sorted(STORES) == sorted(NAMES)


def test_every_store_has_a_known_adapter_base_and_delay():
    for name, cfg in STORES.items():
        assert cfg["adapter"] in ADAPTERS, name
        assert cfg["base"].startswith("https://") and not cfg["base"].endswith("/"), name
        lo, hi = cfg["delay"]; assert 1 <= lo <= hi, name
        if cfg["adapter"] == "html_listing":
            assert cfg["start_urls"] and all(u.startswith(cfg["base"]) for u in cfg["start_urls"]), name
            assert len(set(cfg["start_urls"])) == len(cfg["start_urls"]), name


def test_modes_match_the_probe():
    assert STORES["amazon"]["mode"] == "stealth" and STORES["amazon"]["delay"] == (3, 5)
    assert all(c["mode"] == "http" for n, c in STORES.items() if n != "amazon")
    assert STORES["pcstudio"]["adapter"] == "woo_store_api"
    assert STORES["elitehubs"]["adapter"] == STORES["vishalperipherals"]["adapter"] == "shopify_feed"
