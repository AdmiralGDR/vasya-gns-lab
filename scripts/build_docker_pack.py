#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the separate Docker image pack VASYA-GNS-LAB-<ver>-Docker-Images from tested image archives.

  python3 scripts/build_docker_pack.py --src DOCKER_ARCHIVES \
      --stage STAGE_DIR --out OUT_DIR/VASYA-GNS-LAB-1.1.0-Docker-Images

* every archive is checked against the built-in pins (size + sha256) and the sidecars (.sha256, index.json)
  against packaging/docker-pack/ (the copies Setup.sh is built with);
* the stage holds HARDLINKS to --src (each archive is stored once; a cross-device stage is refused);
* `tar -cf -` (uncompressed: the archives are zstd already) is streamed straight into 95 MiB parts —
  no whole .tar on disk; writes <name>.tar.parts.json and <name>.SHA256SUMS;
* refuses to start if free space after the build would drop below the 12 GiB floor."""
import argparse, hashlib, json, os, shutil, subprocess, sys, time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from vasya import VERSION  # noqa: E402
from vasya.delivery import parts as P  # noqa: E402
from vasya.delivery.bootstrap import docker_pack_spec  # noqa: E402
from vasya.runtime import docker_images as di  # noqa: E402

FLOOR = 12 * 1024 ** 3
SIDECARS = REPO / "packaging" / "docker-pack"


def sidecars():
    return {p.name: p.read_bytes() for p in sorted(SIDECARS.iterdir()) if p.is_file()}


def spec():
    return docker_pack_spec(di.builtin_entries(), sidecars(), VERSION)


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 22), b""):
            h.update(c)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True); ap.add_argument("--stage", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--part-size", type=int, default=95 * 1024 * 1024)
    ap.add_argument("--no-hash", action="store_true", help="trust size only (tests)")
    a = ap.parse_args()
    assert a.part_size < 100 * 1000 * 1000
    D = spec()
    src, out = Path(a.src), Path(a.out)
    bad = []
    for n, f in D["files"].items():
        p = src / n
        if not p.is_file():
            bad.append(f"MISSING {n}"); continue
        if p.stat().st_size != f["size"]:
            bad.append(f"SIZE {n}"); continue
        if not a.no_hash and sha(p) != f["sha256"]:
            bad.append(f"SHA256 {n}")
    if bad:
        sys.exit("refusing to build the pack:\n  " + "\n  ".join(bad))
    total = sum(f["size"] for f in D["files"].values())
    out.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(out).free
    rep = {"pack": D["pack"], "files": len(D["files"]), "bytes": total, "free_before": free,
           "free_after_estimate": free - total - 10 * 1024 * len(D["files"])}
    print(json.dumps(rep, indent=1), flush=True)
    if rep["free_after_estimate"] < FLOOR:
        sys.exit(f"free disk would drop below the 12 GiB floor ({rep['free_after_estimate']} B)")
    top = Path(a.stage) / D["top_dir"]
    d = top / D["subdir"]
    shutil.rmtree(top, ignore_errors=True)
    d.mkdir(parents=True)
    for n in D["files"]:
        os.link(src / n, d / n)          # OSError on another filesystem: never a second copy
    (top / "PACK.json").write_text(json.dumps({k: D[k] for k in ("pack", "subdir")} | {"version": VERSION,
                                    "files": len(D["files"]), "bytes": total}, indent=1))
    if (out / f"{D['archive']}.parts.json").exists():
        sys.exit(f"{out} already has a pack — refusing to rebuild (delete it explicitly)")
    t0 = time.time()
    tar = subprocess.Popen(["tar", "-C", str(top.parent), "--sort=name", "--owner=0", "--group=0",
                            "--numeric-owner", "--mtime=2026-10-26 00:00Z", "-cf", "-", top.name],
                           stdout=subprocess.PIPE)
    man = P.split_stream(tar.stdout, D["archive"], out, a.part_size,
                         {"version": VERSION, "top_dir": D["top_dir"], "kind": "docker-images",
                          "extracted_bytes": total})
    tar.stdout.close()
    if tar.wait() != 0:
        sys.exit(f"tar failed: {tar.returncode}")
    sums = [f"{man['sha256']}  {D['archive']}"] + [f"{p['sha256']}  {p['name']}" for p in man["parts"]]
    sums.append(f"{sha(out / (D['archive'] + '.parts.json'))}  {D['archive']}.parts.json")
    (out / f"{D['pack']}.SHA256SUMS").write_text("\n".join(sums) + "\n")
    rep.update(parts=len(man["parts"]), tar_bytes=man["size"], tar_sha256=man["sha256"],
               max_part_bytes=max(p["size"] for p in man["parts"]), seconds=round(time.time() - t0),
               free_after=shutil.disk_usage(out).free, built_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    (out / f"{D['pack']}.BUILD.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
