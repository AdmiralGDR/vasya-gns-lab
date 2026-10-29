#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Merge template fixes tested on a real install (a directory of exported templates) into
src/vasya/data/appliance_fixes/<block_id>.json. Accepts GNS3 template JSON (as exported
from /v2/templates) or {"template": {...}}; file stem or its "block_id" key names the block.
Only catalog.fixups.FIX_FIELDS are kept. Prints what changed; never touches the source dir."""
import argparse, hashlib, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "src"))
from vasya.catalog.fixups import FIX_FIELDS  # noqa: E402

ALIASES = {"openwrt": "openwrt-realview", "puppy": "puppy-linux", "internet": "internet",
           "openwrt realview": "openwrt-realview", "puppy linux": "puppy-linux"}
IMAGE_SLOTS = ("hda_disk_image", "hdb_disk_image", "cdrom_image", "kernel_image", "initrd")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="directory with exported template JSON files (after-*.json, *.gns3a)")
    ap.add_argument("--out", default=str(HERE / "src/vasya/data/appliance_fixes"))
    a = ap.parse_args()
    src, out = Path(a.src), Path(a.out)
    if not src.is_dir():
        print(f"no fixes at {src} — nothing merged"); return 0
    out.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.glob("*.json")) + sorted(src.glob("*.gns3a")):
        if f.name.startswith("before-"):
            continue  # the pre-fix state; only kept as provenance
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except ValueError as e:
            print(f"SKIP {f.name}: not JSON ({e})"); continue
        tpl = d.get("template") or d.get("qemu") or d
        bid = d.get("block_id") or ALIASES.get(str(tpl.get("name", "")).lower()) or \
            ALIASES.get(f.stem.split(".")[0].lower(), f.stem)
        keep = {k: v for k, v in tpl.items() if k in FIX_FIELDS}
        if not keep:
            print(f"SKIP {f.name}: no overridable fields"); continue
        rec = {"block_id": bid, "source": f.name,
               "source_sha256": hashlib.sha256(f.read_bytes()).hexdigest(), "template": keep,
               # image slots are decided by the plan (CAS names); kept here so tests can prove
               # the generated template puts the same files in the same slots as the tested fix
               "proven_image_slots": {k: tpl.get(k) for k in IMAGE_SLOTS if tpl.get(k)},
               "proven_on": "Pop!_OS 24.04, isolated GNS3 2.2.61"}
        before = f.with_name(f.name.replace("after-", "before-", 1))
        if f.name.startswith("after-") and before.exists():
            b = json.loads(before.read_text(encoding="utf-8"))
            rec["changed_from"] = {k: b.get(k) for k in sorted(set(b) | set(tpl)) if b.get(k) != tpl.get(k)}
        (out / f"{bid}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False))
        print(f"MERGED {f.name} -> {bid}: {sorted(keep)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
