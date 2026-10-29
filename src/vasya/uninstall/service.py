# SPDX-License-Identifier: GPL-3.0-or-later
"""Uninstaller: owned-resource inventory -> undo -> residue scan -> report.

Level 1 ("components"): remove everything VASYA put into GNS3 (templates,
images, appliances, demo/verify projects). VASYA app, payload store and Docker
images stay, so a reinstall is instant.
Level 2 ("full"): level 1 + Docker images VASYA pulled (optional), desktop
shortcut, managed GNS3 server, and the whole ONE-ROOT (self-removal helper).
"""
import os, shutil, tempfile, time
from pathlib import Path
from ..core import txn as txnmod
from ..core.state import root_lock
from ..core.util import utc_now, write_json
from ..gns3.client import GNS3Client
from ..installer.rollback import rollback_txids
from ..runtime import managed_server as ms
from . import residue, selfremove


def inventory(ctx):
    res = txnmod.owned_resources(ctx.layout)
    st = ctx.state.load()
    bases = {r["api_base"] for r in res if r.get("kind") == "template"}
    if (st.get("gns3") or {}).get("api_base"):
        bases.add(st["gns3"]["api_base"])
    from .projects import user_projects
    return {"resources": res, "api_bases": sorted(bases), "user_projects": user_projects(ctx.layout),
            "by_kind": {k: sum(1 for r in res if r.get("kind") == k)
                        for k in sorted({r.get("kind") for r in res})}}


def _cleanup_projects(api_bases, log):
    n = 0
    for b in api_bases:
        cl = GNS3Client(b)
        if cl.version() is None:
            continue
        for p in cl.projects():
            if p.get("name", "").startswith(("vasya-verify-", "vasya-demo-")):
                try:
                    cl.delete_project(p["project_id"])
                    log.log("DELETE_PROJECT", p["name"], "REMOVED")
                    n += 1
                except Exception as e:  # never abort an uninstall on one project
                    log.log("DELETE_PROJECT", p["name"], "FAIL", error=str(e)[:300])
    return n


def uninstall(ctx, level="components", remove_docker=True, keep_projects=True,
              report_dir=None, self_remove_timeout=60, projects=None, projects_dest=None,
              force=False, system_packages=None, pkg_run=None):
    """projects: export|keep|delete for user projects inside the VASYA folder
    (full level only); default derived from keep_projects for compatibility.
    system_packages: package names the user ticked in the full-uninstall wizard; only those
    still offered by installer.system_packages.offer() are removed (others are refused)."""
    from ..runtime.busy import busy_nodes
    from ..installer.service import _blocked
    lay = ctx.layout
    if not force:
        busy = busy_nodes(ctx)
        if busy:
            return dict(_blocked("BUSY_VM", ", ".join(n["name"] for n in busy)), busy=busy)
    projects = projects or ("keep" if keep_projects else "delete")
    started = utc_now()
    inv = inventory(ctx)
    by = f"tx-uninstall-{int(time.time())}"
    log = ctx.oplog(by)
    managed_projects_backup = None
    with root_lock(lay):
        _cleanup_projects(inv["api_bases"], log)
        kinds_l1 = {"file", "template", "remote_image"}
        recs = [r for r in txnmod.all_receipts(lay) if not r["rolled_back"]]
        if level == "components":
            # undo only GNS3-facing resources; keep desktop/docker/managed server
            results = []
            for rec in recs:
                sub = [x for x in rec["committed"] + rec["pending"] if x.get("kind") in kinds_l1]
                if not sub:
                    continue
                from ..installer.rollback import undo_resource
                t = txnmod.open_tx(lay, rec["txid"])
                for x in sub:
                    st, why = undo_resource(ctx, x)
                    log.log("UNDO_" + x["kind"].upper(), x.get("path") or x.get("name"), st,
                            operation_id=x.get("op_id"), source_txid=rec["txid"], error=why)
                    results.append({"result": st, "what": x.get("path") or x.get("name"),
                                    "kind": x["kind"], "why": why})
                    if st in ("REMOVED", "ABSENT"):
                        t.mark_released(x["op_id"], by)
            inv_scope = [r for r in inv["resources"] if r.get("kind") in kinds_l1]
        else:
            from ..runtime.docker_perms import fix_tree
            fx = fix_tree(lay.root)  # while VASYA's own images still exist
            if fx["result"] != "NOT_NEEDED":
                log.log("FIX_CONTAINER_FILE_OWNERSHIP", lay.root, fx["result"], error=fx.get("error"))
            from . import projects as uproj
            managed_projects_backup = uproj.handle(lay, projects, log, projects_dest)
            results = rollback_txids(ctx, {r["txid"] for r in recs}, log, by,
                                     remove_docker=remove_docker)
            ms.stop(lay)
            from ..runtime import docker_backend as dbk
            pt = dbk.teardown(ctx)   # VASYA podman service + rootless storage (no-op when never used)
            if pt["service"] != "ABSENT" or pt["storage"] != "ABSENT":
                log.log("PODMAN_TEARDOWN", str(dbk.podman_paths(ctx)["base"]), pt["storage"], after=pt)
            inv_scope = inv["resources"]
            from ..installer import system_packages as sp
            kw = {"run": pkg_run} if pkg_run else {}
            sys_pk = {"offer": sp.offer(ctx, **kw), "receipts": sp.load(ctx)}
            if system_packages:
                sys_pk["result"] = sp.remove(ctx, list(system_packages), **kw)
                log.log("REMOVE_SYSTEM_PACKAGES", ",".join(system_packages),
                        sys_pk["result"]["status"], after=sys_pk["result"])
        with ctx.state.edit() as s:
            for c in s["components"].values():
                c["installed"] = False
                c["runtime_verified"] = None
            s["last_operation"] = {"kind": f"uninstall-{level}", "at": utc_now()}
    kept = [f"{r['kind']} {r['what']} ({r['result']}: {r.get('why')})" for r in results
            if r["result"] not in ("REMOVED", "ABSENT", "KEPT_REMOTE")]
    manual_remote = [r.get("why") for r in results if r["result"] == "KEPT_REMOTE"]
    report = {"level": level, "root": str(lay.root), "started_at": started,
              "inventory_count": len(inv_scope), "removed": sum(r["result"] == "REMOVED" for r in results),
              "absent": sum(r["result"] == "ABSENT" for r in results), "kept": len(kept),
              "kept_items": kept, "preserved": ["GNS3 itself, user templates/images/projects, "
                                                "system packages (not installed by VASYA)"]}
    if managed_projects_backup:
        report["preserved"].append(f"your managed-lab projects saved to {managed_projects_backup}")
        report["projects_saved_to"] = str(managed_projects_backup)
    report["manual_remote_steps"] = manual_remote
    if level == "full":
        report["system_packages"] = locals().get("sys_pk")
    report["projects_choice"] = projects if level == "full" else "untouched"
    from ..installer.gns3_config_guard import check_config
    report["gns3_config"] = check_config(ctx)
    from ..core import side_effects
    report["external_side_effects"] = side_effects.report(lay)   # read before the root goes away
    rdir = Path(report_dir or (lay.Reports if level == "components" else tempfile.gettempdir()))
    rdir.mkdir(parents=True, exist_ok=True)
    rpath = rdir / f"VASYA-UNINSTALL-REPORT-{int(time.time())}.md"
    if level == "full":
        inside = selfremove.running_inside(lay.root)
        if inside:
            report["residue"] = residue.scan(inv_scope, inv["api_bases"], None, level, remove_docker,
                                             docker_root=lay.root)
            report["finished_at"] = utc_now()
            report["self_removal"] = "SCHEDULED"
            rpath.write_text(residue.render(report), encoding="utf-8")
            report["helper"] = selfremove.spawn(lay.root, rpath, self_remove_timeout)
            report["report_path"] = str(rpath)
            return report
        from ..runtime.docker_perms import remove_tree
        remove_tree(lay.root)
        report["self_removal"] = "IN_PROCESS"
    report["residue"] = residue.scan(inv_scope, inv["api_bases"], lay.root, level, remove_docker)
    report["finished_at"] = utc_now()
    rpath.write_text(residue.render(report), encoding="utf-8")
    report["report_path"] = str(rpath)
    if level != "full":
        write_json(lay.Reports / "last-uninstall.json", report)
        shutil.copyfile(rpath, lay.Reports / "UNINSTALL_REPORT.md")
    return report
