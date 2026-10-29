# SPDX-License-Identifier: GPL-3.0-or-later
"""Facade shared by CLI and GUI. Both call these functions; neither has its own logic."""
from . import VERSION
from .core import txn as txnmod
from .installer.context import Context
from .installer import service as inst
from .installer.target import resolve_target
from .tools.registry import detect_all, registry
from .tools import packet_tracer
from .uninstall import service as uninst
from . import verifier, updater, diagnostics
from .demos import labs
from .catalog import image_import


def open_ctx(root, payload=None):
    return Context(root, payload)


def status(ctx, probe=True):
    """Home-screen / `vasya status` data. Pure read of the shared state store."""
    st = ctx.state.load()
    comps = st["components"]
    g = st.get("gns3") or {}
    tools = detect_all(ctx.platform)
    api_ok = None
    version = None
    if probe and g.get("api_base"):
        from .gns3.client import GNS3Client
        version = GNS3Client(g["api_base"]).version()
        api_ok = version is not None
    ready = ctx.ready_ids()
    installed = sorted(b for b, c in comps.items() if c.get("installed"))
    rv = sorted(b for b, c in comps.items() if c.get("installed") and c.get("runtime_verified") == "PASS")
    errors = sorted(b for b, c in comps.items() if c.get("error") or
                    c.get("runtime_verified") == "FAIL" or c.get("static_verified") == "FAIL")
    by_rt = {}
    for b in ctx.blocks():
        r = by_rt.setdefault(b["runtime"], {"ready": 0, "installed": 0, "runtime_verified": 0})
        r["ready"] += 1
        c = comps.get(b["block_id"], {})
        r["installed"] += bool(c.get("installed"))
        r["runtime_verified"] += bool(c.get("installed") and c.get("runtime_verified") == "PASS")
    inc = txnmod.incomplete(ctx.layout) if ctx.layout.txn_dir.exists() else []
    return {
        "product_version": VERSION, "root": str(ctx.layout.root),
        "installed": ctx.layout.exists() and bool(installed), "mode": st.get("mode"),
        "gns3": {"present": bool(tools.get("gns3server", {}).get("present") or g.get("api_base")),
                 "gui_present": bool(tools.get("gns3", {}).get("present")),
                 "managed": bool(g.get("managed")), "api_base": g.get("api_base"),
                 "api_ok": api_ok, "version": version},
        "runtimes": {k: bool(tools.get(k, {}).get("present")) for k in
                     ("qemu", "kvm", "dynamips", "docker", "ubridge", "wireshark", "tshark")},
        "components": {"catalog": len(ctx.catalog), "ready": len(ready),
                       "installed": len(installed), "runtime_verified": len(rv),
                       "errors": len(errors), "by_runtime": by_rt},
        "error_blocks": errors, "incomplete_transactions": [r["txid"] for r in inc],
        "first_run_done": bool(st.get("first_run_done")),
        "last_operation": st.get("last_operation"),
    }


def verdict(s):
    """One-line verdict string; CLI and GUI must render exactly this."""
    c = s["components"]
    if s["incomplete_transactions"]:
        return "NEEDS_RECOVERY"
    if not c["installed"]:
        return "NOT_INSTALLED"
    if c["errors"]:
        return "DEGRADED"
    if c["runtime_verified"] == c["installed"]:
        return "HEALTHY_VERIFIED"
    return "INSTALLED_UNVERIFIED"


plan = inst.dry_run
install = inst.install
resume = inst.resume
repair = inst.repair
retry_failed = inst.retry_failed
preflight = inst.preflight
rollback = inst.rollback
static_verify = verifier.static_verify
runtime_verify = verifier.runtime_verify
uninstall = uninst.uninstall


def find_release_manifest(ctx, extra_dirs=()):
    """Where the downloaded Linux release parts are (Windows Setup / --import-payload)."""
    from pathlib import Path
    import os
    dirs = [Path(d) for d in extra_dirs]
    src = ctx.layout.root / "payload_source.txt"
    if src.exists():
        dirs.append(Path(src.read_text(encoding="utf-8").strip()))
    home = Path.home()
    dirs += [home / "Downloads", home / "Загрузки", Path.cwd()]
    for d in dirs:
        for sub in (d, d / "drive-parts"):
            hits = sorted(sub.glob("VASYA-GNS-LAB-*-Linux.tar.zst.parts.json")) if sub.is_dir() else []
            if hits:
                return str(hits[-1])
    return None


def import_payload(ctx, manifest=None, search_dirs=(), progress=None):
    from .delivery.payload_import import import_payload as imp
    from .delivery.parts import PartsError
    m = manifest or find_release_manifest(ctx, search_dirs)
    if not m:
        return {"status": "BLOCKED", "code": "PARTS_MISSING",
                "error": "release parts (*.parts.json + .partNNN) not found",
                "error_ru": "не найдены части релиза (*.parts.json и .partNNN)"}
    ctx.layout.root.mkdir(parents=True, exist_ok=True)
    try:
        r = imp(ctx.layout.root, m, search_dirs, progress)
    except PartsError as e:
        return {"status": "FAIL", "code": e.code, "error": str(e), "detail": e.detail}
    ctx.layout.State.mkdir(parents=True, exist_ok=True)
    with ctx.state.edit() as st:
        st["payload_root"] = r["store"]
    return dict(r, status="OK", manifest=m)


def system_packages_offer(ctx):
    from .installer import system_packages as sp
    return sp.offer(ctx)
inventory = uninst.inventory
update_store = updater.update_store
store_delta = updater.store_delta
diagnostics_zip = diagnostics.build
tool_registry = registry


def busy_nodes(ctx):
    from .runtime.busy import busy_nodes as b
    return b(ctx)


def stop_busy_nodes(ctx):
    from .runtime.busy import busy_nodes as b, stop_nodes
    return stop_nodes(ctx, b(ctx))


def explain_error(msg, lang="ru"):
    from .errors import explain
    return explain(msg, lang)


def packet_tracer_status(ctx):
    imp = ctx.state.load().get("packet_tracer_import")
    return packet_tracer.detect(ctx.platform, imp)


def packet_tracer_import(ctx, path):
    v = packet_tracer.verify_installer(path, ctx.platform.name)
    with ctx.state.edit() as s:
        s["packet_tracer_import"] = v
    ctx.oplog("pt-import").log("PT_IMPORT_VERIFY", path, "PASS" if v["verified"] else "FAIL",
                               actual_sha256=v.get("sha256"), after={"checks": v.get("checks")})
    return v


def analyse_image(ctx, path):
    return image_import.analyse(path, ctx.catalog)


def register_image(ctx, analysis, block_id, allow_unverified=False):
    ctx.layout.ensure()
    t = txnmod.Transaction(ctx.layout, "import", meta={"block": block_id})
    log = ctx.oplog(t.txid)
    rec = image_import.register(ctx.layout, analysis, block_id, t, log, allow_unverified)
    t.end("OK", {"block": block_id})
    ctx.user_images = image_import.load_registry(ctx.layout)
    return rec


demo_definitions = labs.definitions
demo_create = labs.create
demo_check = labs.run_check
demo_remove = labs.remove


def register_desktop(ctx):
    """Explicit, user-confirmed step: register the .desktop (kept in <root>/Desktop)
    into ~/.local/share/applications. Receipted in its own transaction."""
    from .desktop import integration as desk
    from .core.util import utc_now
    lay = ctx.layout.ensure()
    t = txnmod.Transaction(lay, "desktop")
    dst = ctx.platform.applications_dir() / desk.DESKTOP_NAME
    if dst.exists():
        t.end("OK", {"reuse": str(dst)})
        return {"status": "ALREADY_REGISTERED", "path": str(dst)}
    t.intent("0001", {"kind": "desktop_file", "path": str(dst)})
    p = desk.register(lay, ctx.platform)
    gui_libs_ensure(ctx)  # the launcher prepends <root>/Runtime/lib when present
    t.commit("0001", {"kind": "desktop_file", "path": str(p)})
    t.end("OK", {"path": str(p)})
    with ctx.state.edit() as s:
        s["desktop"] = {"registered": str(p), "entry": str(lay.Desktop / desk.DESKTOP_NAME),
                        "txid": t.txid, "at": utc_now()}
    ctx.oplog(t.txid).log("REGISTER_DESKTOP", p, "NEW", operation_id="0001")
    return {"status": "REGISTERED", "path": str(p), "txid": t.txid}


def unregister_desktop(ctx):
    from .desktop import integration as desk
    st = ctx.state.load().get("desktop") or {}
    if not st.get("registered"):
        return {"status": "NOT_REGISTERED"}
    removed = desk.unregister(st["registered"])
    for r in txnmod.all_receipts(ctx.layout):
        for x in r["committed"]:
            if x.get("kind") == "desktop_file" and x.get("path") == st["registered"]:
                txnmod.open_tx(ctx.layout, r["txid"]).mark_released(x["op_id"], "unregister")
    with ctx.state.edit() as s:
        s["desktop"] = {"entry": st.get("entry")}
    return {"status": "REMOVED" if removed else "ABSENT"}


def gns3_config_check(ctx):
    from .installer.gns3_config_guard import check_config
    return check_config(ctx)


def gns3_config_restore(ctx):
    from .installer.gns3_config_guard import restore_config
    return restore_config(ctx)


def gui_deps_check(ctx, gns3_cmd="gns3"):
    """PyQt6 for gns3-gui + xcb libs Qt >= 6.5 needs. Report only."""
    from .runtime import gui_deps
    return gui_deps.check(ctx, gns3_cmd)


def gui_libs_ensure(ctx):
    """Put pinned xcb libs missing system-wide into <root>/Runtime/lib (downloaded and verified, receipted, no admin)."""
    import sys as _s
    if not _s.platform.startswith("linux"):
        return {"status": "SKIPPED", "reason": "linux only"}
    from .runtime import gui_deps
    ctx.layout.ensure()
    return gui_deps.bundle_libxcb_cursor(ctx)
