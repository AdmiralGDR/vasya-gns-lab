# SPDX-License-Identifier: GPL-3.0-or-later
"""Find an existing GNS3 installation without assuming ~/GNS3/images."""
import configparser, os
from pathlib import Path
from .client import GNS3Client

DEFAULT_PORTS = (3080, 3081)


def parse_server_conf(path):
    cp = configparser.ConfigParser(interpolation=None)
    try:
        cp.read(path, encoding="utf-8")
    except Exception:
        return {}
    sec = next((s for s in cp.sections() if s.lower() == "server"), None)
    if not sec:
        return {}
    g = lambda k, d=None: cp.get(sec, k, fallback=d)
    return {
        "config": str(path), "host": g("host", "127.0.0.1"),
        "port": int(g("port", "3080") or 3080), "images_path": g("images_path"),
        "appliances_path": g("appliances_path"), "projects_path": g("projects_path"),
        "configs_path": g("configs_path"), "user": g("user"), "password": g("password"),
        "auth": (g("auth", "False") or "").lower() == "true",
    }


def discover(platform, explicit=None):
    """Return dict describing the GNS3 target. `explicit` (dict) overrides."""
    info = {"gui": platform.find_tool("gns3", ["gns3"]),
            "server_bin": os.environ.get("VASYA_GNS3SERVER_BIN") or
                          platform.find_tool("gns3server", ["gns3server"]),
            "config": None, "images_path": None, "appliances_path": None,
            "projects_path": None, "host": "127.0.0.1", "port": None,
            "api_base": None, "api_ok": False, "version": None, "user": None,
            "password": None}
    conf = os.environ.get("VASYA_GNS3_CONFIG")
    cands = ([Path(conf)] if conf else []) + list(platform.gns3_config_candidates())
    for c in cands:
        if Path(c).exists():
            info.update({k: v for k, v in parse_server_conf(c).items() if v is not None})
            break
    if explicit:
        info.update({k: v for k, v in explicit.items() if v is not None})
    home_gns3 = platform.home / "GNS3"
    if not info.get("images_path") and info.get("config"):
        info["images_path"] = str(home_gns3 / "images")
    if not info.get("appliances_path") and info.get("config"):
        info["appliances_path"] = str(home_gns3 / "appliances")
    ports = [int(info["port"])] if info.get("port") else []
    ports += [p for p in DEFAULT_PORTS if p not in ports]
    if info.get("api_base"):
        ports = []
        cl = GNS3Client(info["api_base"], info.get("user"), info.get("password"))
        v = cl.version()
        info.update(api_ok=v is not None, version=v)
    for p in ports:
        base = f"http://{info['host']}:{p}"
        v = GNS3Client(base, info.get("user"), info.get("password")).version(timeout=0.7)
        if v:
            info.update(api_base=base, api_ok=True, version=v, port=p)
            break
    return info


def client_for(info):
    return GNS3Client(info["api_base"], info.get("user"), info.get("password"))


def image_dir(images_path, runtime):
    base = Path(images_path)
    return {"dynamips": base / "IOS", "qemu": base / "QEMU", "iou": base / "IOU"}.get(runtime, base)
