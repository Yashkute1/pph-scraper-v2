"""Temporary: compare background-removal models on the same photos. Not part of the product."""
import io, os, resource, sys, time
from PIL import Image
from rembg import new_session, remove
from tools.cutouts import _download
model = sys.argv[1]
s = new_session(model)
os.makedirs("out", exist_ok=True)
t0, n = time.time(), 0
for line in open("bake/todo.txt"):
    key, _, url = line.strip().partition(" ")
    try:
        data = _download(url)
        if not data:
            continue
        im = Image.open(io.BytesIO(data)); im.load()
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA"); bg = Image.new("RGBA", im.size, (255, 255, 255, 255)); bg.alpha_composite(im); im = bg
        im = im.convert("RGB"); im.thumbnail((1024, 1024), Image.LANCZOS)
        remove(im, session=s, only_mask=True, post_process_mask=False).save(f"out/{key}_m.png"); n += 1
    except Exception as e:
        print("skip", key, type(e).__name__)
line = f"{model}: {n} photos, {(time.time() - t0) / max(n, 1):.1f} s each, peak {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024} MB"
print(line); open("out/timing.txt", "w").write(line + "\n")
