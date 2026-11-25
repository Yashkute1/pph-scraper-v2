"""Seal the Amazon scrape so it can travel through a public repository.

Amazon's rules do not allow its data to be republished, but the scrape has to get from GitHub to the server. The scrape
job seals it to the public key in tools/amazon_scrape.pub; only the server holds the private key, which it makes itself
(ensure_key) and which never leaves it."""
import base64
import gzip
import json
import os
import pathlib

from nacl.public import PrivateKey, PublicKey, SealedBox

PUBLIC = pathlib.Path(__file__).resolve().parent.parent / "tools" / "amazon_scrape.pub"
KEY_NAME = "amazon_scrape.key"
PUB_NAME = "amazon-key.pub"


def _b64(raw):
    return base64.b64encode(raw).decode()


def seal(doc, public_b64):
    box = SealedBox(PublicKey(base64.b64decode(public_b64.strip())))
    return {"sealed": _b64(box.encrypt(gzip.compress(json.dumps(doc, default=str).encode())))}


def unseal(envelope, private_b64):
    box = SealedBox(PrivateKey(base64.b64decode(private_b64.strip())))
    return json.loads(gzip.decompress(box.decrypt(base64.b64decode(envelope["sealed"]))))


def ensure_key(state, exports):
    """Make the private key once, readable by this account only, and publish its public half where the site serves it."""
    state, exports = pathlib.Path(state), pathlib.Path(exports)
    state.mkdir(parents=True, exist_ok=True)
    exports.mkdir(parents=True, exist_ok=True)
    path = state / KEY_NAME
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(_b64(bytes(PrivateKey.generate())) + "\n")
    key = PrivateKey(base64.b64decode(path.read_text().strip()))
    (exports / PUB_NAME).write_text(_b64(bytes(key.public_key)) + "\n")
    return path
