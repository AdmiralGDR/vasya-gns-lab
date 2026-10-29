# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared context: root layout, payload, platform, catalog, GNS3 target."""
import json, os
from pathlib import Path
from ..core.layout import Layout
from ..core.state import StateStore
from ..core.oplog import OpLog
from ..core.cas import Payload
from ..catalog.catalog import Catalog
from ..catalog import image_import
from .. import platform as plat


def payload_dir_for(layout, explicit=None):
    if explicit:
        return Path(explicit)
    env = os.environ.get("VASYA_PAYLOAD")
    if env:
        return Path(env)
    bundle = os.environ.get("VASYA_BUNDLE_DIR")  # running from an extracted bundle: full payload
    if bundle and (Path(bundle) / "Payload" / "manifests" / "pack.json").exists():
        return Path(bundle) / "Payload"
    st = StateStore(layout).load()
    if st.get("payload_root") and Path(st["payload_root"]).exists():
        return Path(st["payload_root"])
    return layout.Store


class Context:
    def __init__(self, root, payload=None, platform=None):
        self.layout = Layout(root)
        self.platform = platform or plat.current()
        self.state = StateStore(self.layout)
        self.payload_root = payload_dir_for(self.layout, payload)
        self.payload = Payload(self.payload_root, user_store=self.layout.user_store)
        self.user_images = image_import.load_registry(self.layout) if self.layout.root.exists() else {}
        self.catalog = Catalog(user_images=self.user_images)
        os.environ.setdefault("VASYA_ROOT_DOCKER_CONFIG", str(self.layout.Cache / "docker-cli"))
        from ..runtime.gui_deps import export_tools
        export_tools(self)

    def oplog(self, txid=None):
        self.layout.Logs.mkdir(parents=True, exist_ok=True)
        return OpLog(self.layout.Logs, txid)

    # ------------------------------------------------------------------
    def blocks(self):
        """READY payload blocks + blocks made installable by a registered user image."""
        from ..catalog.fixups import apply_block
        raw = list(self.payload.blocks)
        out = [apply_block(b, raw, self.appliance_json) for b in raw]
        have = {b["block_id"] for b in out}
        for bid, rec in self.user_images.items():
            if bid in have:
                continue
            b = user_block(self.catalog, bid, rec)
            if b:
                out.append(b)
                have.add(bid)
        # devices whose images come from the user's private source (fetch.private)
        if self.layout.root.exists():
            from ..fetch import private
            for b in private.blocks(self.layout, have=lambda s: self.payload.image_path(s).exists()):
                if b["block_id"] not in have:
                    out.append(b)
                    have.add(b["block_id"])
        return out

    def block(self, bid):
        return next((b for b in self.blocks() if b["block_id"] == bid), None)

    def ready_ids(self):
        return [b["block_id"] for b in self.blocks()]

    def appliance_json(self, block):
        p = block.get("_appliance_abs")
        if not p and block.get("template"):
            p = self.payload_root / block["template"]
        if p and Path(p).exists():
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        return None

    def appliance_path(self, block):
        p = block.get("_appliance_abs")
        if p:
            return Path(p)
        return self.payload_root / block["template"] if block.get("template") else None


def user_block(catalog, bid, rec):
    e = catalog.get(bid)
    app = catalog.appliance_file(bid)
    if not e or not app:
        return None
    with open(app, encoding="utf-8") as f:
        g = json.load(f)
    slot = "hda_disk_image"
    for v in g.get("versions") or []:
        for s, fn in (v.get("images") or {}).items():
            if fn == rec["logical_filename"]:
                slot = s
    rt = e["runtime"]
    return {"block_id": bid, "name": e["name"], "vendor": e["vendor"], "category": e["category"],
            "runtime": rt, "template": None, "_appliance_abs": str(app),
            "appliance_meta_ok": True, "user_image": True,
            "images": [{"logical_filename": rec["logical_filename"], "sha256": rec["sha256"],
                        "size": rec["size"], "disk_slot": slot}],
            "docker_image": None, "ram": e["resources"].get("ram_mb"),
            "architecture": e.get("architecture")}
