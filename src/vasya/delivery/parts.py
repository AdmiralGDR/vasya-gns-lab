# SPDX-License-Identifier: GPL-3.0-or-later
"""Split / find / verify / join a large release archive delivered as parts.

Standalone (stdlib only): the release bootstrap script embeds this file verbatim,
so it must not import anything from the vasya package.

Layout written by split():
    NAME.part001 ... NAME.partNNN      raw byte slices of NAME
    NAME.parts.json                    {"archive", "size", "sha256", "parts": [{name,size,sha256}]}
The user never joins anything by hand: join_stream() finds the parts (also inside
Google-Drive "download folder" zips), verifies each one against the manifest
(cached, so a re-run after an interruption does not re-hash good parts) and
streams them, in order, into a consumer (zstd -d | tar -x) while hashing the whole.
"""
import hashlib, json, os, re, zipfile
from pathlib import Path

CHUNK = 1 << 22
PART_RE = re.compile(r"^(?P<base>.+)\.part(?P<n>\d{3,})$")
CACHE_NAME = ".vasya-parts-verified.json"


class PartsError(Exception):
    """code: PARTS_MISSING | PART_CORRUPT | PART_SIZE | ARCHIVE_CORRUPT | NO_MANIFEST"""
    def __init__(self, code, msg, detail=None):
        super().__init__(msg)
        self.code, self.detail = code, detail or {}


def _sha(path, progress=None):
    h, done = hashlib.sha256(), 0
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(CHUNK), b""):
            h.update(c); done += len(c)
            if progress:
                progress(done)
    return h.hexdigest()


def split(archive, out_dir, part_size, manifest_extra=None):
    archive = Path(archive)
    with open(archive, "rb") as f:
        return split_stream(f, archive.name, out_dir, part_size, manifest_extra)


def split_stream(f, archive_name, out_dir, part_size, manifest_extra=None):
    """Split a byte stream (e.g. `tar -cf -` stdout) straight into parts: the whole archive never
    exists on disk."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    whole, parts, n = hashlib.sha256(), [], 0
    if True:
        while True:
            n += 1
            name = f"{archive_name}.part{n:03d}"
            h, size = hashlib.sha256(), 0
            with open(out_dir / (name + ".tmp"), "wb") as o:
                while size < part_size:
                    c = f.read(min(CHUNK, part_size - size))
                    if not c:
                        break
                    o.write(c); h.update(c); whole.update(c); size += len(c)
            if size == 0:
                os.unlink(out_dir / (name + ".tmp"))
                break
            os.replace(out_dir / (name + ".tmp"), out_dir / name)
            parts.append({"name": name, "size": size, "sha256": h.hexdigest()})
    man = {"format": "vasya-parts/1", "archive": archive_name, "size": sum(p["size"] for p in parts),
           "sha256": whole.hexdigest(), "part_size": part_size, "parts": parts}
    man.update(manifest_extra or {})
    (out_dir / f"{archive_name}.parts.json").write_text(json.dumps(man, indent=1))
    return man


def unpack_drive_zips(dirs, archive_name, dest):
    """Google Drive packs a downloaded folder into one or more .zip files; pull our parts out."""
    got = []
    for d in dirs:
        for z in sorted(Path(d).glob("*.zip")):
            try:
                zf = zipfile.ZipFile(z)
            except (zipfile.BadZipFile, OSError):
                continue
            with zf:
                for info in zf.infolist():
                    base = Path(info.filename).name
                    if not (base.startswith(archive_name + ".part") or base == archive_name + ".parts.json"):
                        continue
                    out = Path(dest) / base
                    if out.exists() and out.stat().st_size == info.file_size:
                        continue
                    with zf.open(info) as src, open(str(out) + ".tmp", "wb") as o:
                        for c in iter(lambda: src.read(CHUNK), b""):
                            o.write(c)
                    os.replace(str(out) + ".tmp", out)
                    got.append(str(out))
    return got


def find_parts(manifest, dirs):
    """Map part name -> path (first dir that has it). Missing parts -> PartsError."""
    found, missing = {}, []
    for p in manifest["parts"]:
        for d in dirs:
            c = Path(d) / p["name"]
            if c.is_file():
                found[p["name"]] = c
                break
        else:
            missing.append(p["name"])
    if missing:
        raise PartsError("PARTS_MISSING", f"{len(missing)} of {len(manifest['parts'])} parts not found",
                         {"missing": missing, "searched": [str(d) for d in dirs]})
    return found


def _load_cache(d):
    try:
        return json.loads((Path(d) / CACHE_NAME).read_text())
    except (OSError, ValueError):
        return {}


def verify_parts(manifest, found, progress=None):
    """Check size + sha256 of every part. Good results are cached next to the part
    (keyed by size+mtime), so resuming after a failure only re-hashes changed parts."""
    bad, total = [], len(manifest["parts"])
    for i, p in enumerate(manifest["parts"], 1):
        path = found[p["name"]]
        st = path.stat()
        if st.st_size != p["size"]:
            bad.append({"name": p["name"], "problem": "size", "expected": p["size"], "actual": st.st_size})
            continue
        cache = _load_cache(path.parent)
        key = f"{p['name']}:{st.st_size}:{int(st.st_mtime)}"
        if cache.get(key) == p["sha256"]:
            if progress:
                progress(i, total, p["name"], "cached")
            continue
        got = _sha(path)
        if got != p["sha256"]:
            bad.append({"name": p["name"], "problem": "sha256", "expected": p["sha256"], "actual": got})
            if progress:
                progress(i, total, p["name"], "BAD")
            continue
        cache[key] = got
        try:
            (path.parent / CACHE_NAME).write_text(json.dumps(cache, indent=0))
        except OSError:
            pass
        if progress:
            progress(i, total, p["name"], "ok")
    if bad:
        raise PartsError("PART_CORRUPT", f"{len(bad)} part(s) damaged or incomplete: "
                         + ", ".join(b["name"] for b in bad), {"bad": bad})
    return True


def join_stream(manifest, found, sink, progress=None):
    """Write all parts in order into sink(bytes); verify the whole-archive sha256 at the end."""
    h, done = hashlib.sha256(), 0
    for p in manifest["parts"]:
        with open(found[p["name"]], "rb") as f:
            for c in iter(lambda: f.read(CHUNK), b""):
                h.update(c); sink(c); done += len(c)
                if progress:
                    progress(done, manifest["size"])
    if done != manifest["size"] or h.hexdigest() != manifest["sha256"]:
        raise PartsError("ARCHIVE_CORRUPT", "joined archive checksum mismatch",
                         {"expected": manifest["sha256"], "actual": h.hexdigest(), "bytes": done})
    return h.hexdigest()


def locate(archive_name, dirs):
    """Return ('whole', path) for a complete archive, or ('parts', manifest_path)."""
    for d in dirs:
        w = Path(d) / archive_name
        if w.is_file():
            return "whole", w
    for d in dirs:
        m = Path(d) / (archive_name + ".parts.json")
        if m.is_file():
            return "parts", m
    return None, None
