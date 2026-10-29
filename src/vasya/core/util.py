# SPDX-License-Identifier: GPL-3.0-or-later
"""Small shared helpers (no product logic)."""
import hashlib, json, os, shutil, uuid
from datetime import datetime, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id(prefix=""):
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def sha256_file(path, bufsize=4 * 1024 * 1024, progress=None):
    h = hashlib.sha256()
    done = 0
    with open(path, "rb") as f:
        while True:
            b = f.read(bufsize)
            if not b:
                break
            h.update(b)
            done += len(b)
            if progress:
                progress(done)
    return h.hexdigest()


def hashes_file(path, bufsize=4 * 1024 * 1024):
    """Return (sha256, md5, size) in one pass."""
    s, m, n = hashlib.sha256(), hashlib.md5(), 0
    with open(path, "rb") as f:
        while True:
            b = f.read(bufsize)
            if not b:
                break
            s.update(b); m.update(b); n += len(b)
    return s.hexdigest(), m.hexdigest(), n


def human_bytes(n):
    n = float(n or 0)
    for u in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or u == "TiB":
            return f"{int(n)} B" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


def load_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, obj):
    """Atomic JSON write (tmp + fsync + rename) so a crash never leaves half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def free_disk_bytes(path):
    fake = os.environ.get("VASYA_TEST_FREE_BYTES")  # test fault injection (LOW_DISK)
    if fake:
        return int(fake)
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(p).free


def which(cmd):
    return shutil.which(cmd)
