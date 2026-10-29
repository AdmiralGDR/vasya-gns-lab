#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Write docs/RELEASE_SOURCES.md from src/vasya/data/third_party.lock.

usage: scripts/lock_report.py [OUT]   (default docs/RELEASE_SOURCES.md)
"""
import json, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOCK = REPO / "src" / "vasya" / "data" / "third_party.lock"

HEAD = """# Release sources

Where every third-party file used by VASYA GNS LAB comes from. This page is generated from
`src/vasya/data/third_party.lock` by `scripts/lock_report.py`; edit the lock, not this page.

* **VERIFIED**: the file was downloaded from the URL on the date shown and its SHA-256 matched.
* **UNVERIFIED**: the URL could not be checked (see the reason). The installer still downloads it and
  still refuses any file whose SHA-256 differs from the pin; if no URL works the device is shown as
  "image not available".

## GNS3 server

Release packages ship GNS3 server 2.2.61 from PyPI (`gns3-server==2.2.61`), source
https://github.com/GNS3/gns3-server/tree/v2.2.61, with the patches in `src/vasya/data/patches/`.

## Appliance files

`src/vasya/data/appliances/` = https://github.com/GNS3/gns3-registry at commit
`0c04ba6100a2fed7f25d9bac5fc289d836db27fa` (unmodified). `packaging/payload/appliances/ntopng/ntopng.gns3a`
comes from commit `8ce90a6a35aaddb85bb10413a46fdf98f0993023`.
"""


def row(*c):
    return "| " + " | ".join(str(x) for x in c) + " |"


def lvl(e):
    v = e.get("verified", {})
    return v.get("level", "UNVERIFIED") + (f" ({v['on']})" if v.get("on") else "")


def main():
    lock = json.loads(LOCK.read_text())
    out = [HEAD, f"Lock generated: {lock.get('generated', '?')}\n"]
    out += ["## Helper programs (Linux x86_64, downloaded when not installed)\n",
            row("Program", "Version", "License", "Package URL", "Package SHA-256", "Source package", "Source SHA-256", "Status"),
            row(*["---"] * 8)]
    for n, e in lock["tools"].items():
        p, s = e["package"], e.get("source", {})
        out.append(row(n, e["version"], e["license"], p["urls"][0], f"`{p['sha256']}`",
                       (s.get("urls") or ["-"])[0], f"`{s.get('sha256', '-')}`", lvl(e)))
    out += ["\n## Qt platform libraries (downloaded when missing)\n",
            row("Library", "Package", "Version", "License", "URL", "SHA-256", "Status"), row(*["---"] * 7)]
    for n, e in lock["libraries"].items():
        p = e["package"]
        out.append(row(n, e["package_name"], e["version"], e["license"], p["urls"][0], f"`{p['sha256']}`", lvl(e)))
    out += ["\n## Device images (public, downloaded from the publisher)\n",
            row("File", "Devices", "URL", "Content SHA-256", "Status"), row(*["---"] * 5)]
    for sha, e in sorted(lock["images"].items(), key=lambda kv: kv[1]["filename"]):
        st = lvl(e)
        if e.get("verified", {}).get("level") != "VERIFIED":
            st += ": " + e["verified"].get("why", "")
        out.append(row(e["filename"], ", ".join(e["blocks"]), e["urls"][0] if e["urls"] else "-", f"`{sha}`", st))
    out += ["\n## Docker images (pulled by digest)\n", row("Image", "Pinned reference", "Image ID", "Status"),
            row(*["---"] * 4)]
    for n, e in sorted(lock["docker"].items()):
        out.append(row(n, f"`{e['pinned']}`", f"`{e['image_id']}`", lvl(e)))
    out.append("\nLicensed vendor images (Cisco IOS and similar) are not listed here: they are never downloaded from a "
               "public location. See [PRIVATE_IMAGES.md](PRIVATE_IMAGES.md).\n")
    dst = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "docs" / "RELEASE_SOURCES.md"
    dst.write_text("\n".join(out))
    print(dst)


if __name__ == "__main__":
    main()
