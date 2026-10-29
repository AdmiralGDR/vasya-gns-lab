# SPDX-License-Identifier: GPL-3.0-or-later
"""Component catalog: all 186 discovered blocks with honest availability status."""
import csv, json
from pathlib import Path
from ..core.util import load_json

DATA = Path(__file__).resolve().parent.parent / "data"
STATUSES = ("READY", "NEEDS_IMAGE", "NEEDS_DOWNLOAD", "NEEDS_REGISTRATION", "NEEDS_LICENSE",
            "OBSOLETE", "UNAVAILABLE")
STATUS_TEXT = {
    "READY": ("Готов: образ в комплекте", "Ready: image bundled"),
    "NEEDS_IMAGE": ("Нужен собственный образ пользователя", "Needs your own image"),
    "NEEDS_DOWNLOAD": ("Бесплатный образ, не включён (размер/лицензия)", "Free image, not bundled"),
    "NEEDS_REGISTRATION": ("Нужна регистрация у производителя", "Vendor registration required"),
    "NEEDS_LICENSE": ("Нужна лицензия / контракт производителя", "Vendor license required"),
    "OBSOLETE": ("Устарел: точный образ больше не публикуется", "Obsolete upstream image"),
    "UNAVAILABLE": ("Недоступен из доверенного источника", "No trusted source"),
}


class Catalog:
    def __init__(self, path=None, user_images=None):
        data = load_json(path or DATA / "catalog.json")
        self.entries = data["entries"]
        self.by_id = {e["block_id"]: e for e in self.entries}
        from ..runtime import docker_images as di
        for e in self.entries:       # docker pins: show the image that was archived and tested (== payload block)
            pin = e.get("docker_image") and di.pin_for_block(e["block_id"])
            if pin:
                e.update(docker_image=pin["refs"][0], docker_digest=pin.get("repo_digest"),
                         docker_image_id=pin.get("image_id"))
        self.user_images = user_images or {}
        for bid, rec in self.user_images.items():
            if bid in self.by_id and self.by_id[bid]["status"] != "READY":
                self.by_id[bid]["status_effective"] = "READY_USER_IMAGE"
                self.by_id[bid]["user_image"] = rec

    def __len__(self):
        return len(self.entries)

    def get(self, bid):
        return self.by_id.get(bid)

    def appliance_file(self, bid):
        p = DATA / "appliances" / f"{bid}.gns3a"
        return p if p.exists() else None

    def search(self, query="", status=None, category=None, runtime=None, vendor=None,
               installed=None, state=None):
        q = (query or "").strip().lower()
        comps = (state or {}).get("components", {})
        out = []
        for e in self.entries:
            st = e.get("status_effective") or e["status"]
            if status and st != status and e["status"] != status:
                continue
            if category and e["category"] != category:
                continue
            if runtime and e["runtime"] != runtime:
                continue
            if vendor and e["vendor"].lower() != vendor.lower():
                continue
            if installed is not None and bool(comps.get(e["block_id"], {}).get("installed")) != installed:
                continue
            if q and not any(q in (e.get(k) or "").lower() for k in
                             ("block_id", "name", "vendor", "product", "description", "category")):
                continue
            out.append(e)
        return out

    def counts(self):
        c = {s: 0 for s in STATUSES}
        for e in self.entries:
            c[e["status"]] = c.get(e["status"], 0) + 1
        c["TOTAL"] = len(self.entries)
        return c

    def categories(self):
        return sorted({e["category"] for e in self.entries})

    def runtimes(self):
        return sorted({e["runtime"] for e in self.entries})

    def export_csv(self, path):
        cols = ["block_id", "name", "vendor", "product", "version", "category", "runtime",
                "status", "purpose_en", "ram_mb", "cpus", "kvm", "required_images",
                "docker_image", "packaged", "packaged_bytes", "reason", "action_required"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for e in self.entries:
                r = e["resources"]
                w.writerow([e["block_id"], e["name"], e["vendor"], e["product"], e["version"],
                            e["category"], e["runtime"], e["status"], e["purpose_en"],
                            r.get("ram_mb"), r.get("cpus"), r.get("kvm"),
                            ";".join(i["filename"] or "" for i in e["required_images"]),
                            e.get("docker_image") or "", e["packaged"], e["packaged_bytes"],
                            e["reason"], e["action_required"]])
        return path
