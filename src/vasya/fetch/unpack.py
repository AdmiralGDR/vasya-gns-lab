# SPDX-License-Identifier: GPL-3.0-or-later
"""Decompression and Debian package member extraction, without root and without dpkg."""
import bz2, gzip, io, lzma, os, shutil, subprocess, tarfile, zipfile
from pathlib import Path

CHUNK = 1 << 20
STREAMS = {"gzip": gzip.open, "bzip2": bz2.open, "xz": lzma.open}


def decompress(src, dest, compression=None, member=None):
    """Write the uncompressed payload of `src` to `dest` (atomically). compression: None, gzip,
    bzip2, xz or zip. For zip, `member` names the file inside; default: the largest file."""
    src, dest = Path(src), Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".partial")
    try:
        if not compression:
            shutil.copyfile(src, tmp)
        elif compression == "zip":
            with zipfile.ZipFile(src) as z:
                infos = [i for i in z.infolist() if not i.is_dir()]
                pick = next((i for i in infos if member and (i.filename == member or
                                                             i.filename.rsplit("/", 1)[-1] == member)), None)
                pick = pick or max(infos, key=lambda i: i.file_size)
                with z.open(pick) as r, open(tmp, "wb") as w:
                    shutil.copyfileobj(r, w, CHUNK)
        elif compression in STREAMS:
            with STREAMS[compression](src, "rb") as r, open(tmp, "wb") as w:
                shutil.copyfileobj(r, w, CHUNK)
        else:
            raise ValueError(f"unsupported compression {compression!r}")
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink()
    return dest


def _ar_members(data):
    if not data.startswith(b"!<arch>\n"):
        raise ValueError("not a Debian package (ar archive)")
    pos = 8
    while pos + 60 <= len(data):
        hdr = data[pos:pos + 60]
        name = hdr[:16].decode().strip().rstrip("/")
        size = int(hdr[48:58].decode().strip())
        yield name, data[pos + 60:pos + 60 + size]
        pos += 60 + size + (size & 1)


def _tar_stream(name, blob):
    if name.endswith(".zst"):
        try:
            import zstandard
            return tarfile.open(fileobj=io.BytesIO(zstandard.ZstdDecompressor().decompress(
                blob, max_output_size=1 << 31)), mode="r:")
        except ImportError:
            z = shutil.which("zstd")
            if not z:
                raise RuntimeError("zstd is needed to unpack " + name)
            out = subprocess.run([z, "-dc"], input=blob, capture_output=True, check=True).stdout
            return tarfile.open(fileobj=io.BytesIO(out), mode="r:")
    return tarfile.open(fileobj=io.BytesIO(blob), mode="r:*")


def deb_extract(deb, member, dest, mode=0o755):
    """Extract one file (e.g. 'usr/bin/vpcs') from the data archive of a .deb into `dest`."""
    want = member.lstrip("./")
    for name, blob in _ar_members(Path(deb).read_bytes()):
        if not name.startswith("data.tar"):
            continue
        with _tar_stream(name, blob) as tf:
            for m in tf:
                if m.name.lstrip("./") == want and m.isfile():
                    dest = Path(dest)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    tmp = dest.with_name(dest.name + ".partial")
                    with tf.extractfile(m) as r, open(tmp, "wb") as w:
                        shutil.copyfileobj(r, w, CHUNK)
                    os.chmod(tmp, mode)
                    os.replace(tmp, dest)
                    return dest
    raise FileNotFoundError(f"{member} not found in {Path(deb).name}")
