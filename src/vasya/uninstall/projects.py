# SPDX-License-Identifier: GPL-3.0-or-later
"""User projects that live INSIDE the VASYA folder (managed lab). On full
uninstall the user chooses: export (zip), keep (move out of the folder), delete."""
import json, shutil, time, zipfile
from pathlib import Path
from ..runtime import managed_server as ms

CHOICES = ("export", "keep", "delete")
SKIP = ("vasya-verify-", "vasya-demo-")


def user_projects(layout):
    pp = ms.paths(layout)["projects_path"]
    out = []
    if not pp.is_dir():
        return out
    for d in sorted(pp.iterdir()):
        if not d.is_dir():
            continue
        name = d.name
        for f in d.glob("*.gns3"):
            try:
                name = json.loads(f.read_text(encoding="utf-8")).get("name") or f.stem
            except Exception:
                name = f.stem
        if name.startswith(SKIP):
            continue
        size = sum(p.stat().st_size for p in d.rglob("*") if p.is_file() and not p.is_symlink())
        out.append({"name": name, "dir": str(d), "bytes": size})
    return out


def handle(layout, choice, log, dest_dir=None):
    """Returns the path where projects were saved (or None)."""
    projs = user_projects(layout)
    if not projs or choice == "delete":
        if projs:
            log.log("DELETE_USER_PROJECTS", ", ".join(p["name"] for p in projs), "OK")
        return None
    base = Path(dest_dir or Path.home())
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if choice == "export":
        dst = base / f"VASYA-GNS-LAB-projects-{stamp}.zip"
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
            for p in projs:
                d = Path(p["dir"])
                for f in d.rglob("*"):
                    if f.is_file():
                        z.write(f, Path(p["name"]) / f.relative_to(d))
        log.log("EXPORT_USER_PROJECTS", dst, "OK", after={"projects": len(projs)})
        return dst
    dst = base / f"VASYA-GNS-LAB-projects-{stamp}"
    dst.mkdir(parents=True)
    for p in projs:
        shutil.copytree(p["dir"], dst / Path(p["dir"]).name, symlinks=True)
    log.log("KEEP_USER_PROJECTS", dst, "OK", after={"projects": len(projs)})
    return dst
