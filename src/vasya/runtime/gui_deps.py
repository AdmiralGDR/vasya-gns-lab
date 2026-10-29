# SPDX-License-Identifier: GPL-3.0-or-later
"""GNS3 GUI (gns3-gui) dependencies — PyQt6 and libxcb-cursor0 (Qt >= 6.5 xcb plugin) — and the
small helper programs VPCS, Dynamips and uBridge.

No system changes. If an xcb library is not found system-wide, VASYA downloads the pinned Ubuntu
package (third_party.lock), verifies it and places the library under <root>/Runtime/lib,
recorded in State/receipts/runtime-lib.json (sha/size/inode) and exported via LD_LIBRARY_PATH
only for processes VASYA launches. Helper programs go to <root>/Runtime/bin the same way.
Before anything is installed (the GUI started from the unpacked bundle) the launcher calls
``python -m vasya.runtime.gui_deps DIR`` to get the same verified libraries into a per-user
cache and link them into DIR. PyQt6 is only ever pip-installed into a VASYA-owned venv;
a system/user gns3 without PyQt6 is reported with the admin/user command, never changed.
"""
import glob, hashlib, os, shutil, subprocess
from pathlib import Path
from ..core.util import load_json, write_json, utc_now

LIB = "libxcb-cursor.so.0"
# Qt >= 6.5 xcb platform plugin needs these; the last two are usually present on a desktop.
LIBS = {"libxcb-cursor.so.0": "libxcb-cursor0", "libxcb-icccm.so.4": "libxcb-icccm4",
        "libxcb-keysyms.so.1": "libxcb-keysyms1"}
_which = shutil.which  # monkeypatched in tests (a system vpcs would hide the downloaded one)
SYS_DIRS = ("/usr/lib/x86_64-linux-gnu", "/lib/x86_64-linux-gnu", "/usr/lib64", "/usr/lib")


def runtime_lib(ctx):
    return ctx.layout.root / "Runtime" / "lib"


def receipt_path(ctx):
    return ctx.layout.State / "receipts" / "runtime-lib.json"


def _sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def system_lib(name=LIB, dirs=SYS_DIRS, use_ldconfig=True):
    for d in dirs:
        if glob.glob(os.path.join(d, name + "*")):
            return os.path.join(d, name)
    if not use_ldconfig:
        return None
    try:
        out = subprocess.check_output(["ldconfig", "-p"], text=True, timeout=30)
        for line in out.splitlines():
            if name in line and "=>" in line:
                return line.split("=>")[1].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def gns3_python(gns3_cmd):
    """Interpreter from the gns3 launcher's shebang (pip/venv script)."""
    p = shutil.which(gns3_cmd) if gns3_cmd and os.path.sep not in gns3_cmd else gns3_cmd
    if not p or not os.path.exists(p):
        return None
    try:
        with open(p, "rb") as f:
            first = f.readline().decode(errors="replace").strip()
    except OSError:
        return None
    if first.startswith("#!"):
        parts = first[2:].split()
        if parts and os.path.basename(parts[0]) == "env" and len(parts) > 1:
            return shutil.which(parts[1])
        return parts[0] if parts else None
    return None


def has_module(python, mod="PyQt6.QtWidgets", run=subprocess.run):
    if not python:
        return None
    try:
        r = run([python, "-c", f"import {mod}"], capture_output=True, text=True, timeout=60)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return None


def check(ctx, gns3_cmd="gns3", sys_dirs=SYS_DIRS, run=subprocess.run):
    py = gns3_python(gns3_cmd)
    ldc = sys_dirs is SYS_DIRS
    libs = {n: {"system": system_lib(n, sys_dirs, ldc),
                "vasya": str(runtime_lib(ctx) / n) if (runtime_lib(ctx) / n).exists() else None,
                "package": pk} for n, pk in LIBS.items()}
    missing = [n for n, v in libs.items() if not v["system"] and not v["vasya"]]
    sysl = libs[LIB]["system"]
    own = runtime_lib(ctx) / LIB
    res = {"gns3_gui": bool(py), "gns3_python": py,
           "pyqt6": has_module(py, run=run) if py else None,
           "libxcb_cursor_system": sysl,
           "libxcb_cursor_vasya": str(own) if own.exists() else None,
           "libs": libs, "missing_libs": missing, "actions": []}
    if missing:
        res["actions"].append({"id": "bundle_xcb_libs", "admin": False, "libs": missing,
                               "alt_admin_cmd": "sudo apt-get install --no-install-recommends "
                               + " ".join(LIBS[n] for n in missing)})
    if py and res["pyqt6"] is False:
        vasya_owned = str(ctx.layout.root) in os.path.realpath(py)
        res["actions"].append({"id": "pip_pyqt6", "admin": False, "vasya_owned_env": vasya_owned,
                               "cmd": f"{py} -m pip install PyQt6",
                               "auto": vasya_owned})
    res["ok"] = bool(py) and res["pyqt6"] is True and not missing
    return res


def _source(ctx, name, src_dir=None):
    """Verified local file for `name`: from `src_dir` when given, else from the pinned download."""
    if src_dir is not None:
        return Path(src_dir) / name, None
    from ..fetch import tools as ft
    r = ft.staged(ctx.layout, name)
    return (Path(r["path"]), None) if r["status"] == "OK" else (None, r.get("reason") or r["status"])


def bundle_libxcb_cursor(ctx, src_dir=None, names=None, sys_dirs=SYS_DIRS):
    """Place xcb libs missing system-wide under <root>/Runtime/lib; receipt each.
    Idempotent, no admin. names=None -> every LIBS entry not found on the system."""
    if names is None:
        names = [n for n in LIBS if not system_lib(n, sys_dirs, sys_dirs is SYS_DIRS)]
    rec = load_json(receipt_path(ctx), {"files": {}})
    out = {"status": "OK", "placed": [], "reused": [], "problems": []}
    for n in names:
        src, why = _source(ctx, n, src_dir)
        r = _place_one(ctx, src, rec) if src else {"status": "BLOCKED", "reason": f"{n}: {why}"}
        (out["placed"] if r["status"] == "OK" and not r.get("reused") else
         out["reused"] if r["status"] == "OK" else out["problems"]).append(dict(r, lib=n))
    receipt_path(ctx).parent.mkdir(parents=True, exist_ok=True)
    write_json(receipt_path(ctx), rec)
    if out["problems"]:
        out["status"] = "BLOCKED" if all(p["status"] == "BLOCKED" for p in out["problems"]) else "PARTIAL"
    return out


def _place_one(ctx, src, rec, dst_dir=None, mode=None):
    if not src.exists():
        return {"status": "BLOCKED", "reason": f"{src.name} missing in {src.parent}"}
    dst = Path(dst_dir or runtime_lib(ctx)) / src.name
    sha = _sha(src)
    if dst.exists():
        if str(dst) not in rec["files"]:
            return {"status": "CONFLICT", "reason": f"{dst} exists and is not VASYA's"}
        if _sha(dst) == sha:
            return {"status": "OK", "path": str(dst), "reused": True}
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".partial")
    shutil.copy2(src, tmp)
    if mode is not None:
        os.chmod(tmp, mode)
    if _sha(tmp) != sha:
        tmp.unlink()
        return {"status": "FAIL", "reason": "post-copy sha mismatch"}
    os.replace(tmp, dst)
    st = dst.stat()
    rec["files"][str(dst)] = {"sha256": sha, "size": st.st_size, "ino": st.st_ino,
                              "dev": st.st_dev, "owner": "vasya", "at": utc_now()}
    return {"status": "OK", "path": str(dst), "reused": False}


def remove_owned(ctx):
    """Delete only receipted files whose sha/size still match."""
    rec = load_json(receipt_path(ctx), {"files": {}})
    out = {"removed": [], "kept": []}
    for p, r in list(rec["files"].items()):
        q = Path(p)
        if not q.exists():
            rec["files"].pop(p)
            continue
        if q.stat().st_size != r["size"] or _sha(q) != r["sha256"]:
            out["kept"].append({"path": p, "status": "KEPT_MODIFIED"})
            continue
        q.unlink()
        rec["files"].pop(p)
        out["removed"].append(p)
    if receipt_path(ctx).exists():
        write_json(receipt_path(ctx), rec)
    return out


def launch_env(ctx, base=None):
    env = dict(base if base is not None else os.environ)
    d = runtime_lib(ctx)
    if any((d / n).exists() for n in LIBS):
        env["LD_LIBRARY_PATH"] = os.pathsep.join(x for x in (str(d), env.get("LD_LIBRARY_PATH")) if x)
    return env


HELPERS = ("vpcs", "dynamips", "ubridge")


def runtime_bin(ctx):
    return ctx.layout.root / "Runtime" / "bin"


def ensure_tool(ctx, name, src_dir=None, which=None):
    """A helper program for the managed server: a system copy is used as-is (never touched);
    otherwise the pinned GNS3 package build is downloaded, verified and placed at
    <root>/Runtime/bin/<name> with a receipt (same ownership rules as the xcb libs)."""
    sysv = (which or _which)(name)
    if sysv:
        return {"status": "OK", "path": sysv, "source": "system"}
    src, why = _source(ctx, name, src_dir)
    if not src:
        return {"status": "BLOCKED", "reason": why, "source": "vasya-fetched"}
    rec = load_json(receipt_path(ctx), {"files": {}})
    r = _place_one(ctx, src, rec, runtime_bin(ctx), 0o755)
    receipt_path(ctx).parent.mkdir(parents=True, exist_ok=True)
    write_json(receipt_path(ctx), rec)
    return dict(r, source="vasya-fetched")


def ensure_vpcs(ctx, src_dir=None, which=None):
    return ensure_tool(ctx, "vpcs", src_dir, which)


def export_tools(ctx):
    """Point tool discovery at helpers placed under <root>/Runtime/bin (system copies still win)."""
    for name, var in (("dynamips", "VASYA_DYNAMIPS_BIN"), ("ubridge", "VASYA_UBRIDGE_BIN")):
        p = runtime_bin(ctx) / name
        if p.is_file() and os.access(p, os.X_OK):
            os.environ.setdefault(var, str(p))


def session_cache():
    """Per-user download cache used before VASYA is installed (no <root> yet)."""
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "vasya-gns-lab"


def stage_session_libs(dest, names=None, cache=None):
    """Link verified copies of the missing xcb libs into `dest` (for LD_LIBRARY_PATH of one
    session). Returns {name: path or reason}. Nothing outside `dest` and the cache is touched."""
    from types import SimpleNamespace
    from ..fetch import tools as ft
    lay = SimpleNamespace(root=Path(cache or session_cache()))
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    out = {}
    for n in names or [n for n in LIBS if not system_lib(n)]:
        r = ft.staged(lay, n)
        if r["status"] != "OK":
            out[n] = r.get("reason") or r["status"]
            continue
        link = dest / n
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(r["path"])
        out[n] = r["path"]
    return out


if __name__ == "__main__":          # used by packaging/linux/vasya-gns-manager
    import sys
    res = stage_session_libs(sys.argv[1], sys.argv[2:] or None)
    for k, v in res.items():
        if not str(v).startswith("/"):
            print(f"VASYA: {k} not available ({v})", file=sys.stderr)
