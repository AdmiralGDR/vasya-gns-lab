# SPDX-License-Identifier: GPL-3.0-or-later
import os
from pathlib import Path, PureWindowsPath
from .base import Platform, windows_path_problems


class WindowsPlatform(Platform):
    name = "windows"
    exe_suffix = ".exe"

    def _env_path(self, key, fallback):
        v = self.env.get(key)
        return PureWindowsPath(v) if v else PureWindowsPath(fallback)

    def default_root(self):
        if self.env.get("VASYA_ROOT"):
            return PureWindowsPath(self.env["VASYA_ROOT"])
        # per-user, no admin needed (ONE-ROOT); avoids Program Files UAC virtualisation
        return self._env_path("LOCALAPPDATA", r"C:\Users\user\AppData\Local") / "VASYA-GNS-LAB"

    def pure_path(self, p):
        return PureWindowsPath(p)

    def gns3_config_candidates(self):
        appdata = self._env_path("APPDATA", r"C:\Users\user\AppData\Roaming")
        prog = self._env_path("ProgramData", r"C:\ProgramData")
        return [appdata / "GNS3" / "2.2" / "gns3_server.ini", appdata / "GNS3" / "gns3_server.ini",
                prog / "GNS3" / "gns3_server.ini"]

    def validate_root(self, root):
        return windows_path_problems(str(root))

    def is_admin(self):
        if os.name != "nt":
            return False
        import ctypes
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def needs_admin_for(self, path):
        s = str(path).lower()
        for prot in ("c:\\program files", "c:\\windows", "c:\\programdata\\microsoft"):
            if s.startswith(prot):
                return True
        if os.name != "nt":
            return False
        return super().needs_admin_for(path)

    def tool_paths(self, tool):
        pf = self._env_path("ProgramFiles", r"C:\Program Files")
        return {
            "gns3": [pf / "GNS3" / "gns3.exe"],
            "gns3server": [pf / "GNS3" / "gns3server.exe"],
            "dynamips": [pf / "GNS3" / "dynamips.exe"],
            "ubridge": [pf / "GNS3" / "ubridge.exe"],
            "qemu-system-x86_64": [pf / "GNS3" / "qemu" / "qemu-system-x86_64w.exe",
                                   pf / "qemu" / "qemu-system-x86_64.exe"],
            "wireshark": [pf / "Wireshark" / "Wireshark.exe"],
            "tshark": [pf / "Wireshark" / "tshark.exe"],
            "docker": [pf / "Docker" / "Docker" / "resources" / "bin" / "docker.exe"],
        }.get(tool, [])

    def packet_tracer_candidates(self):
        pf = self._env_path("ProgramFiles", r"C:\Program Files")
        return [pf / "Cisco Packet Tracer 8.2.2" / "bin" / "PacketTracer.exe",
                pf / "Cisco Packet Tracer 8.2.1" / "bin" / "PacketTracer.exe",
                pf / "Cisco Packet Tracer 8.2.0" / "bin" / "PacketTracer.exe",
                pf / "Cisco Packet Tracer" / "bin" / "PacketTracer.exe"]

    def applications_dir(self):
        appdata = self._env_path("APPDATA", r"C:\Users\user\AppData\Roaming")
        return appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs"

    def detach_kwargs(self):
        return {"creationflags": 0x00000008 | 0x00000200}  # DETACHED_PROCESS|NEW_PROCESS_GROUP
