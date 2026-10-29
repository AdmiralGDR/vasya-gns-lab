# SPDX-License-Identifier: GPL-3.0-or-later
"""Platform adapter interface (paths, privileges, tool lookup)."""
import os, re, shutil
from pathlib import Path, PurePosixPath, PureWindowsPath


class Platform:
    name = "base"
    exe_suffix = ""

    def __init__(self, home=None, env=None):
        self.env = dict(os.environ if env is None else env)
        self.home = Path(home) if home else Path.home()

    # --- paths ---------------------------------------------------------
    def default_root(self):
        raise NotImplementedError

    def gns3_config_candidates(self):
        raise NotImplementedError

    def pure_path(self, p):
        return PurePosixPath(p)

    def validate_root(self, root):
        """Return list of problems with a proposed install root (empty = OK)."""
        problems = []
        p = str(root)
        if not p:
            return ["empty path"]
        if len(p) > 200:
            problems.append("path longer than 200 characters")
        return problems

    # --- privileges ----------------------------------------------------
    def is_admin(self):
        raise NotImplementedError

    def needs_admin_for(self, path):
        """True if writing `path` needs elevation."""
        p = Path(path)
        while not p.exists() and p != p.parent:
            p = p.parent
        return not os.access(p, os.W_OK)

    # --- tools ---------------------------------------------------------
    def which(self, name):
        return shutil.which(name + self.exe_suffix) or shutil.which(name)

    def tool_paths(self, tool):
        """Extra well-known locations for a tool (beyond PATH)."""
        return []

    def find_tool(self, tool, names):
        for n in names:
            w = self.which(n)
            if w:
                return w
        for c in self.tool_paths(tool):
            if Path(c).exists():
                return str(c)
        return None

    def packet_tracer_candidates(self):
        return []

    def applications_dir(self):
        return None

    def detach_kwargs(self):
        return {}


_BAD_WIN = re.compile(r'[<>:"|?*]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}


def windows_path_problems(p):
    probs = []
    wp = PureWindowsPath(p)
    if not wp.drive and not str(p).startswith("\\\\"):
        probs.append("not an absolute Windows path (no drive)")
    for part in wp.parts[1:]:
        if _BAD_WIN.search(part):
            probs.append(f"invalid character in '{part}'")
        if part.split(".")[0].upper() in _RESERVED:
            probs.append(f"reserved device name '{part}'")
        if part.endswith((" ", ".")):
            probs.append(f"component ends with space/dot '{part}'")
    if len(str(p)) > 200:
        probs.append("path longer than 200 characters (MAX_PATH risk for nested images)")
    return probs
