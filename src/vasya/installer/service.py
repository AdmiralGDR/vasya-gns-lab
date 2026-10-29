# SPDX-License-Identifier: GPL-3.0-or-later
"""Installer service: dry-run / install / resume / repair (idempotent, transactional)."""
import os
from ..core import txn as txnmod
from ..core.state import root_lock
from ..core.util import utc_now, write_json, sha256_file
from .plan import build_plan
from .apply import Applier, Cancelled
from .rollback import rollback_txids, undo_resource
from .target import resolve_target


def dry_run(ctx, mode="INTEGRATION", block_ids=None, explicit_target=None, desktop=False,
            allow_copy=False):
    target = resolve_target(ctx, mode, explicit_target, start=False) if mode != "FULL" else \
        _full_target_preview(ctx)
    return build_plan(ctx, target, block_ids, mode, desktop=desktop, allow_copy=allow_copy)


def _full_target_preview(ctx):
    from .target import managed_target
    return managed_target(ctx, start=False)


def _summ(results):
    s = {}
    for r in results:
        s[r["result"]] = s.get(r["result"], 0) + 1
    return s


def preflight(ctx, mode="INTEGRATION", block_ids=None, explicit_target=None, allow_copy=False):
    """Checks that must pass BEFORE anything is written. Returns None or a BLOCKED
    result (nothing changed) with a human-readable error and recovery action."""
    from ..errors import explain
    lay = ctx.layout
    if ctx.platform.needs_admin_for(lay.root):
        return _blocked("NO_ADMIN", f"{lay.root} is not writable by this user")
    managed = mode == "FULL" or (ctx.state.load().get("gns3") or {}).get("managed")
    if explicit_target or not managed:
        tgt = resolve_target(ctx, mode, explicit_target, start=False)
        if not tgt.get("api_ok"):
            return _blocked("GNS3_UNREACHABLE", f"GNS3 API not reachable at {tgt.get('api_base')}")
    plan = dry_run(ctx, mode, block_ids, explicit_target, allow_copy=allow_copy)
    pv = plan["preview"]
    if not pv["space_ok"]:
        return _blocked("LOW_DISK", f"need {pv['space_needed_human']}, free {pv['free_human']}",
                        need=pv["space_needed"], free=pv["free_bytes"])
    return None


def _blocked(code, detail, **kw):
    from ..errors import explain
    return {"status": "BLOCKED", "code": code, "error": explain(code, "en", detail),
            "error_ru": explain(code, "ru", detail), "changed": False, **kw}


def install(ctx, mode="INTEGRATION", block_ids=None, explicit_target=None, pull_docker=True,
            cancel=None, progress=None, desktop=False, kind="install", allow_copy=False,
            check=True, fetch=True):
    if check and kind == "install":
        if txnmod.incomplete(ctx.layout) if ctx.layout.txn_dir.exists() else False:
            return _blocked("INTERRUPTED", "an earlier operation did not finish; resume or roll back first")
        b = preflight(ctx, mode, block_ids, explicit_target, allow_copy)
        if b:
            return b
    lay = ctx.layout.ensure()
    with root_lock(lay):
        with ctx.state.edit() as st:
            st["mode"] = st.get("mode") or mode
            st["payload_root"] = str(ctx.payload_root)
            st["allow_copy"] = bool(allow_copy)
            if explicit_target and not st.get("gns3"):
                st["gns3"] = dict(explicit_target, managed=False)
        target = resolve_target(ctx, mode, explicit_target)
        if not target.get("managed"):
            from .gns3_config_guard import backup_config
            backup_config(ctx, target)
        fetched = None
        if fetch and kind == "install":
            from ..fetch.prepare import prepare
            fetched = prepare(ctx, block_ids)
        plan = build_plan(ctx, target, block_ids, mode, desktop=desktop, allow_copy=allow_copy)
        write_json(lay.State / "plans" / f"{plan['plan_id']}.json", plan)
        t = txnmod.Transaction(lay, kind, meta={"plan_id": plan["plan_id"], "mode": mode,
                                                 "blocks": plan["block_ids"]})
        log = ctx.oplog(t.txid)
        log.log("BEGIN_" + kind.upper(), lay.root, "OK", operation_id="0000",
                after={"plan_id": plan["plan_id"], "mode": mode})
        ap = Applier(ctx, plan, t, log, pull_docker=pull_docker, cancel=cancel, progress=progress)
        try:
            results = ap.run()
        except Cancelled:
            undone = rollback_txids(ctx, {t.txid}, log, by_txid=t.txid + "-cancel")
            t.end("CANCELLED_ROLLED_BACK", {"undone": len(undone)})
            _record(ctx, plan, [], t.txid, "CANCELLED")
            return {"status": "CANCELLED", "txid": t.txid, "undone": undone, "plan": plan}
        fails = [r for r in results if r["result"] == "FAIL"]
        status = "OK" if not fails else "PARTIAL"
        t.end(status, _summ(results))
        if not ctx.state.load().get("gns3") and not target.get("managed"):
            with ctx.state.edit() as st:
                st["gns3"] = {k: target.get(k) for k in ("api_base", "images_path",
                              "appliances_path", "config", "version")} | {"managed": False}
        _record(ctx, plan, results, t.txid, status)
        from .payload_adopt import adopt
        ok_blocks = [b for b in plan["block_ids"]
                     if b not in {r.get("block_id") for r in fails}]
        try:
            adopted = adopt(ctx, ok_blocks, allow_copy=allow_copy, log=log)
        except Exception as e:  # never fail an install because of this
            adopted = {"adopted": False, "reason": str(e)}
        return {"status": status, "txid": t.txid, "results": results, "failed": fails,
                "blocked": [r for r in results if r["result"] == "BLOCKED"],
                "plan": plan, "payload": adopted, "fetch": fetched}


def _record(ctx, plan, results, txid, status):
    failed_blocks = {r["block_id"] for r in results if r["result"] in ("FAIL", "BLOCKED") and r.get("block_id")}
    with ctx.state.edit() as st:
        for bid in plan["block_ids"]:
            c = st["components"].setdefault(bid, {})
            if status == "CANCELLED":
                continue
            c["installed"] = bid not in failed_blocks
            c["txid"] = txid
            c["installed_at"] = utc_now()
            c["error"] = next((r["error"] for r in results if r.get("block_id") == bid
                               and r["result"] in ("FAIL", "BLOCKED")), None)
            c["blocked"] = any(r.get("block_id") == bid and r["result"] == "BLOCKED" for r in results)
        st["last_operation"] = {"kind": "install", "txid": txid, "status": status, "at": utc_now()}


def recover(ctx, oplog=None):
    """Clean up after a crash: undo PENDING (uncommitted) work of incomplete txns.
    Committed resources stay owned by their txn (so rollback/uninstall still sees them)."""
    lay = ctx.layout
    out = []
    for rec in txnmod.incomplete(lay):
        log = oplog or ctx.oplog(rec["txid"])
        for x in rec["pending"]:
            st, why = undo_resource(ctx, x)
            log.log("RECOVER_PENDING", x.get("path") or x.get("name"), st,
                    operation_id=x["op_id"], source_txid=rec["txid"], error=why)
            out.append({"txid": rec["txid"], "op_id": x["op_id"], "result": st})
            t = txnmod.open_tx(lay, rec["txid"])
            t.abort_op(x["op_id"], f"recovered after crash: {st}")
        t = txnmod.open_tx(lay, rec["txid"])
        t.end("CRASHED_RECOVERED", {"pending_cleaned": len(rec["pending"]),
                                    "committed_kept": len(rec["committed"])})
    return out


def resume(ctx, **kw):
    """Crash-resume: recover pending work, then re-run the same plan idempotently."""
    lay = ctx.layout
    inc = txnmod.incomplete(lay)
    if not inc:
        return {"status": "NOTHING_TO_RESUME"}
    meta = inc[-1].get("meta") or {}
    with root_lock(lay):
        rec = recover(ctx)
    r = install(ctx, mode=meta.get("mode") or "INTEGRATION", block_ids=meta.get("blocks"),
                kind="resume", **kw)
    r["recovered"] = rec
    return r


def rollback(ctx, txid=None, remove_docker=False):
    lay = ctx.layout
    with root_lock(lay):
        recs = [r for r in txnmod.all_receipts(lay) if not r["rolled_back"]]
        ids = {txid} if txid else {r["txid"] for r in recs}
        by = f"tx-rollback-{utc_now()}"
        res = rollback_txids(ctx, ids, ctx.oplog(by), by, remove_docker=remove_docker)
        with ctx.state.edit() as st:
            for c in st["components"].values():
                if txid is None or c.get("txid") == txid:
                    c["installed"] = False
                    c["runtime_verified"] = None
            st["last_operation"] = {"kind": "rollback", "status": "OK", "at": utc_now()}
        return {"status": "OK", "undone": res}


def retry_failed(ctx, progress=None):
    """Re-run only components whose last attempt failed (e.g. Docker pull without Internet)."""
    st = ctx.state.load()
    failed = sorted(b for b, c in st["components"].items() if c.get("error") and not c.get("installed"))
    if not failed:
        return {"status": "NOTHING_TO_RETRY", "retried": []}
    r = install(ctx, mode=st.get("mode") or "INTEGRATION", block_ids=failed, kind="retry",
                progress=progress, allow_copy=bool(st.get("allow_copy")))
    r["retried"] = failed
    return r


def repair(ctx, progress=None, force=False):
    """Verify, quarantine damaged VASYA-owned files, then re-run install idempotently."""
    from ..verifier import static_verify
    from ..runtime.busy import busy_nodes
    lay = ctx.layout
    if not force:
        busy = busy_nodes(ctx)
        if busy:
            return dict(_blocked("BUSY_VM", ", ".join(n["name"] for n in busy)), busy=busy)
    v = static_verify(ctx)
    damaged = [x for x in v["checks"] if x["status"] == "FAIL"]
    with root_lock(lay):
        q = lay.Cache / "quarantine"
        owned = {x["path"]: x for x in txnmod.owned_resources(lay) if x.get("kind") == "file"}
        moved = []
        for d in damaged:
            p = d.get("path")
            if p and p in owned and os.path.exists(p) and owned[p].get("sha256") and \
                    sha256_file(p) != owned[p]["sha256"]:
                q.mkdir(parents=True, exist_ok=True)
                dst = q / (os.path.basename(p) + ".damaged")
                os.replace(p, dst)
                moved.append({"path": p, "quarantined": str(dst)})
                txnmod.open_tx(lay, owned[p]["txid"]).mark_released(owned[p]["op_id"], "repair")
    blocks = sorted({b for b, c in ctx.state.load()["components"].items()
                     if c.get("installed") or c.get("error")}) or None
    st = ctx.state.load()
    r = install(ctx, mode=st.get("mode") or "INTEGRATION", block_ids=blocks, kind="repair",
                progress=progress, desktop=False, allow_copy=bool(st.get("allow_copy")))
    for m in moved:  # damaged copies are not needed once the good file is back
        try:
            os.unlink(m["quarantined"])
        except OSError:
            pass
    after = static_verify(ctx)
    r.update(damaged_before=len(damaged), quarantined=moved,
             failed_after=sum(1 for x in after["checks"] if x["status"] == "FAIL"))
    r["status"] = "OK" if r["failed_after"] == 0 and r["status"] == "OK" else "PARTIAL"
    with ctx.state.edit() as s:
        s["last_operation"] = {"kind": "repair", "status": r["status"], "at": utc_now()}
    return r
