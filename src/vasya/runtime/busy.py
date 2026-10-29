# SPDX-License-Identifier: GPL-3.0-or-later
"""BUSY_VM detection: which running GNS3 nodes use VASYA templates or images.
Uninstall and repair refuse to touch them unless the user stops them (or forces)."""
from ..core import txn as txnmod
from ..gns3.client import GNS3Client


def _client(ctx):
    g = ctx.state.load().get("gns3") or {}
    if not g.get("api_base"):
        return None
    c = GNS3Client(g["api_base"], timeout=5)
    return c if c.version(timeout=1.0) else None


def busy_nodes(ctx, client=None):
    c = client or _client(ctx)
    if not c or not ctx.layout.txn_dir.exists():
        return []
    owned = txnmod.owned_resources(ctx.layout)
    names = {x.get("name") for x in owned if x.get("kind") == "template"}
    files = {str(x.get("path", "")).rsplit("/", 1)[-1] for x in owned if x.get("kind") == "file"}
    try:
        tmap = {t["template_id"]: t.get("name") for t in c.templates()}
        out = []
        for p in c.projects():
            if p.get("status") != "opened":
                continue
            for n in c.nodes(p["project_id"]):
                if n.get("status") != "started":
                    continue
                props = n.get("properties") or {}
                imgs = {str(props.get(k) or "").rsplit("/", 1)[-1] for k in ("hda_disk_image", "image", "path")}
                if tmap.get(n.get("template_id")) in names or (imgs & files - {""}):
                    out.append({"project_id": p["project_id"], "project": p.get("name"),
                                "node_id": n["node_id"], "name": n.get("name")})
        return out
    except Exception:
        return []


def stop_nodes(ctx, nodes, client=None):
    c = client or _client(ctx)
    done = []
    for n in nodes:
        try:
            c.node_action(n["project_id"], n["node_id"], "stop")
            done.append(n["name"])
        except Exception:
            pass
    return done
