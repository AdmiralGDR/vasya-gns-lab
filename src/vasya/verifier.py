# SPDX-License-Identifier: GPL-3.0-or-later
"""Verifier: static (files/templates/docker) and runtime (create/start/console/stop/delete)."""
import os, shutil, subprocess, time
from pathlib import Path
from .core.util import sha256_file, utc_now
from .core import txn as txnmod
from .gns3.client import GNS3Client, GNS3Error
from .gns3.discover import image_dir
from .installer.plan import alt_name
from .installer.target import resolve_target
from .installer.apply import docker_cmd
from .runtime import console
from .catalog.fixups import equivalent_empty_disk


def static_verify(ctx, block_ids=None):
    st = ctx.state.load()
    target = resolve_target(ctx, st.get("mode"), start=True)
    comps = st["components"]
    ids = block_ids or [b for b, c in comps.items() if c.get("installed")]
    cl = GNS3Client(target["api_base"]) if target.get("api_ok") else None
    tnames = {(t["name"], t.get("template_type")) for t in (cl.templates() if cl else [])}
    checks = []
    for bid in ids:
        b = ctx.block(bid)
        if not b:
            checks.append({"block_id": bid, "check": "manifest", "status": "FAIL",
                           "detail": "block not in payload"})
            continue
        for im in b.get("images") or []:
            d = image_dir(target["images_path"], b["runtime"])
            cands = [d / im["logical_filename"], d / alt_name(im["sha256"], im["logical_filename"])]
            ok = next((c for c in cands if c.exists() and c.stat().st_size == im.get("size", c.stat().st_size)
                       and sha256_file(c) == im["sha256"]), None)
            if not ok and cands[0].exists() and equivalent_empty_disk(cands[0], ctx.payload.image_path(im["sha256"])):
                ok = cands[0]   # GNS3's own blank disk of the same size (D3)
            exists = any(c.exists() for c in cands)
            checks.append({"block_id": bid, "check": "image", "path": str(cands[0]),
                           "status": "PASS" if ok else "FAIL",
                           "code": None if ok else ("IMAGE_CORRUPT" if exists else "IMAGE_MISSING"),
                           "detail": f"ok at {ok.name}" if ok else
                           ("checksum mismatch" if exists else "missing")})
        if cl is not None:
            ok = (b["name"], b["runtime"]) in tnames
            checks.append({"block_id": bid, "check": "template", "status": "PASS" if ok else "FAIL",
                           "detail": b["name"]})
        else:
            checks.append({"block_id": bid, "check": "template", "status": "NOT_TESTED",
                           "detail": "GNS3 API not reachable"})
        if b["runtime"] == "docker" and b.get("docker_image"):
            from .runtime import docker_backend as dbk
            pcmd, penv = dbk.engine_cmd(ctx)   # podman-rootless (default) or the shared daemon
            cmd = pcmd or docker_cmd()
            ok = bool(cmd) and subprocess.run(cmd + ["image", "inspect", b["docker_image"]], env=penv,
                                              capture_output=True).returncode == 0
            checks.append({"block_id": bid, "check": "docker_image",
                           "status": "PASS" if ok else "FAIL", "detail": b["docker_image"]})
    per = {}
    for c in checks:
        per.setdefault(c["block_id"], []).append(c["status"])
    with ctx.state.edit() as s:
        for bid, sts in per.items():
            c = s["components"].setdefault(bid, {})
            c["static_verified"] = "FAIL" if "FAIL" in sts else "PASS"
            c["static_verified_at"] = utc_now()
    fail = sum(1 for c in checks if c["status"] == "FAIL")
    return {"status": "PASS" if not fail else "FAIL", "checks": checks, "failed": fail,
            "blocks": len(ids), "target": target.get("api_base")}


def _wait_status(cl, pid, nid, want, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        n = cl.get(f"/v2/projects/{pid}/nodes/{nid}")
        if n.get("status") == want:
            return n
        time.sleep(1)
    return cl.get(f"/v2/projects/{pid}/nodes/{nid}")


def runtime_verify_block(ctx, cl, bid, settle=4):
    b = ctx.block(bid)
    out = {"block_id": bid, "runtime": b["runtime"], "steps": {}, "status": "FAIL"}
    t = cl.find_template(b["name"], b["runtime"])
    if not t:
        out["error"] = "template not registered"
        return out
    pname = f"vasya-verify-{bid}-{int(time.time())}"
    proj = cl.create_project(pname)
    pid = proj["project_id"]
    try:
        node = cl.node_from_template(pid, t["template_id"], 0, 0)
        out["steps"]["CREATE"] = "PASS"
        nid = node["node_id"]
        cl.node_action(pid, nid, "start", timeout=180)
        n = _wait_status(cl, pid, nid, "started", 90)
        out["steps"]["START"] = "PASS" if n.get("status") == "started" else "FAIL"
        time.sleep(settle)
        n = cl.get(f"/v2/projects/{pid}/nodes/{nid}")
        if n.get("status") != "started":
            out["steps"]["START"] = "FAIL"
            out["error"] = "node stopped right after start (emulator exited; see gns3server.log)"
        if n.get("console") and n.get("console_type") in ("telnet", "vnc", "http", "https"):
            pr = console.probe(n.get("console_host") or "127.0.0.1", n["console"],
                               want_bytes=n.get("console_type") == "telnet")
            out["steps"]["CONSOLE"] = "PASS" if pr["ok"] else "FAIL"
            out["console"] = {"type": n.get("console_type"), "port": n["console"], **pr}
        else:
            out["steps"]["CONSOLE"] = "NOT_APPLICABLE"
        cl.node_action(pid, nid, "stop", timeout=120)
        n = _wait_status(cl, pid, nid, "stopped", 60)
        out["steps"]["STOP"] = "PASS" if n.get("status") == "stopped" else "FAIL"
    except GNS3Error as e:
        out["error"] = str(e)[:400]
    finally:
        if "nid" in locals() and "STOP" not in out["steps"]:
            try:  # a clean stop lets GNS3 hand container files back to the user
                cl.node_action(pid, nid, "stop", timeout=60)
            except Exception:
                pass
        try:
            cl.delete_project(pid)
            out["steps"]["DELETE"] = "PASS"
        except Exception as e:
            out["steps"]["DELETE"] = "FAIL"
            out["error"] = (out.get("error") or "") + f" delete: {e}"
    req = ("CREATE", "START", "STOP", "DELETE")
    ok = all(out["steps"].get(k) == "PASS" for k in req) and out["steps"].get("CONSOLE") != "FAIL"
    out["status"] = "PASS" if ok else "FAIL"
    return out


def runtime_verify(ctx, block_ids=None, progress=None):
    st = ctx.state.load()
    target = resolve_target(ctx, st.get("mode"), start=True)
    if not target.get("api_ok"):
        return {"status": "NOT_TESTED", "reason": "GNS3 API not reachable", "results": []}
    cl = GNS3Client(target["api_base"], timeout=200)
    ids = block_ids or [b for b, c in st["components"].items() if c.get("installed")]
    res = []
    log = ctx.oplog("verify-" + utc_now())
    for i, bid in enumerate(ids, 1):
        r = runtime_verify_block(ctx, cl, bid)
        res.append(r)
        log.log("RUNTIME_VERIFY", bid, r["status"], after=r["steps"], error=r.get("error"))
        ctx.state.set_component(bid, runtime_verified=r["status"], runtime_verified_at=utc_now(),
                                error=r.get("error"))
        if progress:
            progress(i, len(ids), bid, r["status"])
    n = sum(r["status"] == "PASS" for r in res)
    return {"status": "PASS" if n == len(res) and res else ("FAIL" if res else "NOT_TESTED"),
            "passed": n, "total": len(res), "results": res}
