#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Refresh an existing build stage in place (no Pack re-read, no payload re-link):
App/vasya + top-level launchers from the repo, the bundled gns3server docker patch, Docs, VERSION and
BUNDLE_MANIFEST.json file hashes. Used when only VASYA code/docs/patches changed since build_bundle.py."""
import argparse, json, shutil, sys, hashlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    ap.add_argument("--docs", default=str(REPO / "docs"))
    a = ap.parse_args()
    top = Path(a.stage); app = top / "App"
    man_p = top / "BUNDLE_MANIFEST.json"
    assert man_p.exists() and (app / "runtime" / "gns3server").is_dir(), "not a build stage"
    ign = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.rmtree(app / "vasya")
    shutil.copytree(REPO / "src" / "vasya", app / "vasya", ignore=ign)
    lx = REPO / "packaging" / "linux"
    for n in ("vasya", "vasya-gns-manager"):
        for d in (top, app):
            shutil.copy2(lx / n, d / n)
    shutil.copy2(lx / "install.sh", top / "install.sh")
    from vasya.runtime.docker_backend import patch_gns3server, patch_init_su, patch_record
    gs = app / "runtime" / "gns3server"
    res = patch_gns3server(gs)
    res4 = patch_init_su(gs)
    bad = [r for r in res + res4 if r[1] not in ("PATCHED", "ALREADY", "UPGRADED")]
    assert len(res) == 4 and len(res4) == 4 and not bad, (res, res4)
    (gs / "VASYA_PATCHES.json").write_text(json.dumps(patch_record(gs, app), indent=1))
    if Path(a.docs).exists():
        shutil.rmtree(top / "Docs", ignore_errors=True)
        shutil.copytree(a.docs, top / "Docs")
    man = json.load(open(man_p))
    files = {}
    for p in sorted(top.rglob("*")):
        if p.is_file() and not p.is_symlink():
            rel = str(p.relative_to(top))
            if rel.startswith("Payload/images/sha256/") or rel == "BUNDLE_MANIFEST.json":
                continue
            files[rel] = sha(p)
    old = man.get("files", {})
    man["files"] = files
    man["apparent_bytes"] = sum(p.stat().st_size for p in top.rglob("*")
                                if p.is_file() and not p.is_symlink() and p.name != "BUNDLE_MANIFEST.json")
    json.dump(man, open(man_p, "w"), indent=1)
    changed = sorted(k for k in files if old.get(k) != files[k])
    print(json.dumps({"patch": res, "init_su": res4, "changed": len(changed), "removed": sorted(set(old) - set(files)),
                      "sample": changed[:40]}, indent=1, default=str))


if __name__ == "__main__":
    main()
