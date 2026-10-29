# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolve the GNS3 target an operation acts on (existing vs VASYA-managed)."""
from ..gns3.discover import discover
from ..gns3.client import GNS3Client
from ..runtime import managed_server as ms

MODES = ("FULL", "INTEGRATION", "SELECTIVE")


def managed_target(ctx, port=None, start=True):
    lay = ctx.layout
    st = ctx.state.load()
    g = st.get("gns3") or {}
    port = port or (g.get("port") if g.get("managed") else None) or ms.free_port()
    p = ms.paths(lay)
    exist = discover(ctx.platform)
    info = {"managed": True, "port": port, "api_base": f"http://127.0.0.1:{port}",
            "config": str(p["config"]), "images_path": str(p["images_path"]),
            "appliances_path": str(p["appliances_path"]), "projects_path": str(p["projects_path"]),
            "server_bin": g.get("server_bin") or exist.get("server_bin"), "api_ok": False,
            "version": None}
    if start and info["server_bin"] and p["config"].exists():
        newp, moved = ms.relocate_if_busy(lay, port)
        if moved:
            info.update(port=newp, api_base=f"http://127.0.0.1:{newp}", port_moved_from=moved)
            port = newp
            if g.get("managed"):
                with ctx.state.edit() as s2:
                    s2["gns3"].update(port=newp, api_base=info["api_base"])
        try:
            from ..runtime import docker_backend as dbk
            senv = dbk.prepare_server_env(ctx)   # {} unless podman active + socket up
            ms.start(lay, info["server_bin"], port, extra_env=senv)
        except Exception as e:
            info["error"] = str(e)
    v = GNS3Client(info["api_base"]).version()
    info.update(api_ok=bool(v), version=v)
    return info


def resolve_target(ctx, mode=None, explicit=None, start=True):
    st = ctx.state.load()
    g = st.get("gns3") or {}
    mode = mode or st.get("mode")
    if explicit:
        info = discover(ctx.platform, {k: v for k, v in explicit.items() if k != "compute_id"})
        info["managed"] = False
        return _with_compute(ctx, info, explicit.get("compute_id") or "auto")
    if mode == "FULL" or g.get("managed"):
        return managed_target(ctx, start=start)
    if g.get("api_base") and not g.get("managed"):
        info = discover(ctx.platform, {k: g.get(k) for k in
                                       ("api_base", "images_path", "appliances_path", "config")})
    else:
        info = discover(ctx.platform)
    info["managed"] = False
    return _with_compute(ctx, info, g.get("compute_id") or "auto")


def _with_compute(ctx, info, requested):
    """Remote compute (GNS3 VM): images are uploaded via the API, never placed locally."""
    from ..gns3 import remote_compute as rc
    cid = "local"
    if info.get("api_ok"):
        cid = rc.pick(ctx.platform.name, GNS3Client(info["api_base"], info.get("user"),
                                                     info.get("password")), requested)
    elif requested not in ("auto", "local", None):
        cid = requested
    info["compute_id"] = cid
    if cid != "local":
        info["images_path"] = None
    return info
