# SPDX-License-Identifier: GPL-3.0-or-later
"""Undo WAL-recorded resources (used by cancel, crash recovery, rollback, uninstall)."""
import os
import shutil, subprocess
from pathlib import Path
from ..core.util import sha256_file
from ..core import txn as txnmod
from ..gns3.client import GNS3Client, GNS3Error
from ..runtime import managed_server as ms
from ..desktop import integration as desk
from .apply import docker_cmd, OWNER_LABEL, OWNER_VALUE

ORDER = {"template": 0, "desktop_file": 1, "file": 2, "docker_labeled_image": 3, "docker_image": 4,
         "managed_gns3": 5}


def owned_state_mismatch(p, r):
    """D6: a file is deleted only when (1) it is in a receipt — callers only pass
    receipt entries — and (2) it is still exactly what VASYA placed: size + sha256 match; inode is
    recorded too. Returns None when deletion is safe, else the reason to keep it."""
    if not r.get("sha256"):
        return "no checksum in the receipt; not deleting by name"
    st = os.lstat(p)
    if r.get("size") is not None and st.st_size != r["size"]:
        return f"size changed since VASYA created it ({r['size']} -> {st.st_size})"
    if sha256_file(p) != r["sha256"]:
        return "content changed since VASYA created it"
    # same bytes but another inode = the name was replaced by an identical copy: deleting it loses
    # nothing VASYA did not bring, so it is still removed (noted in the log by the caller's status)
    return None


def undo_resource(ctx, r, remove_docker=False):
    k = r.get("kind")
    if k == "file":
        part = Path(r.get("partial") or "")
        if r.get("partial") and part.exists():
            part.unlink()
        p = Path(r["path"])
        md5c = p.with_name(p.name + ".md5sum")  # cache file GNS3 writes next to images
        if not p.exists() and not p.is_symlink():
            if md5c.exists() and r.get("role") == "image":
                md5c.unlink()
            return "ABSENT", None
        if p.is_symlink() and not p.exists():
            p.unlink()
            return "REMOVED", "dangling link"
        why = owned_state_mismatch(p, r)
        if why:
            return ("KEPT_UNVERIFIED" if why.startswith("no checksum") else "KEPT_MODIFIED"), why
        p.unlink()   # removes only this name; other hardlinks (CAS store) keep the data
        if md5c.exists() and r.get("role") == "image":
            md5c.unlink()
        return "REMOVED", None
    if k == "template":
        cl = GNS3Client(r["api_base"])
        if cl.version() is None:
            return "UNREACHABLE", f"GNS3 API {r['api_base']} not reachable"
        tid = r.get("template_id")
        if not tid:
            t = cl.find_template(r["name"], r.get("template_type"))
            if t and (r.get("tag") or "") in (t.get("usage") or ""):
                tid = t["template_id"]
        if not tid:
            return "ABSENT", None
        return ("REMOVED" if cl.delete_template(tid) else "ABSENT"), None
    if k in ("docker_image", "docker_labeled_image"):
        if not remove_docker:
            return "KEPT_BY_CHOICE", "docker image retained (by user choice)"
        from ..runtime.docker_backend import receipt_cmd
        cmd = receipt_cmd(r, ctx.layout.root, docker_cmd)   # podman receipt -> VASYA podman only
        if not cmd:
            return "ABSENT", None
        if subprocess.run(cmd + ["image", "inspect", r["ref"]], capture_output=True).returncode != 0:
            return "ABSENT", None
        users = docker_foreign_users(cmd, r["ref"])
        if users:
            return "KEPT_IN_USE", f"used by non-VASYA containers: {', '.join(users[:5])}"
        if k == "docker_labeled_image":
            # VASYA containers (GNS3 nodes) of this image: only labelled ones, never others
            ids = subprocess.run(cmd + ["ps", "-aq", "--filter", f"ancestor={r['ref']}",
                                        "--filter", f"label={OWNER_LABEL}={OWNER_VALUE}"],
                                 capture_output=True, text=True).stdout.split()
            if ids:
                subprocess.run(cmd + ["rm", "-f"] + ids, capture_output=True)
        rr = subprocess.run(cmd + ["rmi", r["ref"]], capture_output=True, text=True)  # never -f, never prune
        if rr.returncode == 0:
            return "REMOVED", None
        return "FAILED", rr.stderr[-300:]
    if k == "remote_image":
        from ..gns3.remote_compute import manual_cleanup_hint
        return "KEPT_REMOTE", manual_cleanup_hint(r)
    if k == "desktop_file":
        return ("REMOVED" if desk.unregister(r["path"]) else "ABSENT"), None
    if k == "managed_gns3":
        ms.stop(ctx.layout)
        cfg = Path(r["config"])
        if cfg.exists():
            cfg.unlink()
        return "REMOVED", None
    return "UNKNOWN_KIND", k


def rollback_txids(ctx, txids, oplog, by_txid, remove_docker=False):
    """Undo every committed+pending resource of the given transactions, newest first."""
    lay = ctx.layout
    results = []
    recs = [r for r in txnmod.all_receipts(lay) if r["txid"] in txids and not r["rolled_back"]]
    for rec in sorted(recs, key=lambda r: r["started_at"] or "", reverse=True):
        items = [dict(x, state="COMMITTED") for x in rec["committed"]] + \
                [dict(x, state="PENDING") for x in rec["pending"]]
        items.sort(key=lambda x: (ORDER.get(x.get("kind"), 9), x.get("op_id")))
        kept = 0
        for x in items:
            try:
                st, why = undo_resource(ctx, x, remove_docker=remove_docker)
            except Exception as e:
                st, why = "FAILED", str(e)[:300]
            if st in ("KEPT_MODIFIED", "KEPT_UNVERIFIED", "KEPT_BY_CHOICE", "KEPT_IN_USE", "FAILED", "UNREACHABLE",
                      "UNKNOWN_KIND"):
                kept += 1
            oplog.log("UNDO_" + (x.get("kind") or "?").upper(),
                      x.get("path") or x.get("name") or x.get("ref") or x.get("filename") or x.get("config"), st,
                      operation_id=x.get("op_id"), source_txid=rec["txid"], error=why,
                      before={"state": x["state"]})
            results.append({"txid": rec["txid"], "op_id": x.get("op_id"), "kind": x.get("kind"),
                            "what": x.get("path") or x.get("name") or x.get("ref") or x.get("filename"),
                            "state": x["state"], "result": st, "why": why})
        t = txnmod.open_tx(lay, rec["txid"])
        if kept == 0:
            if rec["status"] == txnmod.INCOMPLETE:
                t._append({"type": "END", "status": "ROLLED_BACK_AFTER_CRASH", "summary": {}})
            t.mark_rolled_back(by_txid)
        else:
            for x in results:
                if x["txid"] == rec["txid"] and x["result"] in ("REMOVED", "ABSENT"):
                    t.mark_released(x["op_id"], by_txid)
    return results


def docker_foreign_users(cmd, ref):
    """Containers using `ref` that do NOT carry the VASYA owner label."""
    out = subprocess.run(cmd + ["ps", "-a", "--filter", f"ancestor={ref}", "--format",
                                "{{.ID}} {{.Label \"%s\"}} {{.Names}}" % OWNER_LABEL],
                         capture_output=True, text=True).stdout
    return [ln.split()[-1] for ln in out.splitlines() if ln.strip() and OWNER_VALUE not in ln]
