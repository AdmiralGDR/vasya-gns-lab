# SPDX-License-Identifier: GPL-3.0-or-later
"""vasya-gns command line — full automation interface (same backend as the GUI)."""
import argparse, json, os, sys
from pathlib import Path
from . import VERSION, api
from .core.layout import default_root
from .core.util import human_bytes


def _p(obj, as_json):
    if as_json:
        print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            print(f"{k}: {v if not isinstance(v, (dict, list)) else json.dumps(v, ensure_ascii=False, default=str)}")
    else:
        print(obj)


LANG = os.environ.get("VASYA_LANG") or ("ru" if os.environ.get("LANG", "").startswith("ru") else "en")


def _progress(i, n, op, res):
    from .installer.progress_text import describe
    print(describe(i, n, op, res, LANG, op.get("last_error")), flush=True)


def _blocked(r, j):
    from .errors import render
    if j:
        _p(r, True)
    else:
        print(render(r["error_ru"] if LANG == "ru" else r["error"]))
    return 3


def build_parser():
    ap = argparse.ArgumentParser(prog="vasya-gns", description=f"VASYA GNS LAB {VERSION}")
    ap.add_argument("--root", default=None, help="ONE-ROOT directory (default ~/VASYA-GNS-LAB)")
    ap.add_argument("--payload", default=None, help="payload store (READY images + manifests)")
    ap.add_argument("--json", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("version")
    sub.add_parser("status")
    for name in ("plan", "install"):
        s = sub.add_parser(name)
        s.add_argument("--mode", choices=["FULL", "INTEGRATION", "SELECTIVE"], default="INTEGRATION")
        s.add_argument("--blocks", default=None, help="comma-separated block ids (SELECTIVE)")
        s.add_argument("--api", default=None, help="explicit GNS3 API base, e.g. http://127.0.0.1:3080")
        s.add_argument("--compute", default=None,
                       help="GNS3 compute for QEMU/Dynamips/Docker: local | vm | <id> (default: auto — GNS3 VM on Windows)")
        s.add_argument("--images-path", default=None)
        s.add_argument("--appliances-path", default=None)
        s.add_argument("--no-docker-pull", action="store_true")
        s.add_argument("--register-desktop", action="store_true",
                       help="also register the menu entry in ~/.local/share/applications (receipted)")
        s.add_argument("--allow-copy", action="store_true",
                       help="allow full copies of images when hardlink/symlink is impossible")
        s.add_argument("-y", "--yes", action="store_true")
    sub.add_parser("resume")
    s = sub.add_parser("fetch", help="download pinned images and helper programs only (no install)")
    s.add_argument("--blocks", default=None, help="comma-separated block ids (default: all)")
    s.add_argument("--no-tools", action="store_true")
    s.add_argument("--no-images", action="store_true")
    s.add_argument("--no-private", action="store_true", help="skip the private image sources")
    s.add_argument("--docker", action="store_true", help="also pull the pinned Docker images (podman)")
    s.add_argument("--dry-run", action="store_true", help="only show what is missing and where it comes from")
    s = sub.add_parser("verify"); s.add_argument("--runtime", action="store_true")
    s.add_argument("--blocks", default=None)
    s = sub.add_parser("repair"); s.add_argument("--force", action="store_true", help="even if lab nodes are running")
    sub.add_parser("retry", help="retry only components that failed (e.g. Docker pulls without Internet)")
    s = sub.add_parser("rollback"); s.add_argument("--txid", default=None)
    s = sub.add_parser("uninstall"); s.add_argument("--level", choices=["components", "full"], default="components")
    s.add_argument("--keep-docker", action="store_true"); s.add_argument("-y", "--yes", action="store_true")
    s.add_argument("--projects", choices=["export", "keep", "delete"], default="keep",
                   help="user projects inside the VASYA folder (full level)")
    s.add_argument("--force", action="store_true", help="even if lab nodes are running")
    s = sub.add_parser("import-payload", help="take images+manifests from the downloaded Linux release parts")
    s.add_argument("manifest", nargs="?", help="VASYA-GNS-LAB-<ver>-Linux.tar.zst.parts.json (auto-search if omitted)")
    s.add_argument("--search", action="append", default=[])
    s = sub.add_parser("update"); s.add_argument("source", help="new payload directory")
    s.add_argument("--allow-copy", action="store_true")
    s.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("catalog"); s.add_argument("query", nargs="?", default="")
    s.add_argument("--status", default=None); s.add_argument("--runtime", default=None)
    s.add_argument("--export-csv", default=None)
    s = sub.add_parser("import-image"); s.add_argument("path"); s.add_argument("--block", default=None)
    s.add_argument("--register", action="store_true"); s.add_argument("--allow-unverified", action="store_true")
    sub.add_parser("tools")
    s = sub.add_parser("packet-tracer"); s.add_argument("--import-installer", default=None)
    s = sub.add_parser("diagnostics"); s.add_argument("--out", default=None)
    sub.add_parser("inventory")
    s = sub.add_parser("demo"); s.add_argument("action", choices=["list", "create", "check", "remove"])
    s.add_argument("id", nargs="?")
    sub.add_parser("logs")
    s = sub.add_parser("desktop"); s.add_argument("action", choices=["register", "unregister"])
    s = sub.add_parser("gns3-config"); s.add_argument("action", choices=["check", "restore"])
    s = sub.add_parser("gui-deps", help="PyQt6 + xcb libs for the GNS3 GUI")
    s.add_argument("--bundle", action="store_true", help="place bundled xcb libs under <root>/Runtime/lib")
    s.add_argument("--gns3", default="gns3")
    return ap


def _target(a):
    if not a.api:
        return None
    return {"api_base": a.api, "images_path": a.images_path, "appliances_path": a.appliances_path,
            "compute_id": getattr(a, "compute", None)}


def main(argv=None):
    a = build_parser().parse_args(argv)
    root = a.root or str(default_root())
    if a.cmd == "version":
        print(f"VASYA GNS LAB {VERSION}"); return 0
    ctx = api.open_ctx(root, a.payload)
    j = a.json
    if a.cmd == "status":
        s = api.status(ctx); s["verdict"] = api.verdict(s); _p(s, j); return 0
    if a.cmd == "plan":
        blocks = a.blocks.split(",") if a.blocks else None
        p = api.plan(ctx, a.mode, blocks, _target(a), desktop=a.register_desktop, allow_copy=a.allow_copy)
        if j:
            _p(p, True)
        else:
            pv = p["preview"]
            print(f"PLAN {p['plan_id']} mode={a.mode} blocks={pv['blocks']} ops={p['summary']['operations']}")
            for k in ("bytes_to_copy_human", "space_needed_human", "free_human", "space_ok", "download_human",
                      "deps_missing", "admin_required", "admin_reason", "reboot_or_relogin", "conflicts"):
                print(f"  {k}: {pv[k]}")
            print("  system changes (outside the VASYA folder):")
            for c in pv["system_changes"]:
                print(f"    - [{c['kind']}] {c['what']}" + (f"  → {c['command']}" if c.get("admin") else ""))
            print("NO CHANGES HAVE BEEN MADE.")
        return 0
    if a.cmd == "install":
        blocks = a.blocks.split(",") if a.blocks else None
        if not a.yes:
            p = api.plan(ctx, a.mode, blocks, _target(a), desktop=a.register_desktop, allow_copy=a.allow_copy)
            print(f"Will copy {p['preview']['bytes_to_copy_human']}, {p['summary']['operations']} operations.")
            if input("Proceed? [y/N]: ").strip().lower() not in ("y", "yes"):
                print("cancelled"); return 1
        r = api.install(ctx, a.mode, blocks, _target(a), pull_docker=not a.no_docker_pull,
                        progress=None if j else _progress, desktop=a.register_desktop, allow_copy=a.allow_copy)
        if r["status"] == "BLOCKED":
            return _blocked(r, j)
        out = {"status": r["status"], "txid": r["txid"], "failed": r.get("failed")}
        _p(out, j); return 0 if r["status"] == "OK" else 2
    if a.cmd == "fetch":
        blocks = a.blocks.split(",") if a.blocks else None
        if a.dry_run:
            from .fetch import images as fi, lock as fl, private as fp
            lk, priv = fl.load(), fp.manifest_images(ctx.layout)
            need = fi.needed(ctx, blocks)
            rows = {s: dict(n, source="public" if s in lk.get("images", {}) else
                            "private" if s in priv else "none") for s, n in need.items()}
            _p({"missing_images": rows, "private_sources": [fp.describe(x) for x in fp.sources()]}, j)
            return 0
        from .fetch.prepare import prepare
        r = prepare(ctx.layout.ensure() and ctx, blocks, tools=not a.no_tools, images=not a.no_images,
                    use_private=not a.no_private, docker=a.docker)
        _p(r, j)
        im = r.get("images") or {}
        return 0 if not im.get("error") else 2
    if a.cmd == "resume":
        r = api.resume(ctx, progress=None if j else _progress)
        _p({k: r.get(k) for k in ("status", "txid", "recovered", "failed")}, j)
        return 0 if r["status"] in ("OK", "NOTHING_TO_RESUME") else 2
    if a.cmd == "verify":
        blocks = a.blocks.split(",") if a.blocks else None
        r = api.static_verify(ctx, blocks)
        out = {"static": r["status"], "static_failed": r["failed"], "blocks": r["blocks"]}
        if a.runtime:
            rr = api.runtime_verify(ctx, blocks, progress=None if j else
                                    (lambda i, n, b, s: print(f"[{i}/{n}] {b}: {s}", flush=True)))
            out.update(runtime=rr["status"], runtime_passed=rr.get("passed"), runtime_total=rr.get("total"),
                       runtime_results=rr.get("results") if j else None)
        _p(out, j); return 0 if out["static"] == "PASS" and out.get("runtime", "PASS") == "PASS" else 2
    if a.cmd == "repair":
        r = api.repair(ctx, progress=None if j else _progress, force=a.force)
        if r["status"] == "BLOCKED":
            return _blocked(r, j)
        _p({k: r.get(k) for k in ("status", "txid", "damaged_before", "quarantined", "failed_after")}, j)
        return 0 if r["status"] == "OK" else 2
    if a.cmd == "retry":
        r = api.retry_failed(ctx, progress=None if j else _progress)
        if r["status"] == "BLOCKED":
            return _blocked(r, j)
        _p({k: r.get(k) for k in ("status", "txid", "retried", "failed")}, j)
        return 0 if r["status"] in ("OK", "NOTHING_TO_RETRY") else 2
    if a.cmd == "rollback":
        r = api.rollback(ctx, a.txid); _p({"status": r["status"], "undone": len(r["undone"])}, j); return 0
    if a.cmd == "uninstall":
        if not a.yes and input(f"Uninstall level '{a.level}' from {root}? [y/N]: ").strip().lower() not in ("y", "yes"):
            print("cancelled"); return 1
        r = api.uninstall(ctx, a.level, remove_docker=not a.keep_docker, projects=a.projects, force=a.force)
        if r.get("status") == "BLOCKED":
            return _blocked(r, j)
        _p({"report": r["report_path"], **r["residue"]["counts"],
            "CLEAN_UNINSTALL": "PASS" if r["residue"]["clean"] else "FAIL",
            "self_removal": r.get("self_removal")}, j)
        return 0 if r["residue"]["clean"] else 2
    if a.cmd == "import-payload":
        r = api.import_payload(ctx, a.manifest, a.search)
        _p(r, j); return 0 if r["status"] == "OK" else 6
    if a.cmd == "update":
        if a.dry_run:
            d = api.store_delta(a.source, ctx.layout.Store)
            _p({"copy": len(d["copy"]), "reuse": len(d["reuse"]), "bytes_copy": human_bytes(d["bytes_copy"]),
                "bytes_reused": human_bytes(d["bytes_reused"])}, j); return 0
        d = api.update_store(ctx, a.source, allow_copy=getattr(a, 'allow_copy', False))
        _p({"copied": len(d["copy"]), "reused": len(d["reuse"]), "bytes_copy": d["bytes_copy_human"],
            "bytes_reused": d["bytes_reused_human"]}, j); return 0
    if a.cmd == "catalog":
        if a.export_csv:
            ctx.catalog.export_csv(a.export_csv); print(a.export_csv); return 0
        rows = ctx.catalog.search(a.query, status=a.status, runtime=a.runtime)
        if j:
            _p(rows, True)
        else:
            for e in rows:
                print(f"{e['status']:<19} {e['runtime']:<9} {e['block_id']:<44} {e['name']}")
            print(f"{len(rows)}/{len(ctx.catalog)} entries; counts={ctx.catalog.counts()}")
        return 0
    if a.cmd == "import-image":
        an = api.analyse_image(ctx, a.path)
        if a.register:
            rec = api.register_image(ctx, an, a.block or an["suggested_block"], a.allow_unverified)
            an["registered"] = rec
        _p(an, j); return 0
    if a.cmd == "tools":
        rows = api.tool_registry(ctx.platform)
        if j:
            _p(rows, True)
        else:
            for r in rows:
                print(f"{'OK ' if r['present'] else '-- '} {r['name']:<34} owner={r['owner']:<12} {r.get('version') or ''}")
        return 0
    if a.cmd == "packet-tracer":
        if a.import_installer:
            _p(api.packet_tracer_import(ctx, a.import_installer), j)
        _p(api.packet_tracer_status(ctx), j); return 0
    if a.cmd == "diagnostics":
        _p(api.diagnostics_zip(ctx, a.out), j); return 0
    if a.cmd == "inventory":
        _p(api.inventory(ctx), j); return 0
    if a.cmd == "demo":
        if a.action == "list":
            for d in api.demo_definitions():
                print(f"{d['id']:<20} {d['title_ru']}  needs={d['required_blocks']}")
            return 0
        st = ctx.state.load()
        base = (st.get("gns3") or {}).get("api_base")
        fn = {"create": lambda: api.demo_create(ctx, a.id, base), "check": lambda: api.demo_check(ctx, a.id),
              "remove": lambda: api.demo_remove(ctx, a.id)}[a.action]
        _p(fn(), j); return 0
    if a.cmd == "desktop":
        _p(api.register_desktop(ctx) if a.action == "register" else api.unregister_desktop(ctx), j); return 0
    if a.cmd == "gns3-config":
        _p(api.gns3_config_check(ctx) if a.action == "check" else api.gns3_config_restore(ctx), j); return 0
    if a.cmd == "gui-deps":
        r = api.gui_deps_check(ctx, a.gns3)
        if a.bundle:
            r["bundle"] = api.gui_libs_ensure(ctx)
        _p(r, j); return 0
    if a.cmd == "logs":
        p = ctx.layout.Logs / "operations.log"
        print(p.read_text() if p.exists() else "(no log)"); return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
