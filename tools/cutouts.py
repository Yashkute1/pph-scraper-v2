"""Remove the background from product photos, so the website can show parts on its dark pages.

Runs in GitHub Actions in three steps, so the database password is never in the same process as code that
downloads from store servers:

    python -m tools.cutouts list  todo.txt --shard 0/16 --limit 500      # needs MONGO_URI; writes "key url" lines
    python -m tools.cutouts make  todo.txt out/                          # no secrets; downloads, cuts, writes WebP
    python -m tools.cutouts merge branch_dir/ out1/ out2/ ...            # no secrets; copies files, updates manifest

How a photo is cut. Most store photos sit on a plain background, and for those the background colour is known
exactly, so it is removed by arithmetic rather than by guessing: a pixel is as see-through as it is close to that
colour, and the colour that bled into edge pixels is taken back out. A segmentation model (BiRefNet "general lite",
MIT licence, run through the rembg library) is only asked the one thing arithmetic cannot know: whether a
background-coloured area is part of the product (a white label, a white headset) or not (the gap inside a handle).
It can therefore no longer eat dark parts of a product or leave a white fringe, which is what the first version did.
A photo without a plain background is cut by the model alone, and only when the model is sure; otherwise it is
recorded as "skip" and the website shows the whole photo on a tile."""
import hashlib
import io
import ipaddress
import os
import shutil
import sys
from urllib.parse import urlsplit

MAX_SIDE = 640
WORK_SIDE = 1024                           # photos are cut at this size, then reduced
MODEL = "birefnet-general-lite"
MAX_BYTES = 8 * 1024 * 1024
MIN_KEEP, MAX_KEEP = 0.02, 0.97            # share of pixels kept; outside this the cut is not trusted


def cutout_key(url):
    return hashlib.sha256(url.encode()).hexdigest()[:24]


def in_shard(key, shard, shards):
    return int(key[:8], 16) % shards == shard


def parse_manifest(text):
    out = {}
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] in ("ok", "skip"):
            out[parts[0]] = parts[1]
    return out


def merge_manifest(old, new):
    merged = dict(old)
    for k, v in new.items():
        if v == "ok" or k not in merged:
            merged[k] = v
    return "".join(f"{k} {merged[k]}\n" for k in sorted(merged))


def safe_url(url):
    """https, a public host name or public address, no credentials."""
    try:
        u = urlsplit(url)
    except (ValueError, AttributeError):
        return False
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not host or u.username or u.password:
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return "." in host and not host.endswith((".local", ".internal", ".localhost")) and host != "localhost"


def todo(urls, done, shard, shards, limit):
    out, seen = [], set()
    for url in urls:
        if not url or not safe_url(url):
            continue
        key = cutout_key(url)
        if key in seen or key in done or not in_shard(key, shard, shards):
            continue
        seen.add(key)
        out.append((key, url))
        if len(out) >= limit:
            break
    return out


def background(rgb):
    """(colour, plain?) read from the outer ring of the picture. `rgb` is an HxWx3 uint8 array.

    Plain means most of the ring is one colour and little of it is a gradient. A product that touches the edge is
    fine: its pixels are far from the background colour, not slightly off it."""
    import numpy as np
    h, w, _ = rgb.shape
    r = max(2, round(min(h, w) * 0.015))
    ring = np.concatenate([rgb[:r].reshape(-1, 3), rgb[-r:].reshape(-1, 3), rgb[:, :r].reshape(-1, 3), rgb[:, -r:].reshape(-1, 3)]).astype(np.int32)
    q = ring // 8
    codes = q[:, 0] * 1024 + q[:, 1] * 32 + q[:, 2]
    col = np.median(ring[codes == np.bincount(codes).argmax()], axis=0)
    d = np.abs(ring - col).max(axis=1)
    near, mid = float((d <= 10).mean()), float(((d > 10) & (d <= 45)).mean())
    return col, (near >= 0.6 and mid <= 0.10) or (near >= 0.35 and mid <= 0.03)


def _erode(mask, k):
    import numpy as np
    from PIL import Image, ImageFilter
    return np.asarray(Image.fromarray((mask * 255).astype("uint8")).filter(ImageFilter.MinFilter(k))) > 0


def _dilate(mask, k):
    import numpy as np
    from PIL import Image, ImageFilter
    return np.asarray(Image.fromarray((mask * 255).astype("uint8")).filter(ImageFilter.MaxFilter(k))) > 0


def _blur(channel, radius):
    import numpy as np
    from PIL import Image, ImageFilter
    return np.asarray(Image.fromarray(channel.astype("uint8")).filter(ImageFilter.BoxBlur(radius)), dtype=np.float32)


def exact_cut(rgb, model, col):
    """Cut a photo whose background colour `col` is known. `model` is the model's mask, HxW floats from 0 to 1.

    1. Every pixel is at least as solid as its distance from the background colour demands, so dark and coloured
       parts stay whatever the model says. Faint differences (a soft shadow) stay faint and come out dark.
    2. The model can only add to that. A background-coloured pixel is kept only well inside what the model calls
       product, which drops the thin light fringe models leave around edges.
    3. Pixels on the outline are a blend of product and background. They are un-blended against the product colour
       just inside them, so the outline is smooth and carries none of the background colour."""
    import numpy as np
    f = rgb.astype(np.float32)
    diff = f - col
    dist = np.abs(diff).max(axis=2)
    k = max(5, round(max(dist.shape) * 0.006)) | 1
    core = _erode(model > 0.5, k)
    m = np.where((dist < 18) & ~core, 0.0, model)
    floor = np.maximum(dist / 255.0, np.clip((dist - 60) / 90.0, 0, 1))
    floor = np.where(dist < 5, 0.0, floor)                           # compression noise in the background
    # Things printed on the background that do not touch the product (a slogan, a row of feature badges) are not the
    # product. A separate island is kept only if the model recognises some of it; a part the model missed is still
    # safe, because it is joined to the rest of the product.
    from scipy import ndimage
    # The model often counts a slogan or a feature badge as an object of its own. Anything it marks that is separate
    # from the main product and much smaller than it is not kept. (A white case stays whole: the model marks it as
    # one region, however many pieces its outline breaks into.)
    islands, count = ndimage.label(dist >= 40)
    regions, n = ndimage.label(_dilate(model > 0.5, 7))
    if n > 1:
        idx = np.arange(1, n + 1)
        size = ndimage.sum_labels(np.ones_like(model), regions, idx)
        rows = np.array(ndimage.center_of_mass(np.ones_like(model), regions, idx))[:, 0] / dist.shape[0]
        main = int(size.argmax())
        drop = size < 0.04 * size[main]                              # a speck beside the product
        drop |= (size < 0.15 * size[main]) & ((rows < 0.2) | (rows > 0.88))      # a badge in the top or bottom margin
        for r in np.flatnonzero(~drop):                              # lettering: many small pieces, none of them the bulk
            if r == main or size[r] > 0.6 * size[main]:
                continue
            pieces = np.bincount(islands[(regions == r + 1) & (islands > 0)])
            pieces = pieces[pieces > 0]
            if len(pieces) >= 6 and pieces.max() < 0.35 * pieces.sum():
                drop[r] = True
        minor = np.concatenate([[False], drop])[regions]
        model = np.where(minor, 0.0, model)
        m = np.where(minor, 0.0, m)
    if count > 1:
        idx = np.arange(1, count + 1)
        seen = ndimage.sum_labels(model > 0.5, islands, idx) / np.maximum(ndimage.sum_labels(np.ones_like(model), islands, idx), 1)
        stray = np.concatenate([[False], seen < 0.03])[islands]
        if stray.any() and not stray[dist >= 40].all():              # never drop everything
            floor = np.where(_dilate(stray, 5), np.minimum(floor, m), floor)
    alpha = np.maximum(floor, m)

    gone = alpha < 0.05
    band = _dilate(gone, 5) & ~gone                                  # the two pixels next to removed background
    solid = (alpha > 0.95) & ~_dilate(gone, 7)
    weight = _blur(solid * 255.0, 4) / 255.0
    inside = np.dstack([_blur(f[..., c] * solid, 4) for c in range(3)]) / np.maximum(weight, 1e-3)[..., None]
    span = inside - col
    power = (span * span).sum(axis=2)
    ok = band & (weight > 0.04) & (np.abs(span).max(axis=2) > 40)
    unmixed = np.clip((diff * span).sum(axis=2) / np.maximum(power, 1.0), 0, 1)
    alpha = np.where(ok, unmixed, alpha)

    a = np.clip(alpha, 1e-3, 1)[..., None]
    fg = np.where(alpha[..., None] >= 0.999, f, np.clip(col + diff / a, 0, 255))      # take the background back out
    return np.dstack([fg, alpha * 255]).round().astype(np.uint8)


def model_cut(rgb, model):
    """For a photo with no plain background: the model's mask as it is, or None when the model is not sure."""
    import numpy as np
    kept = float((model > 0.5).mean())
    unsure = float(((model > 0.15) & (model < 0.85)).mean())
    if kept <= 0 or unsure > 0.25 * kept:
        return None
    return np.dstack([rgb, (model * 255).round()]).astype(np.uint8)


def cut_photo(im, mask_of, debug=None):
    """PIL image in, RGBA PIL image out, or None when no trustworthy cut exists. `mask_of(rgb_image)` returns an L image."""
    import numpy as np
    from PIL import Image
    if im.mode in ("RGBA", "LA", "P"):
        # A photo that arrives with transparency is laid on white and cut like any other. Stores often ship a white
        # square with a transparent margin, which is not a cut-out at all.
        rgba = im.convert("RGBA")
        flat = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        flat.alpha_composite(rgba)
        im = flat
    im = im.convert("RGB")
    im.thumbnail((WORK_SIDE, WORK_SIDE), Image.LANCZOS)
    rgb = np.asarray(im)
    raw = mask_of(im).convert("L").resize(im.size)
    if debug:                                                        # keep what the model saw and said, to study a bad cut
        im.save(debug + "_in.png")
        raw.save(debug + "_m.png")
    model = np.asarray(raw, dtype=np.float32) / 255.0
    col, plain = background(rgb)
    out = exact_cut(rgb, model, col) if plain else model_cut(rgb, model)
    if out is None:
        return None
    rgba = Image.fromarray(out, "RGBA")
    return rgba if usable(rgba) else None


def usable(rgba):
    alpha = rgba.getchannel("A")
    kept = sum(alpha.histogram()[128:]) / float(alpha.width * alpha.height)
    return MIN_KEEP <= kept <= MAX_KEEP


def finish(rgba, max_side=MAX_SIDE):
    """Crop to the subject with a small transparent margin, then cap the size."""
    box = rgba.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    if box:
        pad = max(2, round(max(box[2] - box[0], box[3] - box[1]) * 0.02))
        rgba = rgba.crop((box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad))
    rgba.thumbnail((max_side, max_side), 1)                          # 1 = Lanczos
    return rgba


def encode(rgba):
    buf = io.BytesIO()
    rgba.save(buf, "WEBP", quality=76, method=6, alpha_quality=90)
    return buf.getvalue()


# ---- steps -------------------------------------------------------------------------------------------------------

def _resolves_public(host):
    import socket
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    return bool(infos) and all(ipaddress.ip_address(i[4][0]).is_global for i in infos)


def _download(url):
    import urllib.request

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None                      # a redirect could point anywhere; treat it as a failure

    if not safe_url(url) or not _resolves_public(urlsplit(url).hostname):
        return None
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; PCPartHunt image fetch; +https://pcparthunt.com/about)",
                                               "Accept": "image/*"})
    with urllib.request.build_opener(NoRedirect).open(req, timeout=20) as r:
        if not (r.headers.get("Content-Type") or "").startswith("image/"):
            return None
        data = r.read(MAX_BYTES + 1)
    return data if len(data) <= MAX_BYTES else None


def cmd_list(path, shard, shards, limit, only=None):
    from pymongo import MongoClient

    from pph import DB_NAME
    uri = os.environ.get("MONGO_URI")
    if not uri:
        raise SystemExit("MONGO_URI is not set")
    db = MongoClient(uri, serverSelectionTimeoutMS=20000)[DB_NAME]
    done = parse_manifest(open("manifest.txt").read()) if os.path.exists("manifest.txt") else {}
    urls = (d.get("image") for d in db.products_v2.find({"image": {"$nin": ["", None]}}, {"image": 1})
            .sort([("any_stock", -1), ("store_count", -1)]))
    if only is not None:                                             # a hand-picked set, for checking a change before a full run
        seen, rows = set(), []
        for u in urls:
            if u and safe_url(u) and cutout_key(u) in only and cutout_key(u) not in seen:
                seen.add(cutout_key(u)); rows.append((cutout_key(u), u))
    else:
        rows = todo(urls, done, shard, shards, limit)
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(f"{k} {u}\n" for k, u in rows)
    print({"todo": len(rows), "already_done": len(done)})


def _session():
    import onnxruntime as ort
    from rembg import new_session
    opts = ort.SessionOptions()
    opts.enable_cpu_mem_arena = False                                # the model's working memory is returned after each photo
    opts.enable_mem_pattern = False
    return new_session(MODEL, sess_opts=opts)


def cmd_make(path, out):
    from PIL import Image
    from rembg import remove
    Image.MAX_IMAGE_PIXELS = 40_000_000
    session = _session()
    mask_of = lambda rgb: remove(rgb, session=session, only_mask=True, post_process_mask=False)
    os.makedirs(out, exist_ok=True)
    results = {}
    for line in open(path, encoding="utf-8"):
        key, _, url = line.strip().partition(" ")
        if not key or not url:
            continue
        status = "skip"
        try:
            try:
                data = _download(url)
            except OSError as e:                                     # the store did not answer: leave it for the next run
                print("later", key, type(e).__name__)
                continue
            if data:
                im = Image.open(io.BytesIO(data))
                im.load()
                rgba = cut_photo(im, mask_of, os.path.join(out, key) if os.environ.get("CUTOUT_DEBUG") else None)
                if rgba is not None:
                    os.makedirs(os.path.join(out, key[:2]), exist_ok=True)
                    with open(os.path.join(out, key[:2], key + ".webp"), "wb") as f:
                        f.write(encode(finish(rgba)))
                    status = "ok"
        except Exception as e:                                       # one bad photo must not stop the batch
            print("skip", key, type(e).__name__)
        results[key] = status
    with open(os.path.join(out, "results.txt"), "w") as f:
        f.writelines(f"{k} {v}\n" for k, v in sorted(results.items()))
    print({"ok": sum(v == "ok" for v in results.values()), "skip": sum(v == "skip" for v in results.values())})


def cmd_merge(dest, sources):
    new = {}
    for src in sources:
        res = os.path.join(src, "results.txt")
        if not os.path.exists(res):
            continue
        for key, status in parse_manifest(open(res).read()).items():
            f = os.path.join(src, key[:2], key + ".webp")
            if status == "ok" and os.path.exists(f) and key.isalnum():
                os.makedirs(os.path.join(dest, key[:2]), exist_ok=True)
                shutil.copyfile(f, os.path.join(dest, key[:2], key + ".webp"))
                new[key] = "ok"
            else:
                new[key] = "skip"
    mpath = os.path.join(dest, "manifest.txt")
    old = parse_manifest(open(mpath).read()) if os.path.exists(mpath) else {}
    text = merge_manifest(old, new)
    with open(mpath, "w") as f:
        f.write(text)
    print({"added": len(new), "total": text.count("\n")})


def main(argv=None):
    a = list(argv or sys.argv[1:])
    if a[:1] == ["list"]:
        shard, shards = (int(x) for x in a[a.index("--shard") + 1].split("/")) if "--shard" in a else (0, 1)
        limit = int(a[a.index("--limit") + 1]) if "--limit" in a else 1500
        only = set(open(a[a.index("--keys") + 1]).read().split()) if "--keys" in a else None
        return cmd_list(a[1], shard, shards, limit, only)
    if a[:1] == ["make"]:
        return cmd_make(a[1], a[2])
    if a[:1] == ["merge"]:
        return cmd_merge(a[1], a[2:])
    raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
