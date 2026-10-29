#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build a payload store (manifests + appliances + CAS images) from the 1.0.1 Pack.

Only payload data is taken; the legacy Pack/lib code (incl. the defective
rollback.py 6f657f7a…) is NEVER copied. Images are copied (or hardlinked with
--link) so the source release stays untouched.
usage: make_payload.py SRC_PACK DST [--blocks a,b,c] [--link]
"""
import argparse, json, os, shutil
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("src"); ap.add_argument("dst")
ap.add_argument("--blocks", default=None); ap.add_argument("--link", action="store_true")
a = ap.parse_args()
src, dst = Path(a.src), Path(a.dst)
man = json.load(open(src / "manifests/pack.json"))
if a.blocks:
    want = set(a.blocks.split(","))
    man["blocks"] = [b for b in man["blocks"] if b["block_id"] in want]
man["product_version"] = "1.1.0"
(dst / "manifests").mkdir(parents=True, exist_ok=True)
(dst / "images/sha256").mkdir(parents=True, exist_ok=True)
json.dump(man, open(dst / "manifests/pack.json", "w"), indent=1)
n = 0
for b in man["blocks"]:
    if b.get("template"):
        t = dst / b["template"]; t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src / b["template"], t)
    for im in b.get("images") or []:
        d = dst / "images/sha256" / im["sha256"]
        if d.exists():
            continue
        s = src / "images/sha256" / im["sha256"]
        if a.link:
            os.link(s, d)
        else:
            shutil.copyfile(s, d)
        n += 1
print(f"payload {dst}: {len(man['blocks'])} blocks, {n} images")
