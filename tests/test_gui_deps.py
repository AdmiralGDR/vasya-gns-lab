# SPDX-License-Identifier: GPL-3.0-or-later
"""gns3-gui deps (PyQt6, libxcb-cursor0 & co) — detection and receipted placement."""
import os, subprocess, sys
from pathlib import Path
import pytest
from vasya.installer.context import Context
from vasya.runtime import gui_deps as gd

PY = sys.executable


def _ctx(tmp_path):
    c = Context(tmp_path / "root", payload=tmp_path / "nopayload")
    c.layout.ensure()
    return c


@pytest.fixture
def xcb_src(tmp_path):
    """Stand-ins for the downloaded libraries (the real ones come from the pinned Ubuntu packages)."""
    d = tmp_path / "xcb-src"; d.mkdir()
    for n in gd.LIBS:
        (d / n).write_bytes(b"\x7fELF stand-in for " + n.encode())
    return d


def _launcher(tmp_path, python):
    p = tmp_path / "gns3"
    p.write_text(f"#!{python}\nprint('gns3')\n"); p.chmod(0o755)
    return str(p)


def test_check_reports_missing_libs_and_pyqt6(tmp_path):
    c = _ctx(tmp_path)
    r = gd.check(c, _launcher(tmp_path, PY), sys_dirs=(str(tmp_path / "nolibs"),))
    assert r["gns3_python"] == PY
    assert set(r["missing_libs"]) == set(gd.LIBS)
    ids = [a["id"] for a in r["actions"]]
    assert "bundle_xcb_libs" in ids
    assert "libxcb-cursor0" in r["actions"][0]["alt_admin_cmd"]
    if r["pyqt6"] is False:  # test venv has PySide6, not PyQt6
        a = [x for x in r["actions"] if x["id"] == "pip_pyqt6"][0]
        assert a["vasya_owned_env"] is False and a["auto"] is False  # never touch a foreign env
    assert r["ok"] is False


def test_bundle_places_receipts_and_is_idempotent(tmp_path, xcb_src):
    c = _ctx(tmp_path)
    nod = (str(tmp_path / "nolibs"),)
    r = gd.bundle_libxcb_cursor(c, src_dir=xcb_src, sys_dirs=nod)
    assert r["status"] == "OK" and len(r["placed"]) == 3
    rec = gd.receipt_path(c).read_text()
    for n in gd.LIBS:
        assert (gd.runtime_lib(c) / n).exists() and n in rec
    r2 = gd.bundle_libxcb_cursor(c, src_dir=xcb_src, sys_dirs=nod)
    assert r2["status"] == "OK" and len(r2["reused"]) == 3 and not r2["placed"]
    chk = gd.check(c, _launcher(tmp_path, PY), sys_dirs=nod)
    assert chk["missing_libs"] == []
    env = gd.launch_env(c, base={})
    assert env["LD_LIBRARY_PATH"] == str(gd.runtime_lib(c))


def test_bundle_skips_libs_present_on_system(tmp_path, xcb_src):
    c = _ctx(tmp_path)
    sysd = tmp_path / "sys"; sysd.mkdir()
    (sysd / "libxcb-icccm.so.4").write_bytes(b"x")
    (sysd / "libxcb-keysyms.so.1").write_bytes(b"x")
    r = gd.bundle_libxcb_cursor(c, src_dir=xcb_src, sys_dirs=(str(sysd),))
    assert [p["lib"] for p in r["placed"]] == ["libxcb-cursor.so.0"]


def test_foreign_file_is_conflict_and_modified_file_kept(tmp_path, xcb_src):
    c = _ctx(tmp_path)
    d = gd.runtime_lib(c); d.mkdir(parents=True)
    (d / "libxcb-cursor.so.0").write_bytes(b"not ours")
    r = gd.bundle_libxcb_cursor(c, src_dir=xcb_src, names=["libxcb-cursor.so.0"])
    assert r["status"] == "PARTIAL" or r["problems"][0]["status"] == "CONFLICT"
    assert (d / "libxcb-cursor.so.0").read_bytes() == b"not ours"
    gd.bundle_libxcb_cursor(c, src_dir=xcb_src, names=["libxcb-icccm.so.4", "libxcb-keysyms.so.1"])
    (d / "libxcb-icccm.so.4").write_bytes(b"user changed")
    out = gd.remove_owned(c)
    assert (d / "libxcb-icccm.so.4").exists()  # hash mismatch -> kept
    assert not (d / "libxcb-keysyms.so.1").exists()
    assert (d / "libxcb-cursor.so.0").exists()  # never receipted -> kept
    assert out["kept"][0]["status"] == "KEPT_MODIFIED"


def test_offline_without_source_is_blocked(tmp_path):
    c = _ctx(tmp_path)
    r = gd.bundle_libxcb_cursor(c, names=["libxcb-cursor.so.0"])
    assert r["status"] == "BLOCKED" and not (gd.runtime_lib(c) / "libxcb-cursor.so.0").exists()


def test_every_lib_is_pinned_in_the_lock():
    from vasya.fetch import lock
    libs = lock.load()["libraries"]
    assert set(libs) == set(gd.LIBS)
    for n, e in libs.items():
        pk = e["package"]
        assert pk["install_name"] == n and len(pk["sha256"]) == 64 and len(pk["member_sha256"]) == 64
        assert all(u.startswith("https://") for u in pk["urls"])


@pytest.mark.skipif(not os.path.exists("/usr/bin/Xvfb"), reason="needs Xvfb")
@pytest.mark.skipif(os.environ.get("VASYA_TEST_NETWORK") != "1", reason="downloads the pinned packages")
def test_qt_xcb_starts_with_downloaded_libs(tmp_path, monkeypatch):
    """PySide6 xcb plugin loads once the downloaded libs are on LD_LIBRARY_PATH."""
    monkeypatch.setenv("VASYA_OFFLINE", "0")
    c = _ctx(tmp_path)
    r = gd.bundle_libxcb_cursor(c, sys_dirs=(str(tmp_path / "nolibs"),))
    assert r["status"] == "OK" and len(r["placed"]) == 3, r
    disp = ":96"
    x = subprocess.Popen(["Xvfb", disp, "-screen", "0", "800x600x24"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        import time; time.sleep(1.5)
        env = dict(os.environ, DISPLAY=disp, QT_QPA_PLATFORM="xcb",
                   LD_LIBRARY_PATH=str(gd.runtime_lib(c)))
        code = "from PySide6.QtWidgets import QApplication;import sys;a=QApplication(sys.argv);print(a.platformName())"
        r = subprocess.run([PY, "-c", code], env=env, capture_output=True, text=True, timeout=60)
        assert r.stdout.strip() == "xcb", r.stderr[-500:]
    finally:
        x.terminate()
