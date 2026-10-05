import io

import pytest
from PIL import Image, ImageDraw

from tools.cutouts import (cutout_key, encode, finish, in_shard, merge_manifest, parse_manifest, safe_url, todo, usable)


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
