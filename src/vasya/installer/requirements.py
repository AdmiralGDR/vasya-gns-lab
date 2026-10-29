# SPDX-License-Identifier: GPL-3.0-or-later
"""What the plan screen must show besides files: programs, download size, admin
need, reboots and every change OUTSIDE the VASYA folder — each one separately.
VASYA never performs system changes silently; they are listed with the exact
command so the user (or an approved admin step) runs them."""
import os, shutil, subprocess
from pathlib import Path
from ..core.util import load_json, human_bytes

DATA = Path(__file__).resolve().parent.parent / "data"
APT = {"qemu": "qemu-system-x86", "qemu-arm": "qemu-system-arm", "qemu-img": "qemu-utils", "dynamips": "dynamips",
       "ubridge": "ubridge", "docker": "docker.io", "busybox": "busybox-static",
       "wireshark": "wireshark", "tshark": "tshark", "vpcs": "vpcs", "telnet": "telnet",
       "vncviewer": "tigervnc-viewer", "podman": "podman", "newuidmap": "uidmap"}
WIN = {"gns3server": "GNS3-2.2.61-all-in-one.exe (GNS3 + Dynamips + uBridge + VPCS)",
       "qemu": "GNS3 VM 2.2.61 (VMware/Hyper-V/VirtualBox) — QEMU runs inside the VM",
       "docker": "GNS3 VM 2.2.61 — Docker runs inside the VM",
       "wireshark": "Wireshark + Npcap (official installer)", "tshark": "Wireshark (includes tshark)"}
NEED = {"qemu": ["qemu", "qemu-img"], "dynamips": ["dynamips"], "docker": ["docker", "busybox"]}
ALWAYS = ["gns3server", "ubridge"]
OPTIONAL = ["wireshark", "tshark", "telnet", "vncviewer", "vpcs"]


def docker_sizes():
    return (load_json(DATA / "docker_sizes.json", {}) or {}).get("images", {})


def ubridge_has_caps(path):
    """True/False on Linux when getcap is available, None when unknown."""
    if os.name == "nt" or not path:
        return None
    if os.geteuid() == 0:
        return True
    gc = shutil.which("getcap") or ("/usr/sbin/getcap" if Path("/usr/sbin/getcap").exists() else None)
    if not gc:
        return None
    try:
        out = subprocess.run([gc, path], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return None
    return "cap_net_admin" in out and "cap_net_raw" in out


PODMAN_NEED = ["podman", "newuidmap", "busybox"]   # Linux default backend; never the shared docker


def assess(platform, tools, runtimes, docker_refs, mode, desktop=False, bundled_server=False,
           docker_backend=None):
    linux = platform.name == "linux"
    podman = linux and docker_backend == "podman-rootless"
    need = dict(NEED, docker=PODMAN_NEED) if podman else NEED
    needed = list(ALWAYS) + sorted({t for r in runtimes for t in need.get(r, [])})
    programs = []
    for tid in needed + OPTIONAL:
        d = tools.get(tid, {})
        if tid in ("podman", "newuidmap") and not d:
            w = shutil.which(tid)
            d = {"present": bool(w), "path": w}
        if tid == "gns3server" and bundled_server and not d.get("present"):
            d = {"present": True, "path": "bundled gns3-server 2.2.61 (inside the VASYA folder)"}
        programs.append({"id": tid, "present": bool(d.get("present")), "path": d.get("path"),
                         "required": tid in needed,
                         "package": (APT.get(tid) if linux else WIN.get(tid)) or tid})
    missing_req = [p for p in programs if p["required"] and not p["present"]]
    changes = []
    if linux:
        pk = sorted({p["package"] for p in missing_req if p["id"] not in ("gns3server",)})
        for p in pk:
            changes.append({"kind": "package", "what": p, "admin": True,
                            "command": f"sudo apt-get install --no-install-recommends {p}",
                            "undo": f"sudo apt-get remove {p} (only if VASYA installed it)"})
        if any(p["id"] == "gns3server" for p in missing_req):
            changes.append({"kind": "package", "what": "gns3-server==2.2.61 (not found, and this bundle has no build for this Python)",
                            "admin": True, "command": "sudo apt-get install gns3-server  (or use the VASYA bundle for Python 3.10-3.13)",
                            "undo": "sudo apt-get remove gns3-server"})
        ub = tools.get("ubridge", {})
        if ub.get("present") and ubridge_has_caps(ub.get("path")) is False:
            changes.append({"kind": "capability", "what": f"uBridge CAP_NET_ADMIN/CAP_NET_RAW ({ub['path']})",
                            "admin": True, "command": f"sudo setcap cap_net_admin,cap_net_raw=ep {ub['path']}",
                            "undo": f"sudo setcap -r {ub['path']}"})
        kvm = tools.get("kvm", {})
        if "qemu" in runtimes and kvm.get("present") and not kvm.get("accessible"):
            changes.append({"kind": "group", "what": "user → group kvm", "admin": True, "relogin": True,
                            "command": "sudo usermod -aG kvm $USER", "undo": "sudo gpasswd -d $USER kvm"})
        dk = tools.get("docker", {})
        if docker_refs and not podman and dk.get("present") and not dk.get("accessible"):
            changes.append({"kind": "group", "what": "user → group docker", "admin": True, "relogin": True,
                            "command": "sudo usermod -aG docker $USER", "undo": "sudo gpasswd -d $USER docker"})
    else:
        for p in missing_req:
            changes.append({"kind": "program", "what": p["package"], "admin": True,
                            "command": "run the official installer", "undo": "Settings → Apps"})
    if docker_refs and podman:
        changes.append({"kind": "docker_images", "what": f"{len(docker_refs)} Docker images in VASYA's own rootless "
                        "podman storage inside the VASYA folder (from offline archives, never a pull; your existing "
                        "Docker is not used or changed)",
                        "admin": False, "command": "podman load (automatic)", "undo": "VASYA uninstall"})
    elif docker_refs:
        changes.append({"kind": "docker_images", "what": f"{len(docker_refs)} Docker images in the shared Docker daemon "
                        "(labelled org.vasya.owner, removed on uninstall unless used by other containers)",
                        "admin": False, "command": "docker pull (automatic)", "undo": "VASYA uninstall"})
    if desktop:
        changes.append({"kind": "shortcut", "what": "applications-menu entry vasya-gns-lab.desktop",
                        "admin": False, "command": "automatic", "undo": "VASYA uninstall"})
    sizes = docker_sizes()
    dl = [{"ref": r, "bytes": (sizes.get(r) or {}).get("bytes")} for r in sorted(set(docker_refs))]
    dl_bytes = sum(d["bytes"] or 0 for d in dl)
    relogin = [c["what"] for c in changes if c.get("relogin")]
    return {"programs": programs, "missing_required": [p["id"] for p in missing_req],
            "system_changes": changes, "download": dl, "download_bytes": dl_bytes,
            "download_human": human_bytes(dl_bytes), "download_unknown": [d["ref"] for d in dl if not d["bytes"]],
            "admin_required": any(c["admin"] for c in changes), "relogin": relogin, "reboot": False}
