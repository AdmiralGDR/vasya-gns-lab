# SPDX-License-Identifier: GPL-3.0-or-later
"""Dynamips, uBridge, VPCS and the Qt xcb libraries, fetched from their official packages.

GNS3 publishes no stand-alone Linux binaries for Dynamips, uBridge or VPCS; the official
binaries are the GNS3 PPA packages (https://launchpad.net/~gns3/+archive/ubuntu/ppa).
The xcb libraries come from the Ubuntu archive. Each package is pinned in
third_party.lock by URL and SHA-256 of the .deb and of the extracted file. The file is
extracted without root into the download cache; gui_deps places it under <root>/Runtime
with a receipt, so uninstall removes exactly what VASYA created.

When a package cannot be downloaded the component stays missing and the existing
"install it with your package manager" hint is shown; the pinned source archive
(``source`` in the lock) lets anyone rebuild the same version.
"""
from pathlib import Path
from . import download, lock as L, unpack

KINDS = ("tools", "libraries")


def entry(name, lk=None):
    """(kind, lock entry) for a pinned tool or library, else (None, None)."""
    lk = lk or L.load()
    for k in KINDS:
        if name in lk.get(k, {}):
            return k, lk[k][name]
    return None, None


def staged(layout, name, lk=None, opener=None):
    """Verified copy of `name` in the cache. {"status": "OK", "path"} or a FAIL/OFFLINE/UNKNOWN status."""
    kind, e = entry(name, lk)
    if not e or not e.get("package"):
        return {"status": "UNKNOWN", "reason": f"{name} is not pinned in third_party.lock"}
    pk = e["package"]
    cache = download.cache_dir(layout)
    out = cache / "extracted" / pk["member_sha256"] / (pk.get("install_name") or Path(pk["member"]).name)
    if out.is_file() and download.sha256_file(out) == pk["member_sha256"]:
        return {"status": "OK", "path": str(out), "reused": True, "version": e.get("version")}
    deb = cache / pk["sha256"][:16] / Path(pk["urls"][0]).name.replace("%7E", "~")
    r = download.fetch(pk["urls"], deb, pk["sha256"], size=pk.get("size"), opener=opener)
    if r["status"] != "OK":
        return {"status": r["status"], "reason": "; ".join(r["errors"])[-500:]}
    try:
        unpack.deb_extract(deb, pk["member"], out, mode=0o755 if kind == "tools" else 0o644)
    except Exception as e2:
        return {"status": "FAIL", "reason": f"cannot unpack {deb.name}: {e2}"}
    if download.sha256_file(out) != pk["member_sha256"]:
        out.unlink()
        return {"status": "FAIL", "reason": f"{pk['member']} in {deb.name} does not match the pinned sha256"}
    return {"status": "OK", "path": str(out), "reused": False, "version": e.get("version"), "url": r.get("url")}
