# SPDX-License-Identifier: GPL-3.0-or-later
"""GNS3 VM / remote-compute backend (used on Windows, where QEMU and Docker run
inside the GNS3 VM, not on the host).

Images are uploaded through the controller (POST /v2/computes/<id>/<emulator>/images/<file>,
the same call the GNS3 GUI uses), verified by the md5 the compute reports, and
templates are created with compute_id=<id>. GNS3 2.2 has no API to delete an image
from a compute, so uninstall cannot remove uploaded images; they are listed as a
manual step (exact file names + the in-VM path) instead of being silently left.
"""
import hashlib, http.client, json, urllib.parse
from pathlib import Path
from .client import GNS3Client, GNS3Error

VM_IMAGE_DIRS = {"qemu": "/opt/gns3/images/QEMU", "dynamips": "/opt/gns3/images/IOS"}
UPLOAD_EMULATORS = ("qemu", "dynamips")


class ComputeError(RuntimeError):
    pass


def computes(client):
    try:
        return client.get("/v2/computes") or []
    except (GNS3Error, OSError):
        return []


def pick(platform_name, client, requested="auto"):
    """'local' | '<compute_id>'. auto: on Windows prefer the connected GNS3 VM ('vm')."""
    if requested in (None, "", "local"):
        return "local"
    cs = {c.get("compute_id"): c for c in computes(client)}
    if requested == "auto":
        vm = cs.get("vm")
        return "vm" if platform_name == "windows" and vm and vm.get("connected") else "local"
    c = cs.get(requested)
    if not c:
        raise ComputeError(f"GNS3 compute '{requested}' is not registered on {client.base} "
                           f"(known: {', '.join(sorted(k for k in cs if k)) or 'none'})")
    if not c.get("connected"):
        raise ComputeError(f"GNS3 compute '{requested}' is registered but not connected — start the GNS3 VM")
    return requested


def list_images(client, cid, emulator):
    try:
        return {i["filename"]: i for i in client.get(f"/v2/computes/{cid}/{emulator}/images") or []
                if i.get("filename")}
    except GNS3Error:
        return {}


def md5_cached(path, sha256, cache_file):
    cache_file = Path(cache_file)
    try:
        cache = json.loads(cache_file.read_text())
    except (OSError, ValueError):
        cache = {}
    if sha256 and sha256 in cache:
        return cache[sha256]
    h = hashlib.md5()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 22), b""):
            h.update(c)
    cache[sha256 or str(path)] = h.hexdigest()
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache))
    except OSError:
        pass
    return h.hexdigest()


def classify(remote, filename, size, md5_fn):
    """NEW | IDENTICAL | CONFLICT for an image against the compute's listing."""
    r = remote.get(filename)
    if not r:
        return "NEW"
    if r.get("filesize") not in (None, size):
        return "CONFLICT"
    return "IDENTICAL" if r.get("md5sum") == md5_fn() else "CONFLICT"


def upload(client, cid, emulator, filename, path, progress=None, timeout=3600):
    """Stream a file to the compute via the controller; returns the md5 we sent."""
    u = urllib.parse.urlsplit(client.base)
    conn_cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
    conn = conn_cls(u.hostname, u.port or (443 if u.scheme == "https" else 80), timeout=timeout)
    size = Path(path).stat().st_size
    url = f"{u.path.rstrip('/')}/v2/computes/{cid}/{emulator}/images/{urllib.parse.quote(filename)}"
    h, sent = hashlib.md5(), 0
    try:
        conn.putrequest("POST", url)
        conn.putheader("Content-Type", "application/octet-stream")
        conn.putheader("Content-Length", str(size))
        if client.auth:
            conn.putheader("Authorization", client.auth)
        conn.endheaders()
        with open(path, "rb") as f:
            for c in iter(lambda: f.read(1 << 20), b""):
                conn.send(c); h.update(c); sent += len(c)
                if progress:
                    progress(sent, size)
        r = conn.getresponse()
        body = r.read().decode("utf-8", "replace")
        if r.status >= 300:
            raise GNS3Error(r.status, body)
    finally:
        conn.close()
    return h.hexdigest()


def verify_uploaded(client, cid, emulator, filename, md5):
    got = list_images(client, cid, emulator).get(filename)
    if not got:
        why = (" — GNS3 lists only valid IOS images (32-bit big-endian ELF); is this really a "
               "Cisco IOS image?") if emulator == "dynamips" else ""
        raise ComputeError(f"{filename} not listed on compute {cid} after upload{why}")
    if got.get("md5sum") and got["md5sum"] != md5:
        raise ComputeError(f"{filename}: md5 on compute {got['md5sum']} != sent {md5}")
    return got


def manual_cleanup_hint(r):
    d = VM_IMAGE_DIRS.get(r.get("emulator"), "/opt/gns3/images")
    return (f"GNS3 2.2 cannot delete images remotely: remove {d}/{r.get('filename')} inside "
            f"compute '{r.get('compute_id')}' (GNS3 VM console → Shell) if you no longer need it")
