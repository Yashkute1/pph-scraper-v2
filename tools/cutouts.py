"""Remove the background from product photos, so the website can show parts on its dark pages.

Runs in GitHub Actions in three steps, so the database password is never in the same process as code that
downloads from store servers:

    python -m tools.cutouts list  todo.txt --shard 0/6 --limit 1500      # needs MONGO_URI; writes "key url" lines
    python -m tools.cutouts make  todo.txt out/                          # no secrets; downloads, cuts, writes WebP
    python -m tools.cutouts merge branch_dir/ out1/ out2/ ...            # no secrets; copies files, updates manifest

Model: IS-Net "general use" through the rembg library (both open source). About 2 seconds per photo on a free runner.
A photo whose result looks wrong (nothing removed, or almost everything removed) is recorded as "skip"; the website
then shows the store photo on a white tile, as before."""
import hashlib
import io
import ipaddress
import os
import shutil
import sys
from urllib.parse import urlsplit

MAX_SIDE = 512
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
    rgba.thumbnail((max_side, max_side))
    return rgba


def encode(rgba):
    buf = io.BytesIO()
    rgba.save(buf, "WEBP", quality=80, method=6)
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


def cmd_list(path, shard, shards, limit):
    from pymongo import MongoClient

    from pph import DB_NAME
    uri = os.environ.get("MONGO_URI")
    if not uri:
        raise SystemExit("MONGO_URI is not set")
    db = MongoClient(uri, serverSelectionTimeoutMS=20000)[DB_NAME]
    done = parse_manifest(open("manifest.txt").read()) if os.path.exists("manifest.txt") else {}
    urls = (d.get("image") for d in db.products_v2.find({"image": {"$nin": ["", None]}}, {"image": 1})
            .sort([("any_stock", -1), ("store_count", -1)]))
    rows = todo(urls, done, shard, shards, limit)
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(f"{k} {u}\n" for k, u in rows)
    print({"todo": len(rows), "already_done": len(done)})


def cmd_make(path, out):
    from PIL import Image
    from rembg import new_session, remove
    Image.MAX_IMAGE_PIXELS = 40_000_000
    session = new_session("isnet-general-use")
    os.makedirs(out, exist_ok=True)
    results = {}
    for line in open(path, encoding="utf-8"):
        key, _, url = line.strip().partition(" ")
        if not key or not url:
            continue
        status = "skip"
        try:
            data = _download(url)
            if data:
                im = Image.open(io.BytesIO(data))
                im.load()
                has_alpha = im.mode in ("RGBA", "LA") and im.convert("RGBA").getchannel("A").getextrema()[0] < 16
                rgba = im.convert("RGBA")
                if not (has_alpha and usable(rgba)):                 # a store photo that is already cut out is kept as it is
                    rgb = im.convert("RGB")
                    rgb.thumbnail((1024, 1024))
                    rgba = remove(rgb, session=session, post_process_mask=True)
                if usable(rgba):
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
        return cmd_list(a[1], shard, shards, limit)
    if a[:1] == ["make"]:
        return cmd_make(a[1], a[2])
    if a[:1] == ["merge"]:
        return cmd_merge(a[1], a[2:])
    raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
