import io

import pytest
from PIL import Image, ImageDraw

import numpy as np

from tools.cutouts import (background, cut_photo, cutout_key, encode, exact_cut, finish, in_shard, merge_manifest, model_cut, parse_manifest,
                           safe_url, todo, usable)


def test_key_is_stable_and_path_safe():
    k = cutout_key("https://cdn.store.test/a.jpg?v=1")
    assert k == cutout_key("https://cdn.store.test/a.jpg?v=1") and len(k) == 24 and k.isalnum()
    assert k != cutout_key("https://cdn.store.test/b.jpg")


def test_shards_cover_everything_once():
    keys = [cutout_key(f"https://x.test/{i}.jpg") for i in range(500)]
    seen = [sum(in_shard(k, s, 6) for s in range(6)) for k in keys]
    assert set(seen) == {1}
    assert all(20 < sum(in_shard(k, s, 6) for k in keys) < 160 for s in range(6))


def test_manifest_round_trip_and_merge():
    m = parse_manifest("aaa ok\nbbb skip\n\ngarbage line here\nccc ok\n")
    assert m == {"aaa": "ok", "bbb": "skip", "ccc": "ok"}
    out = merge_manifest(m, {"bbb": "ok", "ddd": "skip"})
    assert out == "aaa ok\nbbb ok\nccc ok\nddd skip\n"          # a later success replaces an earlier skip


def test_todo_skips_done_bad_urls_and_other_shards():
    urls = ["https://a.test/1.jpg", "https://a.test/2.jpg", "http://a.test/3.jpg", "", None, "https://a.test/1.jpg"]
    done = {cutout_key("https://a.test/2.jpg"): "ok"}
    got = todo(urls, done, 0, 1, limit=10)
    assert got == [(cutout_key("https://a.test/1.jpg"), "https://a.test/1.jpg")]
    assert todo(urls, {}, 0, 1, limit=1) == [(cutout_key("https://a.test/1.jpg"), "https://a.test/1.jpg")] or len(todo(urls, {}, 0, 1, limit=1)) == 1


@pytest.mark.parametrize("url,ok", [("https://cdn.store.test/a.jpg", True), ("http://cdn.store.test/a.jpg", False), ("https://127.0.0.1/a.jpg", False),
                                    ("https://10.0.0.8/a.jpg", False), ("https://localhost/a.jpg", False), ("https://[::1]/a.jpg", False),
                                    ("https://169.254.169.254/x", False), ("ftp://x.test/a", False), ("https://user:pw@x.test/a.jpg", False), ("nope", False)])
def test_safe_url(url, ok):
    assert safe_url(url) is ok


def blob(alpha_box=None, size=(400, 400)):
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    if alpha_box:
        ImageDraw.Draw(im).rectangle(alpha_box, fill=(30, 30, 30, 255))
    return im


def test_usable_rejects_empty_and_untouched_results():
    assert usable(blob((100, 100, 300, 300))) is True
    assert usable(blob()) is False                                   # nothing kept
    assert usable(blob((0, 0, 399, 399))) is False                   # nothing removed
    assert usable(blob((198, 198, 202, 202))) is False               # a speck


def test_finish_trims_pads_and_caps_size():
    out = finish(blob((100, 150, 300, 250), size=(2000, 2000)), max_side=640)
    assert max(out.size) <= 640 and out.mode == "RGBA"
    assert out.getpixel((0, 0))[3] == 0                              # a little transparent padding remains
    w, h = out.size
    assert w > h * 1.5                                               # the 2:1 subject keeps its shape
    assert out.getpixel((w // 2, h // 2))[3] == 255


def test_encode_is_webp_with_alpha():
    data = encode(finish(blob((100, 100, 300, 300)), 640))
    im = Image.open(io.BytesIO(data))
    assert im.format == "WEBP" and im.mode == "RGBA" and len(data) < 20000


# ---- the cut itself ------------------------------------------------------------------------------------------------

WHITE = np.array([255.0, 255.0, 255.0])


def scene(size=200):
    """White studio background with a black product in the middle. Returns (rgb array, product box)."""
    rgb = np.full((size, size, 3), 255, np.uint8)
    rgb[60:140, 50:150] = 20
    return rgb, (slice(60, 140), slice(50, 150))


def mask(size=200, box=None, value=1.0):
    m = np.zeros((size, size), np.float32)
    if box:
        m[box] = value
    return m


def test_plain_background_is_detected_even_when_the_product_touches_an_edge():
    rgb, _ = scene()
    col, plain = background(rgb)
    assert plain and col.tolist() == [255, 255, 255]
    rgb[0:200, 80:120] = 20                                           # a cable running out of the top and bottom
    assert background(rgb)[1]
    grad = np.tile(np.linspace(120, 255, 200, dtype=np.uint8)[None, :, None], (200, 1, 3))
    assert not background(grad)[1]                                    # a studio gradient is not a known colour


def test_a_dark_part_the_model_missed_is_kept():
    rgb, box = scene()
    wrong = mask(box=(slice(60, 140), slice(50, 100)))               # the model only saw the left half
    out = exact_cut(rgb, wrong, WHITE)
    assert out[100, 125, 3] == 255 and out[100, 75, 3] == 255        # both halves stay solid
    assert out[10, 10, 3] == 0 and out[100, 170, 3] == 0             # background is gone


def test_a_light_fringe_the_model_added_is_removed():
    rgb, _ = scene()
    halo = mask(box=(slice(58, 142), slice(48, 152)))                # the model's mask is 2 px too generous all round
    out = exact_cut(rgb, halo, WHITE)
    assert out[58, 100, 3] == 0 and out[100, 48, 3] == 0             # the white rim is not kept
    assert out[64, 100, 3] == 255


def test_white_areas_are_decided_by_the_model():
    rgb, _ = scene()
    rgb[80:120, 70:130] = 255                                        # a white label on the black product
    label_is_product = exact_cut(rgb, mask(box=(slice(60, 140), slice(50, 150))), WHITE)
    assert label_is_product[100, 100, 3] == 255
    hole = mask(box=(slice(60, 140), slice(50, 150)))
    hole[80:120, 70:130] = 0                                         # same picture, but the model says it is a gap
    assert exact_cut(rgb, hole, WHITE)[100, 100, 3] == 0


def test_a_shadow_becomes_see_through_and_dark():
    rgb, _ = scene()
    rgb[145:155, 60:140] = 225                                       # soft grey shadow on the white floor
    px = exact_cut(rgb, mask(box=(slice(60, 140), slice(50, 150))), WHITE)[150, 100]
    assert 15 < px[3] < 90 and px[:3].max() < 60                     # mostly transparent and dark, not a pale grey patch


def test_edge_pixels_lose_the_background_colour():
    rgb, _ = scene()
    rgb[59, 50:150] = 137                                            # the anti-aliased row a camera or resize produces
    px = exact_cut(rgb, mask(box=(slice(60, 140), slice(50, 150))), WHITE)[59, 100]
    assert 100 < px[3] < 160 and px[:3].max() < 60                   # half solid and dark: a smooth outline with no pale fringe


def test_without_a_plain_background_only_a_confident_mask_is_used():
    rng = np.random.default_rng(1)
    rgb = rng.integers(0, 255, (200, 200, 3), dtype=np.uint8)
    sure = mask(box=(slice(60, 140), slice(50, 150)))
    out = model_cut(rgb, sure)
    assert out is not None and out[100, 100, 3] == 255 and out[10, 10, 3] == 0
    assert model_cut(rgb, mask(box=(slice(60, 140), slice(50, 150)), value=0.5)) is None     # the model cannot tell
    assert model_cut(rgb, mask()) is None


def test_cut_photo_end_to_end():
    rgb, box = scene()
    im = Image.fromarray(rgb)
    out = cut_photo(im, lambda _: Image.fromarray((mask(box=box) * 255).astype("uint8")))
    assert out.mode == "RGBA" and out.getpixel((100, 100))[3] == 255 and out.getpixel((5, 5))[3] == 0
    # a "transparent" photo that is really a white square with a clear margin is cut like any other
    framed = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    ImageDraw.Draw(framed).rectangle((20, 20, 180, 180), fill=(255, 255, 255, 255))
    ImageDraw.Draw(framed).rectangle((50, 60, 150, 140), fill=(20, 20, 20, 255))
    cut = cut_photo(framed, lambda _: Image.fromarray((mask(box=box) * 255).astype("uint8")))
    assert cut.getpixel((100, 100))[3] == 255 and cut.getpixel((30, 30))[3] == 0
    noise = Image.fromarray(np.random.default_rng(2).integers(0, 255, (200, 200, 3), dtype=np.uint8))
    assert cut_photo(noise, lambda _: Image.new("L", (200, 200), 128)) is None


def test_text_and_badges_printed_on_the_background_are_dropped_but_missed_parts_are_not():
    rgb, box = scene()
    rgb[10:20, 30:170] = 30                                          # a slogan across the top, well away from the product
    rgb[60:140, 150:170] = 20                                        # a part joined to the product that the model missed
    out = exact_cut(rgb, mask(box=box), WHITE)
    assert out[15, 100, 3] == 0                                      # the slogan goes
    assert out[100, 160, 3] == 255 and out[100, 100, 3] == 255       # the joined part and the product stay
    both = mask(box=box)
    both[10:20, 30:170] = 1.0                                        # same slogan, but the model says it is part of the product
    assert exact_cut(rgb, both, WHITE)[15, 100, 3] == 255
    assert exact_cut(rgb, mask(), WHITE)[100, 100, 3] == 255         # a model that saw nothing does not empty the picture


def test_a_badge_the_model_also_marked_is_dropped_but_a_second_product_is_not():
    rgb, box = scene()
    rgb[8:16, 20:40] = 30                                            # a feature badge in the corner
    both = mask(box=box)
    both[8:16, 20:40] = 1.0                                          # the model marks it as an object of its own
    out = exact_cut(rgb, both, WHITE)
    assert out[12, 30, 3] == 0 and out[100, 100, 3] == 255
    rgb2, _ = scene()
    rgb2[150:190, 60:140] = 40                                       # a second item of similar size (a card beside its box)
    two = mask(box=box)
    two[150:190, 60:140] = 1.0
    assert exact_cut(rgb2, two, WHITE)[170, 100, 3] == 255
