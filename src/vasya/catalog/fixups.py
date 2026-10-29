# SPDX-License-Identifier: GPL-3.0-or-later
"""Corrections for upstream appliance data, found during test installs on Pop!_OS 24.04.

D1 internet: '-netdev vde,sock=/var/run/vde2/...' is refused by gns3server 2.2.61 (409 Forbidden
   additional option) and needs a vde_switch system service -> '-net nic,model=e1000 -net user'.
D2 ARM appliances: qemu_path must follow the architecture (qemu-system-arm), and the binary is a
   separate dependency (BLOCKED with a clear message when missing).
D3 ISO-install appliances (Puppy, Smoothwall, IPCop): the upstream version installs an empty
   disk as hda and the ISO as cdrom; 1.0.x used the ISO as hda and 256 MB for Puppy.
   Tested: hda=empty8G, cdrom=ISO, boot from CD, 512 MB -> desktop.
"""
import re

EMPTY_DISK = re.compile(r"(^|-)empty\d+G\.qcow2$")
QEMU_BIN = {"x86_64": "qemu-system-x86_64", "i386": "qemu-system-x86_64", "i486": "qemu-system-x86_64",
            "i686": "qemu-system-x86_64", "arm": "qemu-system-arm", "aarch64": "qemu-system-aarch64"}
ARCH_TOOL = {"arm": "qemu-arm", "aarch64": "qemu-arm"}
ARCH_PACKAGE = {"arm": "qemu-system-arm", "aarch64": "qemu-system-arm"}
LIVE_DESKTOP_MIN_RAM = 512


def qemu_binary(arch):
    return QEMU_BIN.get((arch or "x86_64").lower(), "qemu-system-x86_64")


SLIRP_NET = "-net nic,model=e1000 -net user"


def fix_options(opts):
    """vde uplink -> QEMU user-mode (slirp) uplink, as tested on a real install:
    '-net nic,model=e1000 -net user'. Legacy -net is not in gns3server's forbidden options and
    needs no system service; a GNS3 NAT node is not an option there (no virbr0/libvirt)."""
    if not opts or "-netdev vde" not in opts:
        return opts
    m = re.search(r"-netdev\s+vde,\S*?id=([^\s,]+)", opts)
    nid = m.group(1) if m else None
    rest = re.sub(r"-netdev\s+vde,\S+", "", opts)
    if nid:
        rest = re.sub(r"-device\s+\S*netdev=" + re.escape(nid) + r"\S*", "", rest)
    return " ".join(rest.split() + [SLIRP_NET])


def wanted_hda(gns3a):
    """The version's empty install disk (e.g. empty8G.qcow2), if any."""
    for v in (gns3a or {}).get("versions") or []:
        fn = (v.get("images") or {}).get("hda_disk_image")
        if fn and EMPTY_DISK.search(fn):
            return fn
        break  # only the first (installed) version counts
    return None


def apply_block(block, all_blocks, appliance_loader):
    """Return a corrected copy of a payload block (never mutates the manifest)."""
    if block.get("runtime") == "docker":
        return apply_docker_pin(block)
    if block.get("runtime") != "qemu":
        return block
    imgs = block.get("images") or []
    slots = {i.get("disk_slot") for i in imgs}
    if "cdrom_image" not in slots or "hda_disk_image" in slots:
        return block
    fn = wanted_hda(appliance_loader(block))
    if not fn:
        return block
    src = next((i for b in all_blocks for i in (b.get("images") or []) if i.get("logical_filename") == fn), None)
    if not src:
        return block
    b = dict(block)
    b["images"] = [dict(src, disk_slot="hda_disk_image")] + imgs
    b["fixups"] = list(block.get("fixups") or []) + [f"D3: hda={fn} + cdrom=ISO, boot from CD"]
    if (b.get("category") == "guest" and b.get("console_type") == "vnc"
            and (b.get("ram") or 0) < LIVE_DESKTOP_MIN_RAM):
        b["ram"] = LIVE_DESKTOP_MIN_RAM
        b["fixups"].append(f"D3: ram {block.get('ram')} -> {LIVE_DESKTOP_MIN_RAM} MB")
    return b


def apply_docker_pin(block):
    """Docker pin: the block uses the exact image that was archived and tested (data/docker-images.json):
    ref (tag; offline-restored archives keep no registry digest) + repo digest + image ID."""
    from ..runtime import docker_images as di
    pin = di.pin_for_block(block.get("block_id"))
    if not pin:
        return block
    b = dict(block)
    ref = pin["refs"][0]
    if b.get("docker_image") and b["docker_image"] != ref:
        b["fixups"] = list(block.get("fixups") or []) + [f"docker pin: image {b['docker_image']} -> {ref} (tested pin)"]
    b.update(docker_image=ref, docker_digest=pin.get("repo_digest"), docker_image_id=pin.get("image_id"))
    return b


def missing_dependency(block, tools):
    """(tool_id, apt_package) when the block needs an emulator that is not installed."""
    if block.get("runtime") != "qemu":
        return None
    arch = (block.get("architecture") or "").lower()
    tid = ARCH_TOOL.get(arch)
    if tid and not tools.get(tid, {}).get("present"):
        return tid, ARCH_PACKAGE[arch]
    return None


def _qcow2_vsize(path):
    try:
        with open(path, "rb") as f:
            h = f.read(32)
    except OSError:
        return None
    if len(h) < 32 or h[:4] != b"QFI\xfb":
        return None
    return int.from_bytes(h[24:32], "big")


def equivalent_empty_disk(existing, source, limit=4 * 1024 * 1024):
    """gns3server 2.2.61 ships its own empty*G.qcow2 into images/QEMU at start-up (different bytes,
    same meaning). Two blank qcow2 files with the same virtual size are interchangeable: reuse the
    existing one and do NOT take ownership of it."""
    from pathlib import Path
    e, s = Path(existing), Path(source)
    if not EMPTY_DISK.search(e.name):
        return False
    try:
        if e.stat().st_size > limit or s.stat().st_size > limit:
            return False
    except OSError:
        return False
    v = _qcow2_vsize(e)
    return v is not None and v == _qcow2_vsize(s)


# Per-block template corrections tested on real hardware, merged into
# data/appliance_fixes/<block_id>.json by scripts/merge_template_fixes.py.
# Only these fields may be overridden; image file names stay under plan control.
FIX_FIELDS = {"qemu_path", "options", "ram", "cpus", "boot_priority", "adapter_type", "adapters",
              "console_type", "kvm", "platform", "hda_disk_interface", "kernel_command_line",
              "on_close", "legacy_networking",
              # docker templates
              "default_name_format", "start_command", "environment"}


def template_fix(bid):
    import json
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "data" / "appliance_fixes" / f"{bid}.json"
    if not bid or not p.is_file():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))
    return {k: v for k, v in (d.get("template") or d).items() if k in FIX_FIELDS}


def apply_template_fix(bid, t):
    fix = template_fix(bid)
    t.update(fix)
    return t


GNS3A_QEMU_KEYS = {"options": "options", "ram": "ram", "boot_priority": "boot_priority",
                   "adapters": "adapters", "adapter_type": "adapter_type", "console_type": "console_type"}


def patch_gns3a(bid, d):
    """Bake the proven template fix into the shipped appliance file (build time), so the Payload's
    appliances are correct on their own — not only after VASYA's template generation.
    Returns the list of changed keys; mutates d."""
    fix = template_fix(bid)
    q = (d or {}).get("qemu")
    if not fix or q is None:
        return []
    changed = []
    for fk, qk in GNS3A_QEMU_KEYS.items():
        if fk in fix and q.get(qk) != fix[fk] and not (fk == "options" and not fix[fk] and not q.get(qk)):
            q[qk] = fix[fk]
            changed.append(qk)
    if fix.get("qemu_path") == "qemu-system-arm" and q.get("arch") not in ("arm",):
        q["arch"] = "arm"; changed.append("arch")
    if changed:     # GPL-3.0 section 5(a): the modified file says so, with the date of the change
        d["description"] = ((d.get("description") or "").rstrip() + "\n\n" + MODIFIED_NOTICE.format(
            fields=", ".join(changed))).lstrip()
    return changed


MODIFIED_NOTICE = ("Modified by AdmiralGDR on 2026-10-26 for VASYA GNS LAB (changed: {fields}). "
                   "Original file: GNS3 registry, https://github.com/GNS3/gns3-registry, GPL-3.0.")
