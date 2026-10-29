# SPDX-License-Identifier: GPL-3.0-or-later
"""Desktop integration: plain freedesktop .desktop entry (COSMIC/Wayland, KDE, GNOME — no
desktop-specific deps), Windows Start Menu shortcut.

Files live inside the ONE-ROOT (<root>/Desktop); by default NOTHING is written outside
the root. Registration into ~/.local/share/applications (or the Start Menu .lnk)
is a separate, explicit, user-confirmed step recorded in the WAL and removed by
uninstall. We deliberately do not run update-desktop-database (it would leave a
mimeinfo.cache behind); COSMIC/KDE/GNOME pick new entries up via inotify.
"""
import os, shutil, subprocess
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "icons"
DESKTOP_NAME = "vasya-gns-lab.desktop"


def render_desktop(root, launcher, icon):
    return "\n".join([
        "[Desktop Entry]", "Type=Application", "Version=1.0",
        "Name=VASYA GNS LAB Manager", "Name[ru]=VASYA GNS LAB — Менеджер",
        "GenericName=Network Lab Manager", "GenericName[ru]=Менеджер сетевой лаборатории",
        "Comment=Install, verify, repair and remove the VASYA GNS3 lab",
        "Comment[ru]=Установка, проверка, восстановление и удаление лаборатории GNS3",
        f"Exec=\"{launcher}\"", f"Icon={icon}", "Terminal=false",
        "Categories=Network;Education;System;", "Keywords=GNS3;network;lab;cisco;qemu;docker;",
        "StartupNotify=true", "StartupWMClass=vasya-gns-lab", f"X-VASYA-Root={root}", ""])


def prepare_files(layout):
    d = layout.Desktop
    (d / "icons").mkdir(parents=True, exist_ok=True)
    for ext in ("svg", "png"):
        src = DATA / f"vasya-gns-lab.{ext}"
        if src.exists():
            shutil.copyfile(src, d / "icons" / f"vasya-gns-lab.{ext}")
    launcher = layout.App / ("vasya-gns-manager.cmd" if os.name == "nt" else "vasya-gns-manager")
    icon = d / "icons" / "vasya-gns-lab.svg"
    entry = d / DESKTOP_NAME
    entry.write_text(render_desktop(layout.root, launcher, icon), encoding="utf-8")
    return entry


def register_linux(layout, apps_dir):
    entry = prepare_files(layout)
    apps_dir = Path(apps_dir)
    apps_dir.mkdir(parents=True, exist_ok=True)
    dst = apps_dir / DESKTOP_NAME
    shutil.copyfile(entry, dst)
    os.chmod(dst, 0o755)
    return dst


def register_windows(layout, start_menu):
    prepare_files(layout)
    lnk = Path(start_menu) / "VASYA GNS LAB Manager.lnk"
    target = layout.App / "vasya-gns-manager.cmd"
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');$s.TargetPath='%s';"
          "$s.WorkingDirectory='%s';$s.Save()") % (lnk, target, layout.App)
    if os.name == "nt":
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    return lnk


def register(layout, platform):
    apps = platform.applications_dir()
    if platform.name == "windows":
        return register_windows(layout, apps)
    return register_linux(layout, apps)


def unregister(path):
    p = Path(path)
    existed = p.exists()
    p.unlink(missing_ok=True)
    return existed
