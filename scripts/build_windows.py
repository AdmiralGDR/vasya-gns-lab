#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build VASYA-GNS-LAB-<ver>-Setup.exe (NSIS) on Linux.

Contents: embeddable CPython 3.12.10 (python312._pth extended with .. and ..\\site-packages),
PySide6/shiboken6 pruned to the PE-import closure of QtCore/QtGui/QtWidgets + the Windows
platform/style/image plugins, zstandard (win_amd64 cp312 wheel), the vasya package, docs.
Images are NOT inside: the Manager imports them from the Linux release parts.
STATUS of the result: UNVERIFIED until it runs on real Windows.
"""
import argparse, hashlib, json, re, shutil, subprocess, sys, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "src"))
from vasya import VERSION  # noqa: E402

KEEP_PLUGINS = ["platforms/qwindows.dll", "styles/*.dll", "imageformats/qico.dll",
                "imageformats/qsvg.dll", "imageformats/qjpeg.dll", "iconengines/qsvgicon.dll"]
ROOT_PY = ["__init__.py", "_config.py", "_git_pyside_version.py", "__feature__.pyi", "py.typed"]
SEEDS = ["QtCore.pyd", "QtGui.pyd", "QtWidgets.pyd", "pyside6.abi3.dll"]


def pe_imports(p):
    out = subprocess.run(["objdump", "-p", str(p)], capture_output=True, text=True).stdout
    return [m.group(1) for m in re.finditer(r"DLL Name: (\S+)", out)]


def closure(seeds, search):
    """All DLLs (from `search` dirs) reachable from seeds via PE imports."""
    index = {}
    for d in search:
        for f in d.glob("*.dll"):
            index.setdefault(f.name.lower(), f)
    seen, todo = set(), list(seeds)
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        seen.add(f)
        for name in pe_imports(f):
            hit = index.get(name.lower())
            if hit and hit not in seen:
                todo.append(hit)
    return seen


def stage_pyside(src, dst):
    ps, sh = src / "PySide6", src / "shiboken6"
    out = dst / "PySide6"; out.mkdir(parents=True)
    plugins = [p for pat in KEEP_PLUGINS for p in (ps / "plugins").glob(pat)]
    seeds = [ps / s for s in SEEDS] + plugins
    need = closure(seeds, [ps, sh])
    need |= set(ps.glob("*140*.dll"))  # MSVC runtime shipped with PySide6 (loaded by Qt6Core)
    for f in sorted(need):
        rel = f.relative_to(src)
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst / rel)
    for n in ROOT_PY:
        if (ps / n).exists():
            shutil.copy2(ps / n, out / n)
    for d in ("support",):
        if (ps / d).exists():
            shutil.copytree(ps / d, out / d, ignore=shutil.ignore_patterns("__pycache__"))
    for tr in (ps / "translations").glob("qtbase_*.qm"):
        if tr.name.startswith(("qtbase_ru", "qtbase_en")):
            (out / "translations").mkdir(exist_ok=True); shutil.copy2(tr, out / "translations" / tr.name)
    (out / "qt.conf").write_text("[Paths]\nPrefix = .\nPlugins = plugins\nTranslations = translations\n")
    shutil.copytree(sh, dst / "shiboken6", ignore=shutil.ignore_patterns("__pycache__", "*.lib"),
                    dirs_exist_ok=True)
    for di in src.glob("*.dist-info"):
        shutil.copytree(di, dst / di.name, dirs_exist_ok=True)
    return sorted(str(f.relative_to(src)) for f in need)


def make_ico(png, ico):
    try:
        from PIL import Image
        Image.open(png).save(ico, sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
        return True
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--embed", default="build/win/python-3.12.10-embed-amd64.zip")
    ap.add_argument("--pyside", default="build/win/pyside")
    ap.add_argument("--wheels", default="build/win/wheels")
    ap.add_argument("--docs", default=str(HERE / "docs"))
    ap.add_argument("--work", default="build/win/stage")
    ap.add_argument("--out", required=True, help="output .exe path")
    a = ap.parse_args()
    work = Path(a.work)
    shutil.rmtree(work, ignore_errors=True)
    app = work / "App"
    (app / "python").mkdir(parents=True)
    with zipfile.ZipFile(a.embed) as z:
        z.extractall(app / "python")
    pth = next((app / "python").glob("python3*._pth"))
    pth.write_text("python312.zip\n.\n..\n..\\site-packages\nimport site\n")
    sp = app / "site-packages"; sp.mkdir()
    kept = stage_pyside(Path(a.pyside), sp)
    for whl in Path(a.wheels).glob("*win_amd64.whl"):
        with zipfile.ZipFile(whl) as z:
            z.extractall(sp)
    shutil.copytree(HERE / "src" / "vasya", app / "vasya",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    icons = app / "vasya" / "data" / "icons"
    make_ico(icons / "vasya-gns-lab.png", icons / "vasya-gns-lab.ico")
    for f in ("launch_manager.pyw", "launch_cli.py"):
        shutil.copy2(HERE / "packaging/windows" / f, app / f)
    for f in ("vasya.cmd", "vasya-gns-manager.cmd"):
        shutil.copy2(HERE / "packaging/windows" / f, work / f)
    docs = work / "Docs"; docs.mkdir()
    for f in Path(a.docs).glob("*"):
        if f.is_file():
            shutil.copy2(f, docs / f.name)
    size = sum(f.stat().st_size for f in work.rglob("*") if f.is_file())
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["makensis", "-V2", f"-DVERSION={VERSION}", f"-DSTAGE={work}", f"-DOUTFILE={out}",
                        str(HERE / "packaging/windows/setup.nsi")], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-3000:], r.stderr[-3000:]); return 1
    h = hashlib.sha256(out.read_bytes()).hexdigest()
    info = {"setup_exe": str(out), "bytes": out.stat().st_size, "sha256": h, "staged_bytes": size,
            "pyside_files_kept": len(kept), "python": "3.12.10 embeddable amd64",
            "status": "UNVERIFIED (built on Linux with makensis; not run on Windows)"}
    (work.parent / "setup-build.json").write_text(json.dumps(info, indent=1))
    print(json.dumps(info, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
