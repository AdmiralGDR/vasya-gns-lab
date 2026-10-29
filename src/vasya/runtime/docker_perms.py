# SPDX-License-Identifier: GPL-3.0-or-later
"""Repair ownership of files that Docker containers (running as root) wrote into
VASYA-owned GNS3 project folders, so they can be deleted without sudo.

GNS3 normally chowns container volumes back on a clean *stop*; when a container
start fails half-way (e.g. uBridge without CAP_NET_ADMIN) the files stay owned by
root and both the GNS3 project delete and our uninstall would leave residue.
We fix this with the Docker daemon itself, using an image VASYA owns
(label org.vasya.owner) — never a foreign image and never global prune.
"""
import os, shutil, subprocess
from pathlib import Path

OWNER_FILTER = "label=org.vasya.owner=vasya-gns-lab"


def foreign_owned(path, limit=1):
    """Return up to `limit` paths under `path` not owned by the current user."""
    if os.name == "nt" or not Path(path).exists():
        return []
    me, out = os.getuid(), []
    for dp, dns, fns in os.walk(path):
        for n in dns + fns:
            p = os.path.join(dp, n)
            try:
                if os.lstat(p).st_uid != me:
                    out.append(p)
                    if len(out) >= limit:
                        return out
            except OSError:
                pass
    return out


def _helper_image(cmd):
    r = subprocess.run(cmd + ["images", "--filter", OWNER_FILTER, "--format", "{{.Repository}}:{{.Tag}}"],
                       capture_output=True, text=True, timeout=30)
    refs = [x for x in r.stdout.split() if x and "<none>" not in x] if r.returncode == 0 else []
    return refs[0] if refs else None


def fix_tree(path):
    """chown -R uid:gid `path` through a VASYA-owned image. Returns dict with result."""
    from ..installer.apply import docker_cmd
    path = Path(path)
    if not foreign_owned(path):
        return {"result": "NOT_NEEDED"}
    cmd = docker_cmd()
    if not cmd:
        return {"result": "NO_DOCKER", "example": foreign_owned(path)[0]}
    img = _helper_image(cmd)
    if not img:
        return {"result": "NO_VASYA_IMAGE", "example": foreign_owned(path)[0]}
    uid, gid = os.getuid(), os.getgid()
    r = subprocess.run(cmd + ["run", "--rm", "--network", "none", "--label", "org.vasya.owner=vasya-gns-lab",
                              "-v", f"{path.resolve()}:/vasya-fix", "--entrypoint", "/bin/sh", img, "-c",
                              f"chown -R {uid}:{gid} /vasya-fix && chmod -R u+rwX /vasya-fix"],
                       capture_output=True, text=True, timeout=300)
    left = foreign_owned(path)
    return {"result": "FIXED" if not left else "FAILED", "image": img,
            "error": (r.stderr or "")[-300:] if r.returncode else None}


def remove_tree(path):
    """rmtree that first repairs container-owned files. Returns True if gone."""
    path = Path(path)
    if not path.exists():
        return True
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        fix_tree(path)
        shutil.rmtree(path, ignore_errors=True)
    return not path.exists()
