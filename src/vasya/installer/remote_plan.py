# SPDX-License-Identifier: GPL-3.0-or-later
"""Plan steps for a remote compute (GNS3 VM): upload instead of placing files."""
from ..gns3.client import GNS3Client
from ..gns3 import remote_compute as rc
from ..core.util import human_bytes



class RemotePlanner:
    def __init__(self, ctx, target, add, present, conflicts):
        self.ctx, self.add, self.present, self.conflicts = ctx, add, present, conflicts
        self.cid = target["compute_id"]
        self.client = GNS3Client(target["api_base"]) if target.get("api_ok") else None
        self.listing = {}
        self.done = set()
        self.upload_bytes = 0
        self.vm_pulls = []
        self.md5_cache = ctx.layout.Cache / "md5-by-sha256.json"

    def _remote(self, emu):
        if emu not in self.listing:
            self.listing[emu] = rc.list_images(self.client, self.cid, emu) if self.client else {}
        return self.listing[emu]

    def image(self, b, im):
        emu = b["runtime"]
        if emu not in rc.UPLOAD_EMULATORS:
            return
        fn = im["logical_filename"]
        key = (emu, fn)
        if key in self.done:
            return
        self.done.add(key)
        src = self.ctx.payload.image_path(im["sha256"])
        cls = rc.classify(self._remote(emu), fn, im.get("size"),
                          lambda: rc.md5_cached(src, im["sha256"], self.md5_cache))
        common = dict(block_id=b["block_id"], source=str(src), sha256=im["sha256"], size=im.get("size"),
                      compute_id=self.cid, emulator=emu)
        if cls == "IDENTICAL":
            self.add("REUSE_REMOTE_IMAGE", target=f"{self.cid}:{emu}/{fn}", filename=fn, **common)
            self.present.append(f"image {fn} on compute {self.cid}")
            return
        name = fn
        if cls == "CONFLICT":
            from .plan import alt_name
            name = alt_name(im["sha256"], fn)
            self.conflicts.append({"block_id": b["block_id"], "path": f"{self.cid}:{emu}/{fn}",
                                   "installed_as": name})
        self.add("UPLOAD_IMAGE", target=f"{self.cid}:{emu}/{name}", filename=name, logical=fn, **common)
        self.upload_bytes += im.get("size") or 0

    def docker(self, b):
        # Docker runs inside the GNS3 VM: GNS3 pulls the image there on first node start.
        self.vm_pulls.append(b["docker_image"])

    def summary(self):
        return {"compute_id": self.cid, "upload_bytes": self.upload_bytes,
                "upload_human": human_bytes(self.upload_bytes),
                "docker_pulled_by_vm": sorted(set(self.vm_pulls)),
                "note": "Images are uploaded into the GNS3 VM through the GNS3 API; "
                        "Docker images are downloaded by the GNS3 VM on first start (Internet needed)."}
