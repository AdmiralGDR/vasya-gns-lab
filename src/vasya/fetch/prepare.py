# SPDX-License-Identifier: GPL-3.0-or-later
"""Everything an installation needs from the network, fetched before the plan is built."""
import subprocess
from . import images as fimages


def prepare(ctx, block_ids=None, tools=True, images=True, use_private=True, run=subprocess.run,
            opener=None, log=None, docker=False):
    """Fetch images (public, then private) and, on Linux, the helper programs. Never raises:
    every problem ends up in the returned report and the plan skips what is missing."""
    rep = {"tools": {}, "images": None}
    if images:
        try:
            rep["images"] = fimages.ensure(ctx, block_ids, use_private=use_private, opener=opener,
                                           run=run, log=log)
        except Exception as e:      # a fetch problem must never stop an installation
            rep["images"] = {"error": f"{type(e).__name__}: {e}"}
    if tools and ctx.platform.name == "linux":
        from ..runtime import gui_deps
        sel = [b for b in ctx.blocks() if block_ids is None or b["block_id"] in block_ids]
        want = ["ubridge", "vpcs"] + (["dynamips"] if any(b.get("runtime") == "dynamips" for b in sel) else [])
        for t in want:
            try:
                rep["tools"][t] = gui_deps.ensure_tool(ctx, t)
            except Exception as e:
                rep["tools"][t] = {"status": "FAIL", "reason": f"{type(e).__name__}: {e}"}
        gui_deps.export_tools(ctx)
    if docker:
        rep["docker"] = _docker(ctx, block_ids)
    return rep


def _docker(ctx, block_ids):
    """Pinned Docker images for the selected blocks (rootless podman backend only)."""
    from ..runtime import docker_backend as dbk, docker_images as di
    out = {}
    try:
        if dbk.unavailable_reason(ctx):
            return {"status": "SKIPPED", "reason": dbk.unavailable_reason(ctx)}
        cmd, env = dbk.engine_cmd(ctx)
        if not cmd:
            return {"status": "SKIPPED", "reason": "shared Docker daemon: images are pulled during install"}
        for b in ctx.blocks():
            if (block_ids is None or b["block_id"] in block_ids) and b.get("docker_image"):
                ref = b["docker_image"]
                if ref not in out:
                    out[ref] = di.restore(ctx, ref, cmd, env=env)
    except Exception as e:
        return {"status": "FAIL", "reason": f"{type(e).__name__}: {e}", "images": out}
    return {"status": "OK", "images": out}
