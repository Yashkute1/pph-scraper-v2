from pph.adapters.html_listing import iter_offers
from pph.stores import STORES
from .helpers import FakeFetcher

# Trimmed from computechstore.in/product-category/graphics-card/ (October 2026): the card markup the config reads.
CARD = '''<div class="group bg-white p-2 rounded-2xl relative flex flex-col">
  <div class="absolute top-3 left-3 bg-theme">Sale</div>
  <a href="/product/{slug}/" class="block relative aspect-square"><img src="/media/products/{slug}.jpg" alt="{title}"></a>
  <div class="px-1 flex-grow flex flex-col justify-between"><div class="flex flex-col gap-1">
    <a href="/product/{slug}/" class="block"><h3 class="text-gray-900 font-black">{title}</h3></a>
    <div class="flex items-baseline gap-1.5 mt-0.5"><span class="block text-xs font-black">₹{price}</span>
      <span class="block font-bold text-gray-400 line-through">₹{mrp}</span></div></div>
    <div class="mt-2.5 flex items-center gap-1.5"><div class="w-1.5 h-1.5 rounded-full"></div>
      <span class="text-[8px] font-black uppercase tracking-widest">{stock}</span></div></div></div>'''


def page(*cards):
    return '<html><body><div id="product-grid-container" class="grid">' + "".join(CARD.format(**c) for c in cards) + "</div></body></html>"


def test_computech_cards():
    cfg = dict(STORES["computech"]); cfg["start_urls"] = cfg["start_urls"][:1]
    html = page(dict(slug="powercolor-reaper-rx-9070-gre-12gb", title="Powercolor Reaper AMD Radeon RX 9070 GRE 12GB", price="67499", mrp="123800", stock="In Stock"),
                dict(slug="nextron-gt730-4gb", title="NEXTRON GeForce GT730 4GB DDR3 Graphics Card", price="4499", mrp="5800", stock="Out of Stock"))
    a, b = list(iter_offers(cfg, FakeFetcher({cfg["start_urls"][0]: html}, default="<html><body></body></html>")))
    assert (a["title"], a["price"], a["mrp"], a["in_stock"]) == ("Powercolor Reaper AMD Radeon RX 9070 GRE 12GB", "₹67499", "₹123800", True)
    assert a["url"] == "https://computechstore.in/product/powercolor-reaper-rx-9070-gre-12gb/"
    assert a["image"] == "https://computechstore.in/media/products/powercolor-reaper-rx-9070-gre-12gb.jpg"
    assert b["in_stock"] is False
