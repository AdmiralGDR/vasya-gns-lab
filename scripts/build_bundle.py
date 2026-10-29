#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage the Linux bundle tree (no archive yet — see build_release.py).

usage: build_bundle.py --out DIR [--profile public|private] [--pack DIR] --pyside DIR --gns3rt DIR [--docs DIR]
  --profile public (default): no images of any kind; the installer downloads public images from
            their official URLs (third_party.lock) and proprietary ones from the user's private source
  --profile private: offline bundle for your own machines (all image blobs hardlinked); never publish it
  --pack    payload metadata (default packaging/payload); the private profile also needs images/sha256
  --pyside  pip --target dir with PySide6_Essentials (pruned here to Widgets/Gui/Core + platform plugins)
  --gns3rt  dir with py310..py313 (pip --target gns3-server==2.2.61 per CPython)
Private profile: images are hardlinked from --pack (no extra disk); identical files across the
gns3server builds are hardlinked so tar stores them once.
"""
import argparse, hashlib, json, os, shutil, subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from vasya import VERSION  # noqa: E402
from vasya.runtime.bundled_server import LAUNCHER  # noqa: E402
from vasya.catalog import fixups as fx  # noqa: E402

PRUNE_LIB = ("Qml", "Quick", "Labs", "Lottie", "Designer", "Help", "Sql", "Test", "UiTools",
             "WaylandCompositor", "WaylandEgl", "Concurrent", "Xml", "PrintSupport", "OpenGLWidgets")
KEEP_PY = {"QtCore", "QtGui", "QtWidgets"}


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 22), b""):
            h.update(c)
    return h.hexdigest()


def prune_pyside(dst):
    ps = dst / "PySide6"
    for p in list(ps.iterdir()):
        n = p.name
        if p.is_file() and n.startswith("Qt") and (n.endswith(".so") or n.endswith(".pyi")) \
                and n.split(".")[0] not in KEEP_PY:
            p.unlink()
        elif p.is_file() and os.access(p, os.X_OK) and not n.endswith(".so") and "." not in n:
            p.unlink()  # Qt Designer, Linguist, Qt Assistant, qmlls: developer tools, not needed
        elif p.is_dir() and n in ("include", "typesystems", "glue", "scripts", "examples", "doc"):
            shutil.rmtree(p)
    qt = ps / "Qt"
    for sub in ("qml", "libexec", "metatypes", "resources/qtwebengine"):
        shutil.rmtree(qt / sub, ignore_errors=True)
    for so in (qt / "lib").glob("libQt6*.so*"):
        mod = so.name[len("libQt6"):].split(".")[0]
        if mod.startswith(PRUNE_LIB):
            so.unlink()
    for d in ("qmltooling", "designer", "sqldrivers", "scenegraph", "qmllint", "assetimporters",
              "renderers", "vectorimageformats"):
        shutil.rmtree(qt / "plugins" / d, ignore_errors=True)
    tr = qt / "translations"
    if tr.exists():
        for f in tr.iterdir():
            if not (f.name.startswith(("qtbase_ru", "qtbase_en"))):
                f.unlink() if f.is_file() else shutil.rmtree(f)
    shutil.rmtree(dst / "bin", ignore_errors=True)
    # every remaining ELF must resolve its Qt deps inside the bundle
    missing = []
    for so in list((qt / "lib").glob("*.so*")) + list((qt / "plugins").rglob("*.so")) + list(ps.glob("*.so")):
        out = subprocess.run(["ldd", str(so)], capture_output=True, text=True).stdout
        for line in out.splitlines():
            if "not found" in line and "libQt6" in line:
                missing.append((so.name, line.strip()))
    bad = sorted({m[0] for m in missing})
    for name in bad:  # plugins that need a pruned lib are removed (e.g. qml-based ones)
        for p in list((qt / "plugins").rglob(name)):
            p.unlink()
    return bad


def dedupe(root):
    seen, n = {}, 0
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            k = (p.stat().st_size, sha(p))
            if k in seen:
                p.unlink(); os.link(seen[k], p); n += 1
            else:
                seen[k] = p
    return n


def is_public_block(b, lock):
    """A block may be listed in a public release only if every image it needs has an official
    public download in third_party.lock (nothing proprietary, nothing that only exists locally)."""
    if b.get("private") or b.get("runtime") == "dynamips":
        return False
    return all(im["sha256"] in lock.get("images", {}) and not lock["images"][im["sha256"]].get("private")
               for im in b.get("images") or [])


def stage_payload(pack, pl, image_dirs=(), profile="public", lock=None):
    """Write Payload/manifests/pack.json + appliances (+ image blobs for the private profile only).

    public : metadata only. No image file is ever copied or linked; blocks whose images have no
             public upstream download (Cisco IOS and other vendor images) are left out entirely.
             The installer downloads the public images from their official URLs.
    private: the offline bundle for your own machines: every image blob is hardlinked.
    Returns (manifest, number of image blobs placed)."""
    if profile not in ("public", "private"):
        raise ValueError(f"unknown profile {profile!r}")
    if lock is None:
        from vasya.fetch import lock as flock
        lock = flock.load()
    pack = Path(pack)
    man = json.load(open(pack / "manifests" / "pack.json", encoding="utf-8"))
    man["product_version"] = VERSION
    if profile == "public":
        dropped = [b["block_id"] for b in man["blocks"] if not is_public_block(b, lock)]
        man["blocks"] = [b for b in man["blocks"] if is_public_block(b, lock)]
        man["excluded_private_blocks"] = dropped
    man["profile"] = profile
    (pl / "manifests").mkdir(parents=True)
    if profile == "private":
        (pl / "images" / "sha256").mkdir(parents=True)
    n_img = 0
    for b in man["blocks"]:
        if b.get("template"):
            t = pl / b["template"]; t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(pack / b["template"], t)   # a copy: the Pack is never written through
            ad = json.load(open(t, encoding="utf-8"))
            ch = fx.patch_gns3a(b["block_id"], ad)
            if ch:
                t.write_text(json.dumps(ad, indent=4, ensure_ascii=False), encoding="utf-8")
                b["fixups"] = list(b.get("fixups") or []) + [f"template fix: {', '.join(ch)}"]
        if profile == "public":
            continue
        for im in b.get("images") or []:
            d = pl / "images" / "sha256" / im["sha256"]
            if not d.exists():
                cands = [pack / "images" / "sha256" / im["sha256"]] + [Path(x) / im["sha256"] for x in image_dirs]
                src = next((c.resolve() for c in cands if c.exists()), None)
                if src is None:
                    sys.exit(f"image blob {im['sha256']} not found in Pack/images or --images dirs")
                if im.get("size") and src.stat().st_size != im["size"]:
                    sys.exit(f"size mismatch for {src}: {src.stat().st_size} != {im['size']}")
                os.link(src, d); n_img += 1
    json.dump(man, open(pl / "manifests" / "pack.json", "w"), indent=1)
    if profile == "public":
        leaked = [str(p) for p in pl.rglob("*") if p.is_file()
                  and p.relative_to(pl).parts[0] not in ("manifests", "appliances")]
        if leaked or (pl / "images").exists():
            sys.exit(f"public payload must not contain images: {leaked[:5]}")
    return man, n_img


def write_third_party(top, app):
    """LICENSE, NOTICE, THIRD_PARTY.md at the top of the bundle, plus THIRD_PARTY/ with the license
    texts and the list of Python packages shipped with gns3server and the manager."""
    for n in ("LICENSE", "NOTICE", "THIRD_PARTY.md"):
        shutil.copy2(REPO / n, top / n)
    tp = top / "THIRD_PARTY"
    tp.mkdir()
    shutil.copy2(REPO / "LICENSE", tp / "GPL-3.0.txt")
    for f in sorted((REPO / "packaging" / "licenses").glob("*.txt")):
        shutil.copy2(f, tp / f.name)
    rows = set()
    for meta in sorted(app.glob("**/*.dist-info/METADATA")):
        name = ver = lic = ""
        for line in meta.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line:
                break
            k, _, v = line.partition(": ")
            if k == "Name": name = v
            elif k == "Version": ver = v
            elif k in ("License-Expression", "License") and not lic: lic = v.splitlines()[0][:80]
            elif k == "Classifier" and v.startswith("License ::") and not lic: lic = v.split("::")[-1].strip()
        if name:
            rows.add(f"{name} {ver}: {lic or 'see package metadata'}")
    (tp / "python-licenses.txt").write_text(
        "Python packages shipped in this bundle (from their package metadata)\n\n" + "\n".join(sorted(rows)) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--pack", default=str(REPO / "packaging" / "payload"),
                    help="payload metadata (manifests/pack.json + appliances); private: also images/sha256")
    ap.add_argument("--profile", choices=["public", "private"], default="public",
                    help="public (default): no images at all, devices download from official upstream "
                         "URLs; private: offline bundle with every image, for your own machines only")
    ap.add_argument("--pyside", required=True); ap.add_argument("--gns3rt", required=True)
    ap.add_argument("--docs", default=None)
    ap.add_argument("--images", action="append", default=[],
                    help="extra CAS dir(s) <dir>/<sha256> searched when Pack/images lacks a blob (hardlinked)")
    ap.add_argument("--no-docker-sock-patch", action="store_true",
                    help="ship stock gns3server (no VASYA docker socket/attach/uid patch)")
    ap.add_argument("--docker-archives", default=None,
                    help="dir with docker-images.json + one archive per unique image; "
                         "validated and hardlinked into Payload/docker (private profile only)")
    a = ap.parse_args()
    if a.profile == "public" and (a.images or a.docker_archives):
        sys.exit("--images/--docker-archives are only allowed with --profile private "
                 "(a public bundle never contains images)")
    top = Path(a.out) / (f"VASYA-GNS-LAB-{VERSION}" + ("-PRIVATE" if a.profile == "private" else ""))
    if top.exists():
        shutil.rmtree(top)
    app = top / "App"
    app.mkdir(parents=True)
    ign = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(REPO / "src" / "vasya", app / "vasya", ignore=ign)
    shutil.copytree(a.pyside, app / "site-packages", ignore=ign)
    pruned_bad = prune_pyside(app / "site-packages")
    for v in ("py310", "py311", "py312", "py313"):
        shutil.copytree(Path(a.gns3rt) / v, app / "runtime" / "gns3server" / v, ignore=ign)
        shutil.rmtree(app / "runtime" / "gns3server" / v / "bin", ignore_errors=True)
    if not a.no_docker_sock_patch:
        # docker socket/attach/uid patch; inert unless VASYA exports VASYA_DOCKER_SOCKET etc.
        sys.path.insert(0, str(REPO / "src"))
        from vasya.runtime.docker_backend import patch_gns3server, patch_init_su, patch_record
        res = patch_gns3server(app / "runtime" / "gns3server")
        res4 = patch_init_su(app / "runtime" / "gns3server")   # init.sh su patch
        bad = [r for r in res + res4 if r[1] not in ("PATCHED", "ALREADY", "UPGRADED")]
        assert len(res) == 4 and len(res4) == 4 and not bad, (res, res4)
        (app / "runtime" / "gns3server" / "VASYA_PATCHES.json").write_text(json.dumps(
            patch_record(app / "runtime" / "gns3server", app), indent=1))
    linked = dedupe(app / "runtime")
    (app / "bin").mkdir()
    (app / "bin" / "gns3server").write_text(LAUNCHER); (app / "bin" / "gns3server").chmod(0o755)
    lx = REPO / "packaging" / "linux"
    for n in ("vasya", "vasya-gns-manager"):
        for d in (top, app):
            shutil.copy2(lx / n, d / n)
    shutil.copy2(lx / "install.sh", top / "install.sh")
    shutil.copy2(lx / "VASYA-GNS-LAB-Install.desktop", top / "VASYA-GNS-LAB-Install.desktop")
    (top / "VASYA-GNS-LAB-Install.desktop").chmod(0o755)
    man, n_img = stage_payload(Path(a.pack), top / "Payload", a.images, a.profile)
    pl = top / "Payload"
    if a.docker_archives:
        from vasya.runtime import docker_images as di
        da = Path(a.docker_archives)
        issues = di.validate_dir(da)
        for e in di.load_manifest(da):
            ok, why = di.verify_archive(e)
            if not ok:
                issues.append(f"{e['archive']}: {why}")
        if issues:
            sys.exit("docker archives invalid: " + "; ".join(issues))
        (pl / "docker").mkdir()
        for e in di.load_manifest(da):
            os.link(da / e["archive"], pl / "docker" / e["archive"])
        shutil.copyfile(da / di.MANIFEST, pl / "docker" / di.MANIFEST)
    if a.docs and Path(a.docs).exists():
        shutil.copytree(a.docs, top / "Docs")
    (top / "VERSION").write_text(VERSION + "\n")
    write_third_party(top, app)
    # internal manifest: every file except CAS images (their name IS their sha256)
    files = {}
    for p in sorted(top.rglob("*")):
        if p.is_file() and not p.is_symlink():
            rel = str(p.relative_to(top))
            if rel.startswith("Payload/images/sha256/"):
                continue
            files[rel] = sha(p)
    total = sum(p.stat().st_size for p in top.rglob("*") if p.is_file() and not p.is_symlink())
    json.dump({"product": "VASYA GNS LAB", "version": VERSION, "platform": "linux-x86_64",
               "profile": a.profile,
               "blocks": len(man["blocks"]), "cas_images": n_img, "files": files,
               "pyside_pruned_plugins_removed": pruned_bad, "dedup_hardlinks": linked,
               "apparent_bytes": total}, open(top / "BUNDLE_MANIFEST.json", "w"), indent=1)
    print(json.dumps({"top": str(top), "blocks": len(man["blocks"]), "images": n_img,
                      "dedup": linked, "pruned_plugins": pruned_bad, "apparent_bytes": total}))


if __name__ == "__main__":
    main()
