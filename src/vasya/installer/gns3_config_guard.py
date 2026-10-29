# SPDX-License-Identifier: GPL-3.0-or-later
"""Integration mode safety: VASYA never writes the user's GNS3 config.

Before the first integration install the existing gns3_server.conf/.ini is
backed up byte-for-byte into <root>/State/backups with its SHA-256. `check`
proves it is unchanged; `restore` puts the exact original bytes back.
"""
import shutil
from pathlib import Path
from ..core.util import sha256_file, utc_now


def backup_config(ctx, target):
    cfg = target.get("config")
    st = ctx.state.load()
    if not cfg or not Path(cfg).is_file() or (st.get("gns3_config_backup") or {}).get("path") == cfg:
        return st.get("gns3_config_backup")
    sha = sha256_file(cfg)
    bdir = ctx.layout.State / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    dst = bdir / f"{Path(cfg).name}.{sha[:12]}.orig"
    shutil.copy2(cfg, dst)
    rec = {"path": cfg, "sha256": sha, "backup": str(dst), "at": utc_now(),
           "size": Path(cfg).stat().st_size}
    with ctx.state.edit() as s:
        s["gns3_config_backup"] = rec
    ctx.oplog("config-guard").log("BACKUP_GNS3_CONFIG", cfg, "OK", actual_sha256=sha,
                                   after={"backup": str(dst)})
    return rec


def check_config(ctx):
    rec = ctx.state.load().get("gns3_config_backup")
    if not rec:
        return {"status": "NOT_APPLICABLE"}
    p = Path(rec["path"])
    now = sha256_file(p) if p.exists() else None
    return {"status": "UNCHANGED" if now == rec["sha256"] else "CHANGED", "path": rec["path"],
            "expected": rec["sha256"], "actual": now, "backup": rec["backup"]}


def restore_config(ctx):
    rec = ctx.state.load().get("gns3_config_backup")
    if not rec:
        return {"status": "NOT_APPLICABLE"}
    shutil.copy2(rec["backup"], rec["path"])
    ok = sha256_file(rec["path"]) == rec["sha256"]
    ctx.oplog("config-guard").log("RESTORE_GNS3_CONFIG", rec["path"], "OK" if ok else "FAIL")
    return {"status": "RESTORED_BYTE_IDENTICAL" if ok else "FAIL", "path": rec["path"]}
