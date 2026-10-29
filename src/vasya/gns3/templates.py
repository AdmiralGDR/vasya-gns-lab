# SPDX-License-Identifier: GPL-3.0-or-later
"""Appliance (.gns3a) + block manifest -> GNS3 2.2 template body.

Ported from 1.0.1 Pack/lib/gns3.py (behaviour preserved, verified 44/44 on
gns3server 2.2.61) with the 006 fixes kept: category mapping
(multilayer_switch -> switch, also for Docker), Dynamips without
console_auto_start.
"""
from ..catalog import fixups as fx

VALID_CATEGORIES = ("router", "switch", "guest", "firewall")
CATEGORY_MAP = {"multilayer_switch": "switch", "switch": "switch", "router": "router",
                "firewall": "firewall", "guest": "guest"}
VASYA_USAGE_TAG = "[VASYA GNS LAB]"


def map_category(cat):
    if cat is None:
        return "guest"
    return CATEGORY_MAP.get(str(cat).strip().lower(), "guest")


def _fn(name, overrides):
    return overrides.get(name, name) if overrides else name


def _usage(gns3a):
    u = (gns3a or {}).get("usage") or ""
    return (u + "\n\n" if u else "") + VASYA_USAGE_TAG


def _boot(q, slots):
    bp = q.get("boot_priority")
    if "cdrom" in slots and fx.EMPTY_DISK.search(slots.get("hda") or ""):
        return bp if (bp or "").startswith("d") else "d"   # installer / live ISO first (D3)
    return bp or ("d" if "hda" not in slots else "c")


def qemu_template(block, gns3a, overrides=None):
    q = (gns3a or {}).get("qemu") or {}
    slots = {}
    for im in block.get("images") or []:
        slot = (im.get("disk_slot") or "hda_disk_image").replace("_image", "")
        slot = {"hda_disk": "hda", "hdb_disk": "hdb", "hdc_disk": "hdc", "hdd_disk": "hdd",
                "image": "hda", "kernel": "kernel", "initrd": "initrd"}.get(slot, slot)
        slots.setdefault(slot, _fn(im["logical_filename"], overrides))
    if not ({"hda", "cdrom", "kernel"} & set(slots)) and block.get("images"):
        slots["hda"] = _fn(block["images"][0]["logical_filename"], overrides)
    t = {
        "name": block["name"], "compute_id": "local", "template_type": "qemu",
        "category": map_category((gns3a or {}).get("category") or block.get("category")),
        "symbol": (gns3a or {}).get("symbol") or ":/symbols/qemu_guest.svg",
        "default_name_format": (gns3a or {}).get("default_name_format") or "{name}-{0}",
        "usage": _usage(gns3a),
        "qemu_path": fx.qemu_binary(q.get("arch") or block.get("architecture")),
        "adapter_type": q.get("adapter_type") or block.get("adapter_type") or "e1000",
        "adapters": q.get("adapters") or block.get("adapters") or 1,
        "ram": max(q.get("ram") or 0, block.get("ram") or 0) or 256,
        "cpus": q.get("cpus") or block.get("cpus") or 1,
        "hda_disk_image": slots.get("hda", ""),
        "hda_disk_interface": q.get("hda_disk_interface") or "ide",
        "console_type": q.get("console_type") or block.get("console_type") or "telnet",
        "options": fx.fix_options(q.get("options") or ""),
        "boot_priority": _boot(q, slots),
        "kernel_image": slots.get("kernel", ""),
        "initrd": slots.get("initrd", ""),
        "kernel_command_line": q.get("kernel_command_line") or "",
        "legacy_networking": False,
        "platform": q.get("arch") or block.get("architecture") or "x86_64",
    }
    for s in ("hdb", "hdc", "hdd"):
        if s in slots:
            t[f"{s}_disk_image"] = slots[s]
            t[f"{s}_disk_interface"] = q.get(f"{s}_disk_interface") or "ide"
    if "cdrom" in slots:
        t["cdrom_image"] = slots["cdrom"]
    if t["platform"] in ("i386", "i486", "i686"):
        t["platform"] = "i386"
    return t


def dynamips_template(block, gns3a, overrides=None):
    dy = (gns3a or {}).get("dynamips") or {}
    image = _fn(block["images"][0]["logical_filename"], overrides) if block.get("images") else None
    idlepc = ""
    for v in (gns3a or {}).get("versions") or []:
        idlepc = v.get("idlepc") or idlepc
    t = {
        "name": block["name"], "compute_id": "local", "template_type": "dynamips",
        "category": map_category((gns3a or {}).get("category") or block.get("category") or "router"),
        "symbol": ":/symbols/router.svg", "default_name_format": "R{0}",
        "usage": _usage(gns3a), "platform": dy.get("platform") or block.get("architecture") or "c7200",
        "image": image, "ram": dy.get("ram") or block.get("ram") or 128,
        "nvram": dy.get("nvram") or 256, "idlepc": idlepc, "console_type": "telnet",
    }
    for k, v in dy.items():
        if k.startswith(("slot", "wic")) and v:
            t[k] = v
    if t["platform"] in ("c3725", "c3745", "c2691"):
        t.pop("chassis", None)
    return t


def docker_template(block, gns3a, overrides=None):
    dk = (gns3a or {}).get("docker") or {}
    usage = _usage(gns3a)
    if block.get("docker_digest"):
        pin = (f"VASYA pin: {block.get('docker_image')}@{block['docker_digest']}"
               f" (image {(block.get('docker_image_id') or '?').split(':')[-1][:12]})")
        usage = f"{usage}\n\n{pin}" if usage else pin
    t = {
        "name": block["name"], "compute_id": "local", "template_type": "docker",
        "category": map_category((gns3a or {}).get("category") or block.get("category")),
        "symbol": (gns3a or {}).get("symbol") or ":/symbols/docker_guest.svg",
        "default_name_format": "{name}-{0}", "usage": usage,
        "image": (overrides or {}).get("__docker__:" + block["block_id"]) or
                 block.get("docker_image") or dk.get("image"),
        "adapters": dk.get("adapters") or 1,
        "console_type": dk.get("console_type") or "telnet",
        "console_http_port": dk.get("console_http_port") or 80,
        "console_http_path": dk.get("console_http_path") or "/",
        "environment": dk.get("environment") or "", "start_command": dk.get("start_command") or "",
        "extra_hosts": dk.get("extra_hosts") or "", "extra_volumes": dk.get("extra_volumes") or [],
    }
    from ..catalog import turnkey
    turnkey.apply_preseed(block, t)
    return t


def build_template(block, gns3a, overrides=None, compute_id="local"):
    fn = {"qemu": qemu_template, "dynamips": dynamips_template,
          "docker": docker_template}.get(block.get("runtime"))
    if not fn:
        return None
    t = fn(block, gns3a, overrides)
    fx.apply_template_fix(block.get("block_id"), t)
    t["compute_id"] = compute_id or "local"
    assert t["category"] in VALID_CATEGORIES, t["category"]
    return t


def node_create_fixups(template_type, body):
    """006 fix: gns3server 2.2.61 rejects console_auto_start on Dynamips node create."""
    if template_type == "dynamips":
        body.pop("console_auto_start", None)
    return body
