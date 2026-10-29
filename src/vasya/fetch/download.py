# SPDX-License-Identifier: GPL-3.0-or-later
"""Verified downloads: nothing is used before its size and SHA-256 match the pin."""
import hashlib, os, urllib.request
from pathlib import Path

CHUNK = 1 << 20
OFFLINE_ENV = "VASYA_OFFLINE"          # "1": never touch the network (local sources only)


def offline():
    return os.environ.get(OFFLINE_ENV, "").strip().lower() in ("1", "yes", "true", "on")


def user_agent():
    from .. import VERSION
    return f"VASYA-GNS-LAB/{VERSION}"


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(CHUNK), b""):
            h.update(b)
    return h.hexdigest()


def cache_dir(layout):
    return Path(layout.root) / "Cache" / "downloads"


def _open(url, headers, timeout, opener):
    req = urllib.request.Request(url, headers={"User-Agent": user_agent(), **(headers or {})})
    return (opener or urllib.request.urlopen)(req, timeout=timeout)


def fetch(urls, dest, sha256, size=None, headers=None, timeout=60, opener=None, progress=None,
          max_bytes=None):
    """Download the first URL that yields a file with the expected SHA-256 into `dest`.
    sha256=None only checks the size; callers then verify the unpacked content instead.

    Returns {"status": "OK"|"FAIL"|"OFFLINE", "path", "url", "reused", "errors": [...]}.
    A partially written file is never left under the final name.
    """
    dest = Path(dest)
    if sha256 and dest.is_file() and (size is None or dest.stat().st_size == size) \
            and sha256_file(dest) == sha256:
        return {"status": "OK", "path": str(dest), "reused": True, "errors": []}
    if offline():
        return {"status": "OFFLINE", "path": None, "errors": [f"{OFFLINE_ENV} is set"]}
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".partial")
    errors = []
    limit = max_bytes or (size * 2 + CHUNK if size else None)
    for url in urls or []:
        h, n = hashlib.sha256(), 0
        try:
            with _open(url, headers, timeout, opener) as r, open(tmp, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0) if getattr(r, "headers", None) else 0
                for b in iter(lambda: r.read(CHUNK), b""):
                    n += len(b)
                    if limit and n > limit:
                        raise ValueError(f"more than {limit} bytes")
                    h.update(b)
                    f.write(b)
                    if progress:
                        progress(n, size or total)
        except Exception as e:  # network, HTTP or size errors: try the next URL
            errors.append(f"{url}: {type(e).__name__}: {e}")
            tmp.unlink(missing_ok=True)
            continue
        if size is not None and n != size:
            errors.append(f"{url}: size {n} != {size}")
        elif sha256 and h.hexdigest() != sha256:
            errors.append(f"{url}: sha256 {h.hexdigest()} != {sha256}")
        else:
            os.replace(tmp, dest)
            return {"status": "OK", "path": str(dest), "url": url, "reused": False, "errors": errors}
        tmp.unlink(missing_ok=True)
    return {"status": "FAIL", "path": None, "errors": errors or ["no download URL"]}
