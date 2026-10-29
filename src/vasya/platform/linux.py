# SPDX-License-Identifier: GPL-3.0-or-later
import os
from pathlib import Path
from .base import Platform


class LinuxPlatform(Platform):
    name = "linux"

    def default_root(self):
        return Path(self.env.get("VASYA_ROOT") or (self.home / "VASYA-GNS-LAB"))

    def gns3_config_candidates(self):
        xdg = Path(self.env.get("XDG_CONFIG_HOME") or (self.home / ".config"))
        c = []
        d = xdg / "GNS3"
        if d.exists():
            c += sorted(d.glob("*/gns3_server.conf"), reverse=True)
        c += [d / "gns3_server.conf", self.home / "GNS3" / "gns3_server.conf",
              Path("/etc/xdg/GNS3/gns3_server.conf"), Path("/etc/gns3/gns3_server.conf")]
        return c

    def validate_root(self, root):
        probs = super().validate_root(root)
        if not str(root).startswith("/"):
            probs.append("path must be absolute")
        for bad in ("/usr", "/etc", "/bin", "/sbin", "/boot", "/proc", "/sys", "/dev"):
            if str(root) == bad or str(root).startswith(bad + "/"):
                probs.append(f"refusing system directory {bad}")
        return probs

    def is_admin(self):
        return os.geteuid() == 0

    def tool_paths(self, tool):
        return {
            "dynamips": ["/usr/bin/dynamips", "/usr/local/bin/dynamips"],
            "ubridge": ["/usr/bin/ubridge", "/usr/local/bin/ubridge"],
            "gns3server": [str(self.home / ".local/bin/gns3server")],
            "gns3": [str(self.home / ".local/bin/gns3"), "/usr/bin/gns3"],
        }.get(tool, [])

    def packet_tracer_candidates(self):
        return [Path("/opt/pt/packettracer"), Path("/opt/pt/bin/PacketTracer"),
                Path("/opt/packettracer/packettracer"),
                Path("/usr/local/bin/packettracer"), Path("/usr/bin/packettracer")]

    def applications_dir(self):
        xdg = Path(self.env.get("XDG_DATA_HOME") or (self.home / ".local/share"))
        return xdg / "applications"

    def detach_kwargs(self):
        return {"start_new_session": True}
