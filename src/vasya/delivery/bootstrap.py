# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate the single-file Linux setup script that finds/verifies/joins the parts.

The script is POSIX sh + an embedded stdlib-only Python program (parts.py +
setup_main.py) with the parts manifest baked in, so the user runs exactly one
file and never joins anything by hand.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
MARK = "#__VASYA_PY__"

SH_HEAD = """#!/bin/sh
# VASYA GNS LAB {version} — Linux setup (one file).
# Put this file in the same folder as the downloaded parts (or leave everything in ~/Downloads)
# and run:   sh {script}
# It finds every part, checks its SHA-256, unpacks the bundle into your home folder
# and opens the graphical installer. Nothing is installed before you press "Install".
# Options: --dest DIR  --no-install  --verify-only  --search DIR  --root DIR  --no-docker  --docker-only
# If the parts of {docker_pack} are found too, they are verified and unpacked into <VASYA folder>/Images/docker.
HERE="$(cd "$(dirname "$0")" && pwd)"
export VASYA_SETUP_DIR="$HERE"
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found / python3 не найден:  sudo apt install python3" >&2; exit 3
fi
exec python3 -c "$(sed '1,/^{mark}$/d' "$0")" "$@"
{mark}
"""


def make_setup_script(manifest, script_name, docker=None):
    """docker: optional Docker image pack description {pack, archive, top_dir, subdir, files: {name: {sha256,
    size}}} — every file Setup.sh may write is pinned here, so a pack is trusted only file by file."""
    py = (HERE / "parts.py").read_text() + "\n\nEMBEDDED_MANIFEST = " + json.dumps(manifest, indent=1) \
        + "\n\nEMBEDDED_DOCKER = " + repr(docker) \
        + "\n\n" + (HERE / "setup_main.py").read_text()
    compile(py, script_name, "exec")
    return SH_HEAD.format(version=manifest.get("version", "?"), script=script_name, mark=MARK,
                          docker_pack=(docker or {}).get("pack", "the Docker image pack")) + py


def docker_pack_spec(pins, sidecars, version):
    """pins: docker-images.json entries; sidecars: {name: bytes} (.sha256 files, index.json)."""
    import hashlib
    pack = f"VASYA-GNS-LAB-{version}-Docker-Images"
    files = {e["archive"]: {"sha256": e["archive_sha256"], "size": e["archive_bytes"]} for e in pins}
    for n, b in sorted(sidecars.items()):
        files[n] = {"sha256": hashlib.sha256(b).hexdigest(), "size": len(b)}
    return {"pack": pack, "archive": pack + ".tar", "top_dir": pack, "subdir": "Images/docker", "files": files}
