# SPDX-License-Identifier: GPL-3.0-or-later
import os, sys
from .linux import LinuxPlatform
from .windows import WindowsPlatform


def current(home=None, env=None):
    if os.name == "nt" or sys.platform.startswith("win"):
        return WindowsPlatform(home, env)
    return LinuxPlatform(home, env)


def by_name(name, home=None, env=None):
    return {"linux": LinuxPlatform, "windows": WindowsPlatform}[name](home, env)
