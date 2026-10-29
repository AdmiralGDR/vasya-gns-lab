#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Turn the per-image test CSV (tested-images.csv) into docker-images.json, then validate
(one archive per unique image, no .tar + .tar.zst duplicates, sha256/size of every archive).

  # next to the archives (they are checked: present, size, sha256, no strays):
  python3 scripts/import_docker_archives.py --csv tested-images.csv --index <dir>/index.json --dir <Images/docker>
  # archives not on this machine (metadata only; sizes/sha256 taken from the CSV):
  python3 scripts/import_docker_archives.py --csv ... --index ... --no-files --out src/vasya/data/docker-images.json

Read-only on the archives; writes only the manifest."""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from vasya.runtime import docker_images as di  # noqa: E402


def check(man):
    """Metadata issues that need no archive file."""
    bad, seen = [], {}
    for e in man["images"]:
        for k in ("refs", "archive", "archive_sha256", "image_id", "repo_digest", "archive_bytes"):
            if not e.get(k):
                bad.append(f"NO_{k.upper()} {e.get('archive')}")
        if not e["archive"].endswith(di.ARCHIVE_EXT):
            bad.append(f"NOT_AN_ARCHIVE {e['archive']}")
        k = (e.get("image_id") or "").split(":")[-1]
        if k in seen:
            bad.append(f"DUPLICATE_IMAGE {e['archive']} and {seen[k]}")
        seen[k] = e["archive"]
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--index", default=None, help="Images/docker/index.json of the archive set (archive names + image IDs)")
    ap.add_argument("--dir", default=None, help="archive dir (omit with --no-files)")
    ap.add_argument("--out", default=None); ap.add_argument("--no-hash", action="store_true")
    ap.add_argument("--no-files", action="store_true", help="archives are not on this machine")
    a = ap.parse_args()
    man = di.manifest_from_csv(a.csv, a.index)
    man["source"] = {"csv": Path(a.csv).name, "index": Path(a.index).name if a.index else None}
    bad = check(man)
    d = Path(a.dir) if a.dir else None
    if not a.no_files:
        if not d:
            sys.exit("--dir is required unless --no-files")
        for e in man["images"]:
            p = d / e["archive"]
            if not p.is_file():
                bad.append(f"MISSING {e['archive']}"); continue
            if e.get("archive_bytes") is not None and p.stat().st_size != e["archive_bytes"]:
                bad.append(f"SIZE {e['archive']}")
            if not a.no_hash and di.sha256_file(p) != e["archive_sha256"]:
                bad.append(f"SHA256 {e['archive']}")
            e.setdefault("archive_bytes", p.stat().st_size)
    out = Path(a.out) if a.out else d / di.MANIFEST
    out.write_text(json.dumps(man, indent=1) + "\n")
    issues = bad + (di.validate_dir(d) if (d and not a.no_files and out.parent == d) else [])
    print(json.dumps({"images": len(man["images"]), "refs": sum(len(e["refs"]) for e in man["images"]),
                      "blocks": sum(len(e.get("blocks", [])) for e in man["images"]),
                      "archive_bytes": sum(e.get("archive_bytes", 0) for e in man["images"]),
                      "manifest": str(out), "issues": issues}, indent=1))
    sys.exit(1 if issues else 0)


if __name__ == "__main__":
    main()
