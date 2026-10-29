# SPDX-License-Identifier: GPL-3.0-or-later
"""Images that must not be redistributed, from sources only the user can reach.

Cisco IOS and other vendor images are never part of the source tree or of a public release.
A user who owns licensed copies keeps them in a private source; VASYA fetches them from
there automatically and checks every file against the user's private manifest.

Sources are tried in order. They come from (first match wins):
  1. VASYA_PRIVATE_SOURCES   -- ';'-separated list: a folder path, gh:OWNER/REPO@TAG or an
                                https:// base URL ("none" disables private sources)
  2. VASYA_PRIVATE_SOURCES_FILE, else <config dir>/vasya-gns-lab/private-sources.json:
        {"sources": [{"type": "dir", "path": "~/VASYA-GNS-LAB/Images"},
                     {"type": "github-release", "repo": "OWNER/REPO", "tag": "TAG"},
                     {"type": "https", "url": "https://host/path/", "token_env": "VASYA_PRIVATE_TOKEN"}]}
  3. defaults: the folder ~/VASYA-GNS-LAB/Images (if it exists), and, when the GitHub CLI is
     signed in, the release "images" of <your GitHub login>/vasya-gns-lab-private.

A source holds ``vasya-private-manifest.json`` and the image files (by file name, or named
by their SHA-256). Manifest format (format 1):
  {"format": 1,
   "blocks": [{"block_id", "name", "vendor", "category", "runtime", "architecture", "ram",
               "images": [{"logical_filename", "sha256", "size", "md5", "disk_slot"}],
               "appliance": {...GNS3 appliance JSON...}}]}
Any failure (no source, no network, wrong checksum) only leaves those devices marked
"image not available"; it never stops an installation.
"""
import json, os, shutil, subprocess, urllib.parse
from pathlib import Path
from . import download

MANIFEST = "vasya-private-manifest.json"
ENV_LIST, ENV_FILE = "VASYA_PRIVATE_SOURCES", "VASYA_PRIVATE_SOURCES_FILE"
DEFAULT_REPO_NAME, DEFAULT_TAG = "vasya-gns-lab-private", "images"
TOKEN_ENV = "VASYA_PRIVATE_TOKEN"


def config_dir():
    if os.name == "nt":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "vasya-gns-lab"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "vasya-gns-lab"


def config_file():
    return Path(os.environ.get(ENV_FILE) or config_dir() / "private-sources.json")


def _parse(item):
    item = item.strip()
    if not item:
        return None
    if item.startswith("gh:"):
        repo, _, tag = item[3:].partition("@")
        return {"type": "github-release", "repo": repo, "tag": tag or DEFAULT_TAG}
    if item.startswith(("https://", "http://")):
        return {"type": "https", "url": item}
    return {"type": "dir", "path": item}


def _gh(run=subprocess.run):
    gh = shutil.which("gh")
    if not gh:
        return None
    try:
        r = run([gh, "api", "user", "--jq", ".login"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def sources(run=subprocess.run):
    env = os.environ.get(ENV_LIST)
    if env and env.strip().lower() == "none":
        return []
    if env:
        return [s for s in (_parse(x) for x in env.split(";")) if s]
    cf = config_file()
    if cf.is_file():
        try:
            return list(json.loads(cf.read_text(encoding="utf-8")).get("sources") or [])
        except (OSError, ValueError):
            return []
    out = []
    d = Path.home() / "VASYA-GNS-LAB" / "Images"
    if d.is_dir():
        out.append({"type": "dir", "path": str(d)})
    if not download.offline():
        login = _gh(run)
        if login:
            out.append({"type": "github-release", "repo": f"{login}/{DEFAULT_REPO_NAME}", "tag": DEFAULT_TAG})
    return out


def describe(src):
    t = src.get("type")
    return (src.get("path") if t == "dir" else
            f"gh:{src.get('repo')}@{src.get('tag') or DEFAULT_TAG}" if t == "github-release" else
            _redact(src.get("url", "")))


def _redact(url):
    p = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((p.scheme, p.hostname or "", p.path, "", "")) if p.scheme else url


# ------------------------------------------------------------------ getting one file from a source
def _dir_candidates(root, name, sha):
    root = Path(os.path.expanduser(root))
    cands = [root / name, root / sha, root / "sha256" / sha, root / "images" / "sha256" / sha]
    for sub in ("dynamips", "IOS", "QEMU", "images"):
        cands.append(root / sub / name)
    return [c for c in cands if c.is_file()]


def _gh_get(src, name, dest_dir, run):
    gh = shutil.which("gh")
    if not gh or download.offline():
        return None, "GitHub CLI not available" if not gh else "offline"
    dest_dir.mkdir(parents=True, exist_ok=True)
    cmd = [gh, "release", "download", src.get("tag") or DEFAULT_TAG, "-R", src["repo"],
           "-p", name, "-D", str(dest_dir), "--clobber"]
    try:
        r = run(cmd, capture_output=True, text=True, timeout=3600)
    except (OSError, subprocess.SubprocessError) as e:
        return None, str(e)
    p = dest_dir / name
    if r.returncode != 0 or not p.is_file():
        return None, (r.stderr or r.stdout or "gh release download failed").strip()[-300:]
    return p, None


def _https_get(src, name, dest, sha, size):
    base = src["url"] if src["url"].endswith("/") else src["url"] + "/"
    tok = os.environ.get(src.get("token_env") or TOKEN_ENV)
    headers = {"Authorization": f"Bearer {tok}"} if tok else {}
    r = download.fetch([base + urllib.parse.quote(name)], dest, sha, size=size, headers=headers)
    return (Path(r["path"]), None) if r["status"] == "OK" else (None, "; ".join(r["errors"])[-300:])


def get(src, name, dest_dir, sha=None, size=None, run=subprocess.run):
    """Path of `name` from `src` (not yet verified unless sha was given to an https source)."""
    t = src.get("type")
    try:
        if t == "dir":
            c = _dir_candidates(src.get("path", ""), name, sha or "-")
            return (c[0], None) if c else (None, "not in folder")
        if t == "github-release":
            return _gh_get(src, name, Path(dest_dir), run)
        if t == "https":
            return _https_get(src, name, Path(dest_dir) / name, sha, size)
    except Exception as e:  # a broken source must never stop the installation
        return None, f"{type(e).__name__}: {e}"
    return None, f"unknown source type {t!r}"


# ------------------------------------------------------------------ manifest and blocks
def manifest_cache(layout):
    return Path(layout.State) / "private-manifest.json"


def appliance_dir(layout):
    return Path(layout.Store) / "private" / "appliances"


def sync_manifest(layout, srcs=None, run=subprocess.run):
    """Read the first available private manifest; cache it under State so it works offline.
    Returns {"status": "OK"|"CACHED"|"NONE", "source", "blocks", "errors"}."""
    srcs = sources(run) if srcs is None else srcs
    tmp = download.cache_dir(layout) / "private"
    errors = []
    for s in srcs:
        p, err = get(s, MANIFEST, tmp, run=run)
        if not p:
            errors.append(f"{describe(s)}: {err}")
            continue
        try:
            data = json.loads(Path(p).read_text(encoding="utf-8"))
            if data.get("format") != 1 or not isinstance(data.get("blocks"), list):
                raise ValueError("not a format 1 VASYA private manifest")
        except (OSError, ValueError) as e:
            errors.append(f"{describe(s)}: {e}")
            continue
        _write_cache(layout, data)
        return {"status": "OK", "source": describe(s), "blocks": len(data["blocks"]), "errors": errors}
    if manifest_cache(layout).is_file():
        return {"status": "CACHED", "source": str(manifest_cache(layout)), "errors": errors,
                "blocks": len(load_manifest(layout).get("blocks", []))}
    return {"status": "NONE", "source": None, "blocks": 0, "errors": errors}


def _write_cache(layout, data):
    mc = manifest_cache(layout)
    mc.parent.mkdir(parents=True, exist_ok=True)
    ad = appliance_dir(layout)
    ad.mkdir(parents=True, exist_ok=True)
    for b in data["blocks"]:
        if isinstance(b.get("appliance"), dict):
            (ad / f"{_safe(b['block_id'])}.gns3a").write_text(
                json.dumps(b["appliance"], indent=4, ensure_ascii=False), encoding="utf-8")
    tmp = mc.with_name(mc.name + ".partial")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, mc)


def _safe(bid):
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in bid)


def load_manifest(layout):
    try:
        return json.loads(manifest_cache(layout).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"format": 1, "blocks": []}


def manifest_images(layout):
    """{sha256: image entry} for every image in the cached private manifest."""
    out = {}
    for b in load_manifest(layout).get("blocks", []):
        for im in b.get("images") or []:
            out.setdefault(im["sha256"], dict(im, blocks=[]))["blocks"].append(b["block_id"])
    return out


def blocks(layout, have=None):
    """Private blocks in the payload block format (template = the cached appliance file).
    `have(sha)` -> bool decides availability; unavailable blocks carry image_available=False."""
    out = []
    for b in load_manifest(layout).get("blocks", []):
        blk = {k: v for k, v in b.items() if k != "appliance"}
        ap = appliance_dir(layout) / f"{_safe(b['block_id'])}.gns3a"
        blk.update(template=None, _appliance_abs=str(ap) if ap.is_file() else None,
                   appliance_meta_ok=ap.is_file(), private=True)
        blk["image_available"] = all(have(im["sha256"]) for im in blk.get("images") or []) if have else None
        out.append(blk)
    return out


def fetch_image(layout, sha, name, size=None, srcs=None, run=subprocess.run, place=None):
    """Find `name` (sha256 `sha`) in the private sources, verify it and place it with `place(path)`.
    Returns {"status": "FETCHED"|"NOT_AVAILABLE", "source", "reason"}."""
    srcs = sources(run) if srcs is None else srcs
    tmp = download.cache_dir(layout) / "private"
    reasons = []
    for s in srcs:
        p, err = get(s, name, tmp, sha=sha, size=size, run=run)
        if not p:
            reasons.append(f"{describe(s)}: {err}")
            continue
        if (size is not None and Path(p).stat().st_size != size) or download.sha256_file(p) != sha:
            reasons.append(f"{describe(s)}: {name} does not match the private manifest (sha256)")
            if Path(p).is_relative_to(tmp):
                Path(p).unlink(missing_ok=True)
            continue
        place(Path(p))
        if Path(p).is_relative_to(tmp):
            Path(p).unlink(missing_ok=True)
        return {"status": "FETCHED", "source": describe(s)}
    return {"status": "NOT_AVAILABLE", "source": None,
            "reason": "; ".join(reasons) or "no private image source configured"}
