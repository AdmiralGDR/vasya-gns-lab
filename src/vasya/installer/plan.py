# SPDX-License-Identifier: GPL-3.0-or-later
"""Planning: compute every change BEFORE touching anything (dry-run == plan)."""
import os
from . import remote_plan as rc_plan
from pathlib import Path
from ..catalog.fixups import equivalent_empty_disk
from ..core.util import new_id, utc_now, sha256_file, human_bytes, free_disk_bytes
from ..gns3.discover import image_dir
from ..gns3.client import GNS3Client
from ..runtime import managed_server as ms
from ..tools.registry import detect_all
from ..core.cas import same_device
from .requirements import assess
from ..runtime import bundled_server as bsrv

HASH_PLAN_LIMIT = 256 * 1024 * 1024


def classify(dest, sha, size):
    p = Path(dest)
    if not p.exists():
        return "NEW"
    if size and p.stat().st_size != size:
        return "CONFLICT"
    if p.stat().st_size <= HASH_PLAN_LIMIT or os.environ.get("VASYA_PLAN_DEEP") == "1":
        return "IDENTICAL" if sha256_file(p) == sha else "CONFLICT"
    return "SAME_SIZE"  # hashed at apply time


def link_methods(src, dest_dir, allow_copy=False):
    """Hardlink when on the same filesystem, else symlink (reference); copy only if allowed."""
    # always *try* a hardlink first: st_dev is unreliable on overlay/btrfs subvolumes
    m = ["hardlink", "symlink"]
    if allow_copy:
        m.append("copy")
    return m


def alt_name(sha, logical):
    return f"vasya-{sha[:16]}-{logical}"


def build_plan(ctx, target, block_ids=None, mode="INTEGRATION", desktop=False, allow_copy=False):
    blocks = [b for b in ctx.blocks() if block_ids is None or b["block_id"] in block_ids]
    unknown = sorted(set(block_ids or []) - {b["block_id"] for b in blocks})
    ops, conflicts, present = [], [], []
    bytes_copy = 0
    bytes_link = 0
    blocked = []
    n = 0
    names = {b["block_id"]: b.get("name") or b["block_id"] for b in blocks}

    def add(action, **kw):
        nonlocal n
        n += 1
        op = {"op_id": f"{n:04d}", "action": action}
        op.update(kw)
        if kw.get("block_id"):
            op["label"] = names.get(kw["block_id"], kw["block_id"])
        ops.append(op)
        return op

    managed = bool(target.get("managed"))
    bundle = os.environ.get("VASYA_BUNDLE_DIR")
    app_src = Path(bundle) / "App" if bundle and (Path(bundle) / "App").is_dir() and \
        Path(bundle).resolve() != ctx.layout.root.resolve() else None
    server_bundled = False
    if managed and not target.get("server_bin") and \
            (bsrv.available(app_src) or bsrv.available(ctx.layout.App)):
        target["server_bin"] = str(bsrv.launcher(ctx.layout.App))
        server_bundled = True
    if app_src:  # first: the bundled gns3server (if used) lives in <root>/App
        add("INSTALL_APP", source=str(app_src), target=str(ctx.layout.App))
    if managed:
        add("MANAGED_GNS3", target=target["config"], port=target["port"],
            server_bin=target.get("server_bin"))
    images_path = target.get("images_path")
    appl = target.get("appliances_path")
    existing_templates = []
    if target.get("api_ok"):
        try:
            existing_templates = GNS3Client(target["api_base"]).templates()
        except Exception:
            existing_templates = []
    tnames = {(t.get("name"), t.get("template_type")): t for t in existing_templates}
    docker_needed = []
    placed = set()
    cid = target.get("compute_id") or "local"
    remote = rc_plan.RemotePlanner(ctx, target, add, present, conflicts) if cid != "local" else None
    from ..catalog.fixups import missing_dependency
    tools0 = detect_all(ctx.platform)
    blocked_deps = []
    unavailable = []
    from ..runtime import docker_backend as dbk
    dbe, dbe_reason = dbk.select(ctx), dbk.unavailable_reason(ctx)
    for b in blocks:
        bid, rt = b["block_id"], b["runtime"]
        dep = None if remote else missing_dependency(b, tools0)
        if not remote and rt == "docker" and dbe_reason:
            blocked_deps.append({"block_id": bid, "name": b.get("name"), "needs": "docker-backend",
                                 "package": dbe, "command": dbe_reason})
            add("BLOCKED_DEPENDENCY", block_id=bid, target=b.get("name"), needs="docker-backend",
                package=dbe, command=dbe_reason)
            continue
        if dep:
            cmd = f"sudo apt-get install --no-install-recommends {dep[1]}" if ctx.platform.name == "linux" else dep[1]
            blocked_deps.append({"block_id": bid, "name": b.get("name"), "needs": dep[0],
                                 "package": dep[1], "command": cmd})
            add("BLOCKED_DEPENDENCY", block_id=bid, target=b.get("name"), needs=dep[0],
                package=dep[1], command=cmd)
            continue
        if not remote and images_path:
            gone = [im for im in b.get("images") or []
                    if not ctx.payload.image_path(im["sha256"]).exists()
                    and classify(image_dir(images_path, rt) / im["logical_filename"], im["sha256"],
                                 im.get("size")) not in ("IDENTICAL", "SAME_SIZE")]
            if gone:
                unavailable.append({"block_id": bid, "name": b.get("name"),
                                    "images": [im["logical_filename"] for im in gone]})
                add("IMAGE_NOT_AVAILABLE", block_id=bid, target=b.get("name"),
                    images=[im["logical_filename"] for im in gone])
                continue
        for im in b.get("images") or []:
            if remote:
                remote.image(b, im)
                continue
            if not images_path:
                continue
            dest = image_dir(images_path, rt) / im["logical_filename"]
            key = str(dest)
            if key in placed:
                continue
            placed.add(key)
            src = ctx.payload.image_path(im["sha256"])
            cls = classify(dest, im["sha256"], im.get("size"))
            if cls == "CONFLICT" and equivalent_empty_disk(dest, src):
                cls = "IDENTICAL"   # GNS3's own blank disk, same virtual size (not ours to own)
            methods = link_methods(src, dest.parent, allow_copy)
            if cls in ("NEW", "CONFLICT") and not methods:
                blocked.append({"block_id": bid, "image": im["logical_filename"],
                                "size": im.get("size"), "reason": "hardlink/symlink impossible; copy not allowed"})
                add("BLOCKED_IMAGE", block_id=bid, target=str(dest), size=im.get("size"))
                continue
            if cls == "NEW":
                add("PLACE_IMAGE", block_id=bid, source=str(src), target=str(dest),
                    sha256=im["sha256"], size=im.get("size"), methods=methods)
                if methods[0] == "copy":
                    bytes_copy += im.get("size") or 0
                else:
                    bytes_link += im.get("size") or 0
            elif cls in ("IDENTICAL", "SAME_SIZE"):
                add("REUSE_IMAGE", block_id=bid, target=str(dest), sha256=im["sha256"],
                    size=im.get("size"), verify_at_apply=cls == "SAME_SIZE")
                present.append(f"image {dest.name}")
            else:
                alt = dest.with_name(alt_name(im["sha256"], im["logical_filename"]))
                conflicts.append({"block_id": bid, "path": str(dest), "installed_as": alt.name})
                add("PLACE_IMAGE_ALT", block_id=bid, source=str(src), target=str(alt),
                    original=str(dest), sha256=im["sha256"], size=im.get("size"),
                    logical=im["logical_filename"], methods=methods)
                if methods[0] == "copy":
                    bytes_copy += im.get("size") or 0
                else:
                    bytes_link += im.get("size") or 0
        ap = ctx.appliance_path(b)
        if appl and ap and b.get("appliance_meta_ok", True):
            add("PLACE_APPLIANCE", block_id=bid, source=str(ap),
                target=str(Path(appl) / f"vasya-{bid}.gns3a"))
        if rt == "docker" and b.get("docker_image") and remote:
            remote.docker(b)
        elif rt == "docker" and b.get("docker_image"):
            add("ENSURE_DOCKER_IMAGE", block_id=bid, target=b["docker_image"])
            docker_needed.append(b["docker_image"])
        if (b["name"], rt) in tnames:
            add("REUSE_TEMPLATE", block_id=bid, target=b["name"],
                template_id=tnames[(b["name"], rt)].get("template_id"))
            present.append(f"template {b['name']}")
        else:
            add("REGISTER_TEMPLATE", block_id=bid, target=b["name"], runtime=rt)
    add("DESKTOP_FILES_IN_ROOT", target=str(ctx.layout.Desktop))
    if desktop and ctx.platform.applications_dir():
        # explicit, user-confirmed, receipted step only (never default)
        add("DESKTOP_ENTRY", target=str(ctx.platform.applications_dir() / "vasya-gns-lab.desktop"))
    tools = detect_all(ctx.platform)
    runtimes = {b["runtime"] for b in blocks}
    need = {"qemu": ["qemu", "qemu-img"], "dynamips": ["dynamips"],
            "docker": ["busybox"] if dbe == "podman-rootless" else ["docker", "busybox"]}  # podman: never shared docker
    deps_missing = sorted({t for r in runtimes for t in need.get(r, [])
                           if not tools.get(t, {}).get("present")}) if not remote else []
    if not target.get("server_bin") and managed:
        deps_missing.append("gns3server")
    for t in ("ubridge",):
        if not tools.get(t, {}).get("present") and not remote:
            deps_missing.append(t)
    free = free_disk_bytes(images_path or ctx.layout.root)
    admin = any(ctx.platform.needs_admin_for(o["target"]) for o in ops
                if o["action"].startswith("PLACE"))
    reboot = []
    if "qemu" in runtimes and tools.get("kvm", {}).get("present") and \
            not tools.get("kvm", {}).get("accessible"):
        reboot.append("user must be in group 'kvm' (re-login required)")
    if docker_needed and dbe == "shared-daemon" and tools.get("docker", {}).get("present") and \
            not tools.get("docker", {}).get("accessible"):
        reboot.append("user must be in group 'docker' (re-login required)")
    from ..gns3.discover import discover
    ex = discover(ctx.platform)
    existing = {"found": bool(ex.get("config") or ex.get("api_ok") or ex.get("gui")),
                "config": ex.get("config"), "gui": ex.get("gui"),
                "api_base": ex.get("api_base") if ex.get("api_ok") else None,
                "version": (ex.get("version") or {}).get("version") if ex.get("api_ok") else None}
    installed_before = sorted(b for b, c in ctx.state.load().get("components", {}).items() if c.get("installed"))
    req = assess(ctx.platform, tools, runtimes, docker_needed, mode, desktop=desktop,
                 bundled_server=server_bundled, docker_backend=dbe)
    if req["relogin"]:
        reboot = [f"{w} (re-login required)" for w in req["relogin"]]
    preview = {
        "existing_gns3": existing, "server_bundled": server_bundled, "reinstall": bool(installed_before),
        "already_installed_blocks": len(installed_before),
        "programs": req["programs"], "system_changes": req["system_changes"],
        "download_bytes": req["download_bytes"], "download_human": req["download_human"],
        "download_unknown": req["download_unknown"], "reboot": False,
        "target_writable": not ctx.platform.needs_admin_for(ctx.layout.root),
        "blocks": len(blocks), "unknown_blocks": unknown,
        "bytes_to_copy": bytes_copy, "bytes_to_copy_human": human_bytes(bytes_copy),
        "bytes_linked": bytes_link, "bytes_linked_human": human_bytes(bytes_link),
        "blocked_images": blocked, "allow_copy": allow_copy,
        "free_bytes": free, "free_human": human_bytes(free),
        "space_needed": int(bytes_copy * 1.05 + 256 * 1024 ** 2),
        "space_needed_human": human_bytes(int(bytes_copy * 1.05 + 256 * 1024 ** 2)),
        "space_ok": free > bytes_copy * 1.05 + 256 * 1024 ** 2,
        "downloads": [{"kind": "docker", **d} for d in req["download"]],
        "deps_missing": deps_missing, "already_present": present,
        "conflicts": conflicts, "admin_required": admin or bool(deps_missing) or req["admin_required"],
        "admin_reason": ("missing system packages: " + ", ".join(deps_missing)) if deps_missing
                        else ("target directory not writable" if admin else ""),
        "reboot_or_relogin": reboot,
        "blocked_components": blocked_deps,
        "images_not_available": unavailable,
        "compute_id": cid, "remote": remote.summary() if remote else None,
        "safe_cancel": "Cancel at any point rolls back everything this run created (WAL).",
    }
    if docker_needed and dbe == "podman-rootless":
        from ..runtime import docker_images as di
        preview["docker_image_pack"] = di.pack_status(ctx)
        if preview["docker_image_pack"]["status"] != "PRESENT":
            preview["docker_image_pack"]["note"] = (
                f"{di.PACK_MISSING}: {preview['docker_image_pack']['present']}/{preview['docker_image_pack']['archives']}"
                f" Docker image archives present; Docker components without theirs are skipped")
    return {"plan_id": new_id("plan-"), "created_at": utc_now(), "mode": mode,
            "target": {k: target.get(k) for k in ("api_base", "images_path", "appliances_path",
                                                  "config", "version", "managed", "port",
                                                  "compute_id")},
            "block_ids": [b["block_id"] for b in blocks], "operations": ops, "preview": preview,
            "summary": {"operations": len(ops),
                        "create": sum(o["action"].startswith(("PLACE", "REGISTER", "ENSURE", "DESKTOP", "MANAGED")) for o in ops),
                        "reuse": sum(o["action"].startswith("REUSE") for o in ops),
                        "conflicts": len(conflicts)}}
