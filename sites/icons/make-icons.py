#!/usr/bin/env python3
"""Build the KTP favicon set from the master logo.

The estate used to serve `ktp-logo.png` -- a 2560x2560 PNG, 264 KB -- renamed to
favicon.ico, for a 16px browser tab. This produces a real multi-size .ico plus the two
PNG sizes browsers actually ask for, from the same artwork.

    python3 make-icons.py [master.png]

Deploy the three outputs to each docroot (/var/www/{fastdl,netcode,ktp-profiles,
ktp-bundles,anticheat,anticheat-admin,support.ktpdod.com}).

⚠️ Do NOT replace `ktp-logo.png` with a downscaled version. /var/www/anticheat/index.html
renders it as an <img>, so it is a visible asset, not just an icon source.
"""
import os
import sys

from PIL import Image

MASTER = sys.argv[1] if len(sys.argv) > 1 else "ktp-logo.png"
OUT = os.path.dirname(os.path.abspath(__file__))

src = Image.open(MASTER).convert("RGBA")
src.resize((256, 256), Image.LANCZOS).save(
    os.path.join(OUT, "favicon.ico"), format="ICO",
    sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
src.resize((180, 180), Image.LANCZOS).save(
    os.path.join(OUT, "apple-touch-icon.png"), format="PNG", optimize=True)
src.resize((32, 32), Image.LANCZOS).save(
    os.path.join(OUT, "favicon-32.png"), format="PNG", optimize=True)

for f in ("favicon.ico", "favicon-32.png", "apple-touch-icon.png"):
    print("%-22s %7d bytes" % (f, os.path.getsize(os.path.join(OUT, f))))
