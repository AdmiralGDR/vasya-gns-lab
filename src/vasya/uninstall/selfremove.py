# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded self-removal helper.

When the uninstaller runs from <root>/App it cannot delete its own directory
while running (Windows locks it; on Linux the venv would vanish mid-run). We copy
this stdlib-only helper to a fresh temp dir, start it detached, and exit. The
helper waits (max `timeout` s) for the parent pid to exit, removes the root,
appends the result to the report, and deletes its own temp dir.
"""
import os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

HELPER = r'''
import os, shutil, sys, time
root, ppid, report, timeout = sys.argv[1], int(sys.argv[2]), sys.argv[3], float(sys.argv[4])
def alive(p):
    if os.name == "nt":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, p)
        if not h: return False
        code = ctypes.c_ulong(); ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h); return code.value == 259
    try:
        os.kill(p, 0); return True
    except OSError:
        return False
t0 = time.time()
while alive(ppid) and time.time() - t0 < timeout:
    time.sleep(0.2)
ok = False
for i in range(10):
    shutil.rmtree(root, ignore_errors=True)
    if not os.path.exists(root):
        ok = True; break
    time.sleep(0.5)
with open(report, "a", encoding="utf-8") as f:
    f.write("\nSELF_REMOVAL: %s (root %s, waited %.1fs)\n" % ("PASS" if ok else "FAIL", root, time.time() - t0))
    if ok:
        f.write("VASYA_FILES_LEFT: 0 (after self-removal)\n")
here = os.path.dirname(os.path.abspath(__file__))
try:
    os.remove(os.path.abspath(__file__)); os.rmdir(here)
except OSError:
    pass
'''


def running_inside(root):
    try:
        here = Path(__file__).resolve()
        exe = Path(sys.executable).resolve()
        r = Path(root).resolve()
        return r in here.parents or r in exe.parents
    except Exception:
        return False


def spawn(root, report, timeout=60, python=None):
    d = Path(tempfile.mkdtemp(prefix="vasya-uninstall-"))
    h = d / "vasya_selfremove.py"
    h.write_text(HELPER, encoding="utf-8")
    py = python or _outside_python(root)
    kw = {"start_new_session": True} if os.name != "nt" else {"creationflags": 0x00000008 | 0x00000200}
    p = subprocess.Popen([py, str(h), str(root), str(os.getpid()), str(report), str(timeout)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True, **kw)
    return {"helper": str(h), "pid": p.pid, "python": py}


def _outside_python(root):
    """A Python interpreter that does not live inside the root being deleted."""
    r = Path(root).resolve()
    exe = Path(sys.executable).resolve()
    if r not in exe.parents:
        return str(exe)
    for name in ("python3", "python"):
        w = shutil.which(name)
        if w and r not in Path(w).resolve().parents:
            return w
    base = Path(sys.base_prefix)
    if r not in base.resolve().parents:
        return str(base / ("python.exe" if os.name == "nt" else "bin/python3"))
    # interpreter is bundled inside the root (Windows embeddable): copy it out (~15 MB)
    tmp = Path(tempfile.mkdtemp(prefix="vasya-py-"))
    shutil.copytree(base, tmp / "py", ignore=shutil.ignore_patterns("site-packages", "Lib", "*.pyc"))
    return str(tmp / "py" / ("python.exe" if os.name == "nt" else "bin/python3"))
