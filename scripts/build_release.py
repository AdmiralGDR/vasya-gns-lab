#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the Linux release ONCE from a finished stage: measure -> tar|zstd -> parts -> Setup.sh -> sums.

usage: build_release.py --stage STAGE/VASYA-GNS-LAB-1.1.0 --out OUT_DIR
                        [--part-size 99614720] [--level 12] [--docs docs] [--dry-run]
Refuses to start if free space on --out < 2.3 x the stage size (archive + parts + margin),
or if the archive already exists (no accidental rebuilds; delete it yourself to rebuild).
"""
import argparse, hashlib, json, os, shutil, subprocess, sys, time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from vasya import VERSION  # noqa: E402
from vasya.delivery import parts as P  # noqa: E402
from vasya.delivery.bootstrap import make_setup_script  # noqa: E402


def measure(top):
    seen, apparent, files = set(), 0, 0
    for dp, dn, fn in os.walk(top):
        for n in fn:
            st = os.lstat(os.path.join(dp, n))
            files += 1
            if (st.st_dev, st.st_ino) in seen:
                continue
            seen.add((st.st_dev, st.st_ino))
            apparent += st.st_size
    return {"files": files, "unique_bytes": apparent}


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 22), b""):
            h.update(c)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--part-size", type=int, default=95 * 1024 * 1024)
    ap.add_argument("--level", type=int, default=12)
    ap.add_argument("--docs", default=str(REPO / "docs"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--refresh-setup", action="store_true",
                    help="keep the existing archive/parts; regenerate Setup.sh, Docs and SHA256SUMS only")
    a = ap.parse_args()
    stage, out = Path(a.stage).resolve(), Path(a.out)
    assert a.part_size < 100 * 1000 * 1000, "parts must stay below 100 MB"
    out.mkdir(parents=True, exist_ok=True)
    name = f"VASYA-GNS-LAB-{VERSION}-Linux.tar.zst"
    arc = out / name
    m = measure(stage)
    free = shutil.disk_usage(out).free
    need = int(m["unique_bytes"] * 2.3)
    rep = {"stage": str(stage), **m, "free_bytes": free, "required_free_bytes": need}
    print(json.dumps(rep, indent=1), flush=True)
    if free < need:
        sys.exit(f"not enough free space: {free} < {need}")
    if a.dry_run:
        return
    if a.refresh_setup:
        parts_dir = out / "drive-parts"
        man = json.load(open(parts_dir / f"{name}.parts.json"))
        assert arc.stat().st_size == man["size"], "archive does not match parts manifest"
        old = json.load(open(out / "RELEASE_BUILD.json"))
        old["setup_refreshed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        return finish(out, arc, parts_dir, man, old, a.docs)
    if arc.exists():
        sys.exit(f"{arc} exists — refusing to rebuild (delete it explicitly)")
    t0 = time.time()
    tmp = arc.with_name(arc.name + ".partial")
    tar = subprocess.Popen(["tar", "-C", str(stage.parent), "--sort=name", "--owner=0", "--group=0",
                            "--numeric-owner", "-cf", "-", stage.name], stdout=subprocess.PIPE)
    z = subprocess.run(["zstd", "-q", "-T0", f"-{a.level}", "--long=27", "-o", str(tmp)], stdin=tar.stdout)
    tar.stdout.close()
    if tar.wait() != 0 or z.returncode != 0:
        tmp.unlink(missing_ok=True)
        sys.exit(f"archive failed tar={tar.returncode} zstd={z.returncode}")
    os.replace(tmp, arc)
    rep["archive_seconds"] = round(time.time() - t0)
    rep["archive_bytes"] = arc.stat().st_size
    parts_dir = out / "drive-parts"
    man = P.split(arc, parts_dir, a.part_size, {"version": VERSION, "top_dir": stage.name,
                                                "extracted_bytes": m["unique_bytes"]})
    rep.update(parts=len(man["parts"]), archive_sha256=man["sha256"],
               max_part_bytes=max(p["size"] for p in man["parts"]))
    rep["built_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    finish(out, arc, parts_dir, man, rep, a.docs)


def finish(out, arc, parts_dir, man, rep, docs):
    setup_name = f"VASYA-GNS-LAB-{VERSION}-Linux-Setup.sh"
    sys.path.insert(0, str(REPO / "scripts"))
    from build_docker_pack import spec as docker_spec   # Docker image pack: pinned file list, pack optional
    (parts_dir / setup_name).write_text(make_setup_script(man, setup_name, docker_spec()))
    (parts_dir / setup_name).chmod(0o755)
    shutil.copy2(parts_dir / setup_name, out / setup_name)
    if docs and Path(docs).exists():
        shutil.copytree(docs, out / "Docs", dirs_exist_ok=True)
    sums = []
    for p in sorted(out.rglob("*")):
        if any(x.endswith("-Docker-Images") for x in p.relative_to(out).parts):
            continue                       # the Docker image pack has its own SHA256SUMS
        if p.is_file() and p.name not in ("SHA256SUMS", "RELEASE_BUILD.json") \
                and not p.name.endswith(".partial"):
            rel = p.relative_to(out)
            s = man["sha256"] if p == arc else next((x["sha256"] for x in man["parts"] if x["name"] == p.name
                                                     and p.parent == parts_dir), None) or sha(p)
            sums.append(f"{s}  {rel}")
    (out / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    (out / "RELEASE_BUILD.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
