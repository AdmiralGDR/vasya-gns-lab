#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate src/vasya/data/catalog.json (186 entries) from the appliance resolution data.

usage: build_catalog.py RESOLUTION_DIR [PACK_JSON]
Inputs (read-only): RESOLUTION_DIR/reports/BLOCK_RESOLUTION_MATRIX.csv, RESOLUTION_DIR/canonical/blocks.json
(one record per GNS3 registry appliance, with its .gns3a path), and the payload manifest
(default: packaging/payload/manifests/pack.json, the public blocks). A block is READY only if it
is in the payload; vendor images that must be supplied by the user stay NEEDS_IMAGE.
"""
import csv, json, sys
from pathlib import Path

if len(sys.argv) < 2:
    sys.exit(__doc__)
RES = Path(sys.argv[1])
PACK = Path(sys.argv[2] if len(sys.argv) > 2 else
            Path(__file__).resolve().parent.parent / "packaging/payload/manifests/pack.json")
OUT = Path(__file__).resolve().parent.parent / "src/vasya/data/catalog.json"

STATUS = {
    "READY_DOWNLOADED": "READY", "READY_LOCAL": "READY", "READY_BUILT": "READY",
    "USER_SUPPLIED_REQUIRED": "NEEDS_IMAGE", "FREE_DIRECT": "NEEDS_DOWNLOAD",
    "FREE_REGISTRATION": "NEEDS_REGISTRATION", "REGISTRATION_REQUIRED": "NEEDS_REGISTRATION",
    "PAID_REQUIRED": "NEEDS_LICENSE", "SERVICE_CONTRACT_REQUIRED": "NEEDS_LICENSE",
    "TRIAL_AVAILABLE": "NEEDS_LICENSE", "OBSOLETE": "OBSOLETE",
    "MISSING_UPSTREAM": "UNAVAILABLE", "UNKNOWN": "UNAVAILABLE",
}
PURPOSE = {
    "router": ("Маршрутизация, протоколы динамической маршрутизации, WAN",
               "Routing, dynamic routing protocols, WAN"),
    "multilayer_switch": ("Коммутация L2/L3, VLAN, STP", "L2/L3 switching, VLANs, STP"),
    "firewall": ("Межсетевой экран, NAT, VPN, безопасность", "Firewall, NAT, VPN, security"),
    "guest": ("Конечный узел: хост, сервер, клиент, инструменты",
              "End host: client, server, tooling"),
}
CAT_RU = {"router": "Маршрутизатор", "multilayer_switch": "Коммутатор",
          "firewall": "Межсетевой экран", "guest": "Хост / сервис"}


def main():
    rows = list(csv.DictReader(open(RES / "reports/BLOCK_RESOLUTION_MATRIX.csv", encoding="utf-8")))
    canon = {b["block_id"]: b for b in json.load(open(RES / "canonical/blocks.json", encoding="utf-8"))}
    pack = {b["block_id"]: b for b in json.load(open(PACK, encoding="utf-8"))["blocks"]}
    out = []
    for r in rows:
        bid = r["block_id"]
        c = canon.get(bid, {})
        desc = ""
        tp = c.get("template_path")
        if tp and Path(tp).exists():
            try:
                desc = (json.load(open(tp, encoding="utf-8")).get("description") or "").strip()
            except Exception:
                pass
        st = STATUS.get(r["final_state"], "UNAVAILABLE")
        if st == "READY" and bid not in pack:
            st = "NEEDS_IMAGE"
        p = pack.get(bid, {})
        cat = r["category"] or c.get("category") or "guest"
        images = [{"filename": e.get("filename"), "size": e.get("filesize"),
                   "md5": e.get("md5sum"), "url": e.get("download_url") or ""}
                  for e in c.get("expected_images") or []]
        out.append({
            "block_id": bid, "name": r["block_name"], "vendor": r["vendor"],
            "product": r["product"], "version": r["version"], "category": cat,
            "category_ru": CAT_RU.get(cat, cat), "runtime": r["template_type"],
            "architecture": r["architecture"],
            "purpose_ru": PURPOSE.get(cat, PURPOSE["guest"])[0],
            "purpose_en": PURPOSE.get(cat, PURPOSE["guest"])[1],
            "description": desc[:1200],
            "resources": {"ram_mb": c.get("ram") or p.get("ram"), "cpus": c.get("cpus") or p.get("cpus"),
                          "kvm": c.get("kvm"), "adapters": c.get("adapter_count") or p.get("adapters"),
                          "console": c.get("console_type") or p.get("console_type")},
            "required_images": images,
            "docker_image": c.get("docker_image") or p.get("docker_image") or None,
            "status": st, "source_state": "AUTO_DOWNLOAD" if bid in pack else r["final_state"], "availability": r["availability"],
            "reason": r["reason"], "action_required": r["action_required"],
            "vendor_url": c.get("vendor_url") or "", "product_url": c.get("product_url") or "",
            "packaged": bid in pack,
            "packaged_bytes": sum(i.get("size") or 0 for i in p.get("images") or []),
        })
    out.sort(key=lambda e: (e["status"] != "READY", e["name"].lower()))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    json.dump({"generated_from": ["GNS3 registry appliance files (src/vasya/data/appliances)",
                                  "packaging/payload/manifests/pack.json"], "count": len(out), "entries": out},
              open(OUT, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    from collections import Counter
    print(len(out), Counter(e["status"] for e in out))


if __name__ == "__main__":
    main()
