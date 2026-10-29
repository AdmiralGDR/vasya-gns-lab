# SPDX-License-Identifier: GPL-3.0-or-later
"""Tool registry: what each external tool is for, where it comes from, who owns it."""
import os, subprocess
try:
    import grp
except ImportError:  # Windows
    grp = None
from pathlib import Path
from ..core.util import load_json

DATA = Path(__file__).resolve().parent.parent / "data" / "tools.json"


def metadata():
    return load_json(DATA)["tools"]


def _version(path, tid):
    args = {"gns3server": ["--version"], "dynamips": ["--help"], "ubridge": ["-v"],
            "docker": ["--version"], "qemu": ["--version"], "qemu-img": ["--version"],
            "tshark": ["--version"], "wireshark": ["--version"], "busybox": [""]}.get(tid)
    if args is None:
        return None
    try:
        r = subprocess.run([path] + [a for a in args if a], capture_output=True, text=True, timeout=8)
        out = (r.stdout or r.stderr).strip().splitlines()
        return out[0][:120] if out else None
    except Exception:
        return None


def _in_group(name):
    if os.name == "nt" or grp is None:
        return True
    try:
        g = grp.getgrnam(name)
    except KeyError:
        return False
    return g.gr_gid in os.getgroups() or os.getegid() == g.gr_gid


def detect_all(platform, with_versions=False):
    out = {}
    for t in metadata():
        tid = t["id"]
        if tid == "kvm":
            p = Path("/dev/kvm")
            out[tid] = {"present": p.exists(), "path": str(p) if p.exists() else None,
                        "accessible": p.exists() and os.access(p, os.R_OK | os.W_OK)}
            continue
        if tid == "pyside6":
            try:
                import importlib.util
                spec = importlib.util.find_spec("PySide6")
                out[tid] = {"present": bool(spec), "path": spec.origin if spec else None}
            except Exception:
                out[tid] = {"present": False, "path": None}
            continue
        if tid == "packettracer":
            from .packet_tracer import detect
            d = detect(platform)
            out[tid] = {"present": d["status"] == "INSTALLED", "path": d.get("path"),
                        "status": d["status"]}
            continue
        path = platform.find_tool(tid if tid != "qemu" else "qemu-system-x86_64", t["names"])
        if tid == "gns3server" and os.environ.get("VASYA_GNS3SERVER_BIN"):
            path = os.environ["VASYA_GNS3SERVER_BIN"]
        if tid == "ubridge" and not path and os.environ.get("VASYA_UBRIDGE_BIN"):
            path = os.environ["VASYA_UBRIDGE_BIN"]
        if tid == "dynamips" and not path and os.environ.get("VASYA_DYNAMIPS_BIN"):
            path = os.environ["VASYA_DYNAMIPS_BIN"]
        rec = {"present": bool(path), "path": path}
        if tid == "docker" and path:
            rec["accessible"] = _in_group("docker") or os.geteuid() == 0 if os.name != "nt" else True
        if with_versions and path:
            rec["version"] = _version(path, tid)
        out[tid] = rec
    return out


def registry(platform, ownership=None):
    """Full registry rows for the Tools screen / reports."""
    det = detect_all(platform, with_versions=True)
    own = ownership or {}
    rows = []
    for t in metadata():
        d = det.get(t["id"], {})
        o = own.get(t["id"])
        rows.append(dict(t, present=d.get("present", False), path=d.get("path"),
                         version=d.get("version"), status=d.get("status"),
                         accessible=d.get("accessible"),
                         preinstalled=bool(d.get("present")) and not (o and o.get("installed_by_vasya")),
                         owner=("VASYA" if o and o.get("installed_by_vasya") else
                                ("system/user" if d.get("present") else "—"))))
    return rows


_KVM_CACHE = {}


def kvm_functional(qemu_path, timeout=8):
    """/dev/kvm being writable is not enough: with broken nested virtualisation the vCPU
    creation hangs and QEMU never opens its VNC/telnet console. Start a tiny VM with
    -accel kvm and ask it to quit; True only if it exits cleanly in time. Cached per path."""
    if not qemu_path:
        return False
    if qemu_path in _KVM_CACHE:
        return _KVM_CACHE[qemu_path]
    import subprocess
    try:
        r = subprocess.run([qemu_path, "-accel", "kvm", "-m", "64", "-nodefaults", "-display", "none",
                            "-monitor", "stdio", "-S"], input=b"quit\n", capture_output=True, timeout=timeout)
        ok = r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        ok = False
    _KVM_CACHE[qemu_path] = ok
    return ok
