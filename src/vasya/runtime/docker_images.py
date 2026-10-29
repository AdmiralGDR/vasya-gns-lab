# SPDX-License-Identifier: GPL-3.0-or-later
"""Docker images for the rootless podman backend, pinned by digest.

Sources, in order: an offline archive (optional local image pack), else a pull of the pinned
digest from the official registry (docker.io) with a pull-only registries.conf, followed by an
image ID check against the pin. VASYA_OFFLINE=1 or VASYA_DOCKER_PULL=0 disables pulling.

Archive dirs, searched in order: <root>/Images/docker, <payload>/docker, <payload>/../Images/docker.
Each dir has docker-images.json (VASYA format, written by scripts/import_docker_archives.py from a
per-image CSV):
  {"format": 1, "images": [{"refs": ["gns3/openvswitch:latest", ...],   # all tags sharing this image
                            "archive": "gns3_openvswitch-<id12>.tar.zst",  # ONE file per unique image
                            "archive_sha256": "...", "archive_bytes": N,
                            "image_id": "sha256:<config digest>",           # podman/docker image ID
                            "repo_digest": "sha256:<registry manifest digest>"  # provenance (pinned pull)
                           }]}
Archive = `podman save --format docker-archive` (optionally zstd-compressed, .tar.zst). A .tar and a
.tar.zst of the same image must not both be shipped (validate_dir reports DUPLICATE_FORMAT).

Restore (before any docker node can be created: on every VASYA-managed gns3server start and in the
install step) verifies, in order: archive size + sha256 -> archive manifest.json (exactly one image,
its Config == image_id, RepoTags) -> load -> `image inspect` Id == image_id -> every ref
tagged on that ID (re-tagged if missing). repo_digest cannot be re-checked offline (docker-archive does
not keep the registry manifest); it is recorded as provenance, the content-addressed image_id is the
offline integrity check.
"""
import csv, hashlib, json, os, re, shutil, subprocess, tarfile
from pathlib import Path

MANIFEST = "docker-images.json"
ARCHIVE_EXT = (".tar.zst", ".tar")
# Built-in pins: the same format, shipped inside App/vasya/data. Used for an archive dir
# that has no docker-images.json of its own (e.g. ~/VASYA-GNS-LAB/Images/docker), and authoritative
# for every ref it lists: an archive whose image_id differs from the pin is never loaded.
BUILTIN = Path(__file__).resolve().parent.parent / "data" / MANIFEST


def pack_name():
    """The separate Docker image pack (delivered next to the core release, joined by Setup.sh)."""
    from .. import VERSION
    return f"VASYA-GNS-LAB-{VERSION}-Docker-Images"


PACK_MISSING = "image pack missing"


def pack_status(ctx):
    """Which pinned archives are present in the archive dirs. status PRESENT | PARTIAL | MISSING."""
    pins = builtin_entries()
    have = {e["archive"] for e in entries(ctx) if (Path(e["_dir"]) / e["archive"]).is_file()}
    missing = [e["archive"] for e in pins if e["archive"] not in have]
    st = "PRESENT" if not missing else ("MISSING" if len(missing) == len(pins) else "PARTIAL")
    return {"status": st, "pack": pack_name(), "archives": len(pins), "present": len(pins) - len(missing),
            "missing": missing, "dir": str(ctx.layout.root / "Images" / "docker")}


def pack_missing_reason(ctx, ref):
    p = pin_for_ref(ref)
    what = p["archive"] if p else f"an offline archive for {ref}"
    return (f"{PACK_MISSING}: {what} is not in {ctx.layout.root / 'Images' / 'docker'} — put the parts of "
            f"{pack_name()} next to the Linux Setup.sh, or connect to the internet so the pinned image can be "
            f"pulled from the registry, and run it again")


def builtin_entries():
    if not BUILTIN.is_file():
        return []
    return json.loads(BUILTIN.read_text(encoding="utf-8")).get("images", [])


def pin_for_ref(ref):
    """The pinned entry (refs, repo_digest, image_id, archive...) for `ref`, or None."""
    n = _norm(ref)
    return next((e for e in builtin_entries() if n in {_norm(r) for r in e.get("refs", [])}), None)


def pin_for_block(block_id):
    return next((e for e in builtin_entries() if block_id in (e.get("blocks") or [])), None)


def archive_dirs(ctx):
    pr = Path(ctx.payload_root) if getattr(ctx, "payload_root", None) else None
    ds = [ctx.layout.root / "Images" / "docker"]
    if pr:
        ds += [pr / "docker", pr.parent / "Images" / "docker"]
    out = []
    for d in ds:
        if d not in out:
            out.append(d)
    return out


def _norm(ref):
    """docker.io/library/alpine:latest == alpine:latest == alpine"""
    r = ref.strip()
    if "@" in r:
        r = r.split("@", 1)[0]
    if ":" not in r.rsplit("/", 1)[-1]:
        r += ":latest"
    for p in ("docker.io/library/", "docker.io/", "index.docker.io/library/"):
        if r.startswith(p):
            r = r[len(p):]
            break
    return r


def load_manifest(d):
    p = Path(d) / MANIFEST
    if not p.is_file():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    return [dict(e, _dir=str(d)) for e in data.get("images", [])]


def entries(ctx):
    """Archive entries from every archive dir: its own docker-images.json, else the built-in pins whose
    archive file is present in that dir."""
    out = []
    for d in archive_dirs(ctx):
        own = load_manifest(d)
        if own:
            out += own
        elif Path(d).is_dir():
            out += [dict(e, _dir=str(d), _source="builtin") for e in builtin_entries()
                    if (Path(d) / e["archive"]).is_file()]
    return out


def pin_conflict(e):
    """Reason string when entry `e` contradicts a built-in pin for any of its refs, else None."""
    for r in e.get("refs", []):
        p = pin_for_ref(r)
        if p and p.get("image_id") and _id_hex(p["image_id"]) != _id_hex(e.get("image_id")):
            return f"{r}: archive image {_id_hex(e.get('image_id'))[:12] or '?'} != pinned {_id_hex(p['image_id'])[:12]}"
    return None


def find(ctx, ref):
    n = _norm(ref)
    for e in entries(ctx):
        if n in {_norm(r) for r in e.get("refs", [])} and not pin_conflict(e):
            return e
    return None


def sha256_file(p, bs=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(bs), b""):
            h.update(b)
    return h.hexdigest()


def _open_stream(path):
    """(stream, proc) of the uncompressed docker-archive."""
    if str(path).endswith(".zst"):
        z = shutil.which("zstd")
        if not z:
            raise RuntimeError("zstd not found: needed to read " + str(path))
        proc = subprocess.Popen([z, "-dc", str(path)], stdout=subprocess.PIPE)
        return proc.stdout, proc
    f = open(path, "rb")
    return f, None


def archive_manifest(path):
    """manifest.json of a docker-archive (streamed; works on .tar and .tar.zst)."""
    s, proc = _open_stream(path)
    try:
        with tarfile.open(fileobj=s, mode="r|") as tf:
            for m in tf:
                if m.name in ("manifest.json", "./manifest.json"):
                    return json.load(tf.extractfile(m))
    finally:
        s.close()
        if proc:
            proc.wait()
    return None


def repo_of(ref):
    """'ghcr.io:443/a/b:tag' -> 'ghcr.io:443/a/b' (tag and digest stripped; registry port kept)."""
    r = ref.split("@", 1)[0]
    head, _, last = r.rpartition("/")
    if ":" in last:
        last = last.split(":", 1)[0]
    return f"{head}/{last}" if head else last


def _id_hex(x):
    x = (x or "").split(":", 1)[-1]
    return x.replace(".json", "").split("/")[-1]


def verify_archive(e):
    """Checks that need no container engine. Returns (ok, reason)."""
    p = Path(e["_dir"]) / e["archive"]
    if not p.is_file():
        return False, f"archive missing: {p}"
    if e.get("archive_bytes") is not None and p.stat().st_size != int(e["archive_bytes"]):
        return False, f"archive size {p.stat().st_size} != {e['archive_bytes']}"
    if sha256_file(p) != e["archive_sha256"]:
        return False, "archive sha256 mismatch"
    try:
        man = archive_manifest(p)
    except (tarfile.TarError, OSError, ValueError, RuntimeError) as ex:
        return False, f"archive unreadable: {ex}"
    if not man or len(man) != 1:
        return False, f"archive manifest must describe exactly one image (got {len(man or [])})"
    cfg = _id_hex(man[0].get("Config"))
    if e.get("image_id") and not _id_hex(e["image_id"]).startswith(cfg) and not cfg.startswith(_id_hex(e["image_id"])):
        return False, f"archive image {cfg[:12]} != expected {_id_hex(e['image_id'])[:12]}"
    return True, None


def _inspect_id(run, cmd, ref):
    r = run(cmd + ["image", "inspect", "--format", "{{.Id}}", ref], capture_output=True, text=True)
    return _id_hex(r.stdout.strip()) if r.returncode == 0 else None


def present(run, cmd, ref, image_id=None):
    got = _inspect_id(run, cmd, ref)
    return bool(got) and (not image_id or got.startswith(_id_hex(image_id)[:12]))


def restore(ctx, ref, cmd, env=None, run=None, popen=subprocess.Popen, pull=None):
    """Restore `ref` from its offline archive; without one, pull the pinned digest from the
    official registry (unless offline). Returns dict(status, ...)."""
    run0 = run
    run = run or (lambda a, **k: subprocess.run(a, env=env, **k))
    e = find(ctx, ref)
    if not e:
        if pull if pull is not None else pull_allowed():
            pr = pull_pinned(ctx, ref, cmd, env=env, run=run0)
            if pr["status"] in ("PULLED", "PRESENT"):
                return dict(pr, status="RESTORED" if pr["status"] == "PULLED" else "PRESENT")
            return {"status": "NO_ARCHIVE", "ref": ref, "message": pack_missing_reason(ctx, ref),
                    "pull": pr}
        return {"status": "NO_ARCHIVE", "ref": ref, "message": pack_missing_reason(ctx, ref)}
    if present(run, cmd, ref, e.get("image_id")):
        return {"status": "PRESENT", "ref": ref, "archive": e["archive"]}
    ok, why = verify_archive(e)
    if not ok:
        return {"status": "ARCHIVE_INVALID", "ref": ref, "archive": e["archive"], "error": why}
    p = Path(e["_dir"]) / e["archive"]
    s, zp = _open_stream(p)
    try:
        lp = popen(cmd + ["load"], stdin=s, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        out, err = lp.communicate(timeout=7200)
    finally:
        s.close()
        if zp:
            zp.wait()
    if lp.returncode != 0:
        return {"status": "LOAD_FAILED", "ref": ref, "error": (err or out or b"").decode(errors="replace")[-300:]}
    iid = e.get("image_id")
    if iid and not present(run, cmd, iid):
        return {"status": "ID_MISMATCH", "ref": ref, "error": f"image {iid[:19]} not present after load"}
    retagged = []
    for r in e.get("refs", []):
        if not present(run, cmd, r, iid):
            t = run(cmd + ["tag", iid or ref, r], capture_output=True, text=True)
            if t.returncode != 0 or not present(run, cmd, r, iid):
                return {"status": "TAG_FAILED", "ref": r, "error": (t.stderr or "")[-200:]}
            retagged.append(r)
    return {"status": "RESTORED", "ref": ref, "archive": e["archive"], "image_id": iid,
            "archive_sha256": e["archive_sha256"], "retagged": retagged, "source": "offline-archive"}


def validate_dir(d):
    """Release check: one archive per unique image, all listed, no tar+zst duplicates, no strays."""
    d = Path(d)
    issues = []
    es = load_manifest(d)
    ids = {}
    for e in es:
        k = _id_hex(e.get("image_id") or e["archive"])
        if k in ids:
            issues.append(f"DUPLICATE_IMAGE {e['archive']} and {ids[k]}")
        ids[k] = e["archive"]
    listed = {e["archive"] for e in es}
    stems = {}
    for f in sorted(d.iterdir()) if d.exists() else []:
        if f.name.endswith(ARCHIVE_EXT):
            stem = f.name[:-8] if f.name.endswith(".tar.zst") else f.name[:-4]
            if stem in stems:
                issues.append(f"DUPLICATE_FORMAT {stems[stem]} and {f.name}")
            stems[stem] = f.name
            if f.name not in listed:
                issues.append(f"UNLISTED {f.name}")
    for a in listed - set(stems.values()):
        issues.append(f"MISSING {a}")
    return issues


# ------------------------------------------------------------------ test CSV import
_COLS = {"refs": ("refs", "ref", "image", "docker_image", "image_ref", "tag", "tags"),
         "archive": ("archive", "archive_file", "tar", "file", "filename", "archive_path"),
         "archive_sha256": ("archive_sha256", "sha256", "tar_sha256", "file_sha256"),
         "archive_bytes": ("archive_bytes", "bytes", "size", "size_bytes", "tar_bytes"),
         "image_id": ("image_id", "id", "imageid", "config_digest"),
         "repo_digest": ("repo_digest", "digest", "manifest_digest", "pinned_digest", "amd64_digest"),
         "blocks": ("blocks", "block", "block_id", "template", "templates"),
         "key": ("key",), "arch": ("arch", "platform")}


def _index_by_sha(index_path):
    """Images/docker/index.json of an archive set -> {archive_sha256: (archive basename, image_id)}."""
    if not index_path:
        return {}
    d = json.loads(Path(index_path).read_text(encoding="utf-8"))
    return {v["sha256"].lower(): (Path(v["archive"]).name, v.get("image_id")) for v in d.values() if v.get("sha256")}


def _pop_archive_name(key, digest):
    """Archive naming: <key>-<first 12 hex of the pinned digest>.tar.zst"""
    return f"{key}-{digest.split(':', 1)[-1][:12]}.tar.zst"


def manifest_from_csv(csv_path, index_path=None):
    """Per-image CSV (one row per template; rows sharing an archive are one image) -> manifest.
    The test CSV has no archive/image_id columns: the archive name follows the archive naming
    (<key>-<digest12>.tar.zst) and image_id comes from index.json (matched by archive sha256)."""
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8", newline="")))
    if not rows:
        return {"format": 1, "images": []}
    low = {h.lower().strip(): h for h in rows[0].keys()}
    col = {k: next((low[c] for c in cands if c in low), None) for k, cands in _COLS.items()}
    derive = not col["archive"] and col["key"] and col["repo_digest"]
    miss = [k for k in ("refs", "archive", "archive_sha256") if not col[k] and not (k == "archive" and derive)]
    if miss:
        raise ValueError(f"CSV {csv_path} lacks columns for {miss}; headers: {list(rows[0])}")
    idx = _index_by_sha(index_path)
    by = {}
    for r in rows:
        sha = r[col["archive_sha256"]].strip().lower()
        if col["archive"]:
            arc = Path(r[col["archive"]].strip()).name
        else:
            arc = idx.get(sha, (None,))[0] or _pop_archive_name(r[col["key"]].strip(), r[col["repo_digest"]].strip())
        if not arc:
            continue
        e = by.setdefault(arc, {"refs": [], "archive": arc, "archive_sha256": sha})
        if e["archive_sha256"] != sha:
            raise ValueError(f"{arc}: rows disagree on archive sha256")
        for ref in re.split(r"[;,| ]+", r[col["refs"]].strip()):
            if ref and ref not in e["refs"]:
                e["refs"].append(ref)
        if col["blocks"]:
            for b in re.split(r"[;,| ]+", (r.get(col["blocks"]) or "").strip()):
                if b and b not in e.setdefault("blocks", []):
                    e["blocks"].append(b)
        for k in ("archive_bytes", "image_id", "repo_digest", "arch"):
            v = (r.get(col[k]) or "").strip() if col[k] else ""
            if v:
                e[k] = int(v) if k == "archive_bytes" else v
        if not e.get("image_id") and idx.get(sha, (None, None))[1]:
            iid = idx[sha][1]
            e["image_id"] = iid if iid.startswith("sha256:") else "sha256:" + iid
    return {"format": 1, "images": list(by.values())}


# ------------------------------------------------------------------ pinned pull from the official registry
PULL_ENV = "VASYA_DOCKER_PULL"      # "0": never pull, offline archives only
PULL_REGISTRIES = ("docker.io", "ghcr.io")     # every registry a pin in docker-images.json uses


def pull_allowed():
    from ..fetch.download import offline
    return not offline() and os.environ.get(PULL_ENV, "1").strip() != "0"


def pull_registries_conf(ctx):
    """A registries.conf used only for VASYA's own pinned pulls. The default one (used by the
    API service that gns3server talks to) keeps every registry blocked, so GNS3 itself can
    never pull an unpinned image."""
    from . import docker_backend as dbk
    p = dbk.podman_paths(ctx)["registries_conf"].with_name("registries-pull.conf")
    p.parent.mkdir(parents=True, exist_ok=True)
    blocked = [r for r in dbk.BLOCKED_REGISTRIES if r not in PULL_REGISTRIES]
    p.write_text("# VASYA: pinned pulls by digest only (see third_party.lock)\n"
                 "unqualified-search-registries = []\nshort-name-mode = \"enforcing\"\n"
                 + "".join(f"[[registry]]\nlocation = \"{r}\"\nblocked = true\n" for r in blocked))
    return p


def pinned_source(pin):
    """Fully qualified `docker.io/<repo>@<digest>` for a pin, or None."""
    if not pin or not pin.get("repo_digest"):
        return None
    repo = repo_of(_norm(pin["refs"][0]))
    if "/" not in repo:
        repo = "library/" + repo
    first = repo.split("/", 1)[0]
    if "." not in first and ":" not in first:
        repo = "docker.io/" + repo
    return f"{repo}@{pin['repo_digest']}"


def pull_pinned(ctx, ref, cmd, env=None, run=None):
    """Pull the pinned digest of `ref`, check the image ID against the pin, tag every pinned ref.
    Returns {"status": PULLED|PRESENT|NO_PIN|OFFLINE|PULL_FAILED|ID_MISMATCH|TAG_FAILED, ...}."""
    pin = pin_for_ref(ref)
    src = pinned_source(pin)
    if not src:
        return {"status": "NO_PIN", "ref": ref}
    if not pull_allowed():
        return {"status": "OFFLINE", "ref": ref}
    penv = dict(env if env is not None else os.environ)
    if cmd and os.path.basename(cmd[-1]) == "podman":
        penv["CONTAINERS_REGISTRIES_CONF"] = str(pull_registries_conf(ctx))
    run = run or (lambda a, **k: subprocess.run(a, env=penv, **k))
    iid = pin.get("image_id")
    if present(run, cmd, ref, iid):
        return {"status": "PRESENT", "ref": ref}
    r = run(cmd + ["pull", "--quiet", src], capture_output=True, text=True, timeout=7200)
    if r.returncode != 0:
        return {"status": "PULL_FAILED", "ref": ref, "pinned": src, "error": (r.stderr or r.stdout or "")[-300:]}
    if iid and not present(run, cmd, src, iid):
        run(cmd + ["rmi", src], capture_output=True, text=True)
        return {"status": "ID_MISMATCH", "ref": ref, "pinned": src,
                "error": f"pulled image is not {iid[:19]}"}
    for t in pin.get("refs", []):
        tr = run(cmd + ["tag", iid or src, t], capture_output=True, text=True)
        if tr.returncode != 0:
            return {"status": "TAG_FAILED", "ref": t, "error": (tr.stderr or "")[-200:]}
    return {"status": "PULLED", "ref": ref, "pinned": src, "image_id": iid, "source": "registry"}
