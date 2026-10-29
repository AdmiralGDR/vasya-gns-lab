# SPDX-License-Identifier: GPL-3.0-or-later
"""System snapshot for before/after diffs of the GUI E2E (what VASYA could leave behind)."""
import os, subprocess
from pathlib import Path


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.split("\n")
    except Exception:
        return []


# Not created by VASYA: fontconfig's font cache, written by Qt/fontconfig on first text render
# in any GUI app. Anything else under ~/.cache (e.g. ~/.cache/vasya) is still reported.
IGNORED = (".cache/fontconfig",)


def _ignored(rel):
    return rel == ".cache" or any(rel == i or rel.startswith(i + "/") for i in IGNORED)


def snapshot(home, root):
    home = Path(home)
    files = sorted(r for r in (str(p.relative_to(home)) for p in home.rglob("*")
                               if len(p.relative_to(home).parts) <= 4) if not _ignored(r)) if home.exists() else []
    return {
        "home_files": files,
        "root_exists": Path(root).exists(),
        "docker_images": sorted(l for l in _run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}} {{.ID}}"]) if l),
        "docker_vasya_labelled": sorted(l for l in _run(["docker", "images", "-q", "--filter",
                                                          "label=org.vasya.owner=vasya-gns-lab"]) if l),
        "docker_containers": sorted(l for l in _run(["docker", "ps", "-a", "--format", "{{.Names}} {{.Image}}"]) if l),
        "processes": sorted({l.split(None, 1)[1].split()[0].rsplit("/", 1)[-1] for l in
                             _run(["pgrep", "-af", "gns3server|ubridge|dynamips|qemu-system"]) if l and " " in l
                             and "pgrep" not in l}),
        "listening": sorted(l.split()[3] for l in _run(["ss", "-ltnH"]) if l.strip()),
        "real_home_gns3_config": (Path(os.path.expanduser("~")) / ".config" / "GNS3").exists(),
    }


def diff(a, b):
    out = {}
    for k in a:
        if isinstance(a[k], list):
            add, rem = sorted(set(b[k]) - set(a[k])), sorted(set(a[k]) - set(b[k]))
            if add or rem:
                out[k] = {"added": add, "removed": rem}
        elif a[k] != b[k]:
            out[k] = {"before": a[k], "after": b[k]}
    return out
