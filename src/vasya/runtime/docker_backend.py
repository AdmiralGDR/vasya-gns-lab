# SPDX-License-Identifier: GPL-3.0-or-later
"""Pluggable Docker backend.

Defaults: Linux -> podman-rootless (primary, automatic); Windows -> gns3-vm (Docker nodes in
the GNS3 VM; integration path not verified on real Windows -> UNVERIFIED, never rootless podman).
shared-daemon is used only when explicitly selected (VASYA_DOCKER_BACKEND=shared-daemon or state).

shared-daemon (explicit opt-in only)
    The system Docker daemon that gns3server 2.2.61 hard-codes (/var/run/docker.sock).
    Ownership rules: an image that was already present gets NO receipt (pre-existing ->
    never removed); a pulled/loaded image gets a receipt; every VASYA template uses a thin
    image labelled org.vasya.owner=vasya-gns-lab (+ root tag); before any `rmi` the
    containers/images that still use it are counted and foreign users keep it; no prune, ever.
podman-rootless (Linux default; tested on Pop!_OS 24.04 with all 21 images)
    Rootless podman with ALL persistent state under <root>/Runtime/podman (graphroot, runroot,
    XDG config/data/cache, XDG_RUNTIME_DIR, events log, libpod tmp, network config); the API socket
    is served by a VASYA-launched `podman system service` user process (no systemctl, no sudo, no
    /var/run/docker.sock). Storage is configured through the USER config
    $XDG_CONFIG_HOME/containers/storage.conf — CONTAINERS_STORAGE_CONF is never set (podman then
    treats the file as the *system* config and ignores its graphroot in rootless mode).
    containers.conf sets netns="none" (podman compat ignores GNS3's NetworkDisabled=true; uBridge
    wires eth0). registries.conf blocks docker.io/quay.io/ghcr.io for the API service, so gns3server can never
    pull an unpinned image. Images come from VASYA itself: `podman load -i` of an offline archive,
    or a pull of the pinned digest with a separate registries-pull.conf (docker_images.pull_pinned).
    VASYA's bundled gns3server carries a tested 3-part patch
    (data/patches/gns3server-2.2.61-vasya-docker-socket.patch), inert unless VASYA sets the env:
      1. VASYA_DOCKER_SOCKET  -> Docker API socket (default /var/run/docker.sock)
      2. attach/ws 404        -> fallback to a hijacked POST /containers/{id}/attach (podman 4.9 has no attach/ws)
      3. VASYA_DOCKER_FIX_UID/GID -> chown target in _fix_permissions (0 under rootless podman = host user)
    The server env (socket, DOCKER_HOST for gns3server's `docker exec` aux console, FIX_UID/GID=0) is
    exported ONLY to VASYA's own gns3server process and ONLY when the VASYA podman socket exists.
    VASYA writes the configs, starts the service before its gns3server and stops it with it; the user never
    touches the socket, podman or the archives. Missing images are restored (offline archive, else a
    pinned pull; runtime/docker_images.py) before gns3server starts, i.e. before any docker node exists.
Offline images (any backend, optional)
    `docker save` tars from the optional image pack in Images/docker/ (or <payload>/docker/) are loaded
    with `load -i` instead of pulling; the receipt records source=offline-tar and the engine.
"""
import hashlib, os, re, shutil, subprocess, tempfile, time
from pathlib import Path

BACKENDS = {
    "podman-rootless": {"implemented": True, "platforms": ("posix",)},
    "shared-daemon": {"implemented": True, "platforms": ("posix", "nt")},
    "gns3-vm": {"implemented": False, "platforms": ("nt", "posix"),
                "why": "Docker nodes on Windows run inside the GNS3 VM; the VASYA GNS3-VM integration path is "
                       "not verified on real Windows yet (UNVERIFIED) — Docker components stay unavailable"},
}


def default_backend(osname=None):
    return "gns3-vm" if (osname or os.name) == "nt" else "podman-rootless"


DEFAULT = default_backend()
# unified env names (identical in the patch and in server.sh)
SOCK_ENV = "VASYA_DOCKER_SOCKET"
FIX_UID_ENV, FIX_GID_ENV = "VASYA_DOCKER_FIX_UID", "VASYA_DOCKER_FIX_GID"
LEGACY_SOCK_ENV = "VASYA_DOCKER_SOCK"          # 1.1.0 pre-merge name; never exported any more
ENGINE_SHARED, ENGINE_PODMAN = "shared-daemon", "podman-rootless"
# pre-merge one-line patch (only used to upgrade an already-patched tree in place)
SOCK_PATCH_OLD = "self._server_url = '/var/run/docker.sock'"
LEGACY_SOCK_PATCH = ("self._server_url = __import__('os').environ.get('VASYA_DOCKER_SOCK', "
                     "'/var/run/docker.sock')  # VASYA patch: rootless podman socket")
PATCH_NAME = "gns3server-2.2.61-vasya-docker-socket.patch"
PATCH_FILE = Path(__file__).resolve().parent.parent / "data" / "patches" / PATCH_NAME
PATCH_FILES = ("gns3server/compute/docker/__init__.py", "gns3server/compute/docker/docker_vm.py")
PATCH_MARKERS = {PATCH_FILES[0]: ('os.environ.get("VASYA_DOCKER_SOCKET")', "_VasyaHijackedAttach"),
                 PATCH_FILES[1]: ('os.environ.get("VASYA_DOCKER_FIX_UID")',)}
# Patch 4: container init.sh skips busybox `su` when the container user is root —
# the host's static glibc busybox `su` aborts in old-glibc images (aaa, python-go-perl-php: exit 139).
INIT_SU_PATCH_NAME = "gns3server-2.2.61-vasya-init-su.patch"
INIT_SU_PATCH_FILE = PATCH_FILE.parent / INIT_SU_PATCH_NAME
INIT_SH = "gns3server/compute/docker/resources/init.sh"
INIT_SU_MARKER = "# VASYA patch 4: for root, skip `su`."
BLOCKED_REGISTRIES = ("docker.io", "quay.io", "ghcr.io")
UNIX_SOCK_MAX = 107                             # sun_path limit (108 incl. NUL)


def select(ctx, osname=None):
    osname = osname or os.name
    d = default_backend(osname)
    name = os.environ.get("VASYA_DOCKER_BACKEND") or (ctx.state.load().get("docker_backend")
                                                       if ctx.layout.State.exists() else None) or d
    if name not in BACKENDS or osname not in BACKENDS[name]["platforms"]:
        return d
    return name


def podman_active(ctx):
    return os.name != "nt" and select(ctx) == "podman-rootless"


def unavailable_reason(ctx, which=shutil.which):
    name = select(ctx)
    b = BACKENDS[name]
    if not b["implemented"]:
        return b["why"]
    if name == "podman-rootless":
        miss = podman_prereqs(which)
        if miss:
            return ("rootless podman prerequisites missing: " + ", ".join(miss) +
                    " (install: sudo apt install podman uidmap; your existing Docker is not used or changed)")
        sock = str(podman_paths(ctx)["sock"])
        if len(sock.encode()) > UNIX_SOCK_MAX:
            return f"VASYA folder path too long for a unix socket ({len(sock.encode())} > {UNIX_SOCK_MAX} bytes): {sock}"
    return None


def podman_prereqs(which=shutil.which, subuid="/etc/subuid", user=None):
    user = user or os.environ.get("USER") or ""
    miss = [t for t in ("podman", "newuidmap", "newgidmap") if not which(t)]
    try:
        if not any(ln.split(":")[0] == user for ln in Path(subuid).read_text().splitlines() if ln):
            miss.append(f"{subuid} entry for {user}")
    except OSError:
        miss.append(subuid)
    return miss


def _root(ctx_or_root):
    return Path(ctx_or_root) if isinstance(ctx_or_root, (str, os.PathLike)) else ctx_or_root.layout.root


def podman_paths(ctx_or_root):
    """Every podman path lives under <root>/Runtime/podman (tested layout, relocated per root)."""
    base = _root(ctx_or_root) / "Runtime" / "podman"
    xdg, run = base / "xdg", base / "run"
    cdir = xdg / "config" / "containers"
    return {"base": base, "xdg_config": xdg / "config", "xdg_data": xdg / "data", "xdg_cache": xdg / "cache",
            "runtime_dir": run / "xdg", "run": run,
            "graphroot": base / "storage", "runroot": run / "storage-runroot",
            "conf": cdir / "storage.conf", "containers_conf": cdir / "containers.conf",
            "registries_conf": cdir / "registries.conf",
            "events": base / "events.log", "tmp_dir": run / "libpod-tmp", "networks": base / "networks",
            "sock": run / "podman.sock", "pid": run / "service.pid", "log": base / "service.log"}


def podman_env(ctx_or_root, base=None):
    """Environment for every podman call (CLI and API service). Storage comes from the USER config
    under XDG_CONFIG_HOME; CONTAINERS_STORAGE_CONF is removed, never set (see above)."""
    p = podman_paths(ctx_or_root)
    env = dict(base if base is not None else os.environ)
    env.pop("CONTAINERS_STORAGE_CONF", None)
    env.pop("DOCKER_HOST", None)
    env.update({"XDG_CONFIG_HOME": str(p["xdg_config"]), "XDG_DATA_HOME": str(p["xdg_data"]),
                "XDG_CACHE_HOME": str(p["xdg_cache"]), "XDG_RUNTIME_DIR": str(p["runtime_dir"]),
                "CONTAINERS_CONF": str(p["containers_conf"]),
                "CONTAINERS_REGISTRIES_CONF": str(p["registries_conf"])})
    return env


def write_configs(ctx_or_root):
    """storage.conf + containers.conf + registries.conf (offline: registries blocked) under the root."""
    p = podman_paths(ctx_or_root)
    p["conf"].parent.mkdir(parents=True, exist_ok=True)
    p["runtime_dir"].mkdir(parents=True, exist_ok=True)
    os.chmod(p["runtime_dir"], 0o700)
    p["conf"].write_text(
        "[storage]\ndriver = \"overlay\"\n"
        f"graphroot = \"{p['graphroot']}\"\nrunroot = \"{p['runroot']}\"\n")
    p["containers_conf"].write_text(
        "[containers]\n"
        "# GNS3 sends NetworkDisabled=true, which podman compat ignores; no network (GNS3/uBridge wires eth0)\n"
        "netns = \"none\"\n\n"
        "[engine]\ncgroup_manager = \"cgroupfs\"\nevents_logger = \"file\"\n"
        f"events_logfile_path = \"{p['events']}\"\ntmp_dir = \"{p['tmp_dir']}\"\n"
        "image_default_transport = \"docker://\"\n\n"
        f"[network]\nnetwork_config_dir = \"{p['networks']}\"\n")
    p["registries_conf"].write_text(
        "# VASYA: never pull — images only from `podman load -i` of shipped tars\n"
        "unqualified-search-registries = [\"docker.io\"]\nshort-name-mode = \"permissive\"\n"
        + "".join(f"[[registry]]\nlocation = \"{r}\"\nblocked = true\n" for r in BLOCKED_REGISTRIES))
    return p["conf"]


write_storage_conf = write_configs   # pre-merge name


def service_cmd(ctx):
    return ["podman", "system", "service", "--time=0", f"unix://{podman_paths(ctx)['sock']}"]


def ensure_service(ctx, popen=subprocess.Popen, wait=15):
    """Start VASYA's own podman API service (user process, pidfile under the root). No systemctl."""
    p = podman_paths(ctx)
    if p["sock"].exists() and p["pid"].exists():
        return {"status": "OK", "sock": str(p["sock"]), "reused": True}
    write_configs(ctx)
    p["sock"].parent.mkdir(parents=True, exist_ok=True)
    log = open(p["log"], "ab")
    proc = popen(service_cmd(ctx), env=podman_env(ctx), stdout=log, stderr=subprocess.STDOUT,
                 start_new_session=True)
    p["pid"].write_text(str(proc.pid))
    t0 = time.time()
    while time.time() - t0 < wait and not p["sock"].exists():
        time.sleep(0.2)
    return {"status": "OK" if p["sock"].exists() else "FAIL", "sock": str(p["sock"]), "pid": proc.pid}


def server_env(ctx):
    """Extra environment for VASYA's managed gns3server ({} = stock behaviour).
    Same rule as server.sh: only when podman is active AND the VASYA podman socket exists.
    Process-local: DOCKER_HOST makes gns3server's aux-console `docker exec` reach podman, not the shared daemon."""
    if not podman_active(ctx):
        return {}
    sock = podman_paths(ctx)["sock"]
    if not sock.exists():
        return {}
    return {SOCK_ENV: str(sock), "DOCKER_HOST": f"unix://{sock}", FIX_UID_ENV: "0", FIX_GID_ENV: "0"}


def prepare_server_env(ctx, ensure=None, restore=None, log=None):
    """Before VASYA's gns3server starts: start the podman service (when active and available), restore
    every receipted VASYA image that went missing from its offline archive, then compute server_env."""
    if podman_active(ctx) and not unavailable_reason(ctx):
        sv = (ensure or ensure_service)(ctx)
        if (sv or {}).get("status", "OK") == "OK":
            res = (restore or ensure_images)(ctx)
            if log:
                for r in res:
                    log(r)
    return server_env(ctx)


def receipted_images(ctx, engine=ENGINE_PODMAN):
    """[(base_ref, labelled_ref, block_id)] VASYA installed on `engine` and has not rolled back."""
    from ..core import txn as txnmod
    out = []
    try:
        recs = [r for r in txnmod.all_receipts(ctx.layout) if not r["rolled_back"]]
    except Exception:
        return out
    for rec in recs:
        for x in rec.get("committed", []):
            if x.get("kind") == "docker_labeled_image" and x.get("engine", ENGINE_SHARED) == engine:
                out.append((x["base"], x["ref"], x.get("block_id")))
    return out


def labelled_dockerfile(ref, block_id, root):
    from ..installer.apply import OWNER_LABEL, OWNER_VALUE, root_tag
    from . import docker_images as di
    pin = di.pin_for_ref(ref) or {}
    extra = "".join(f" org.vasya.{k}={pin[v]}" for k, v in (("base_digest", "repo_digest"), ("base_id", "image_id"))
                    if pin.get(v))
    return (f"FROM {ref}\nLABEL {OWNER_LABEL}={OWNER_VALUE} "
            f"org.vasya.block={block_id} org.vasya.base={ref}{extra} "
            f"org.vasya.root={root_tag(root)}\n")


def build_labelled(ctx, cmd, env, ref, lref, block_id, tag="lbl"):
    """podman build of the thin labelled image (context dir under the root, --pull=never)."""
    df = labelled_dockerfile(ref, block_id, ctx.layout.root)
    bdir = podman_paths(ctx)["base"] / "build" / re.sub(r"[^A-Za-z0-9._-]", "_", tag)
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "Dockerfile").write_text(df)
    try:
        return subprocess.run(cmd + ["build", "-q", "--pull=never", "-t", lref, "-f", str(bdir / "Dockerfile"),
                                     str(bdir)], env=env, capture_output=True, text=True, timeout=600)
    finally:
        shutil.rmtree(bdir, ignore_errors=True)


def ensure_images(ctx):
    """Restore missing base images from the offline archives and rebuild missing labelled images.
    Never pulls. Returns one result dict per receipted image."""
    from . import docker_images as di
    cmd, env = engine_cmd(ctx)
    if not cmd:
        return []
    run = lambda a, **k: subprocess.run(a, env=env, **k)
    out = []
    for base, lref, bid in receipted_images(ctx):
        r = di.restore(ctx, base, cmd, env=env, run=run)
        if r["status"] not in ("PRESENT", "RESTORED"):
            if not di.present(run, cmd, base):
                out.append(dict(r, labelled=lref, block_id=bid))
                continue
            r = {"status": "PRESENT", "ref": base, "note": f"{r['status']}; image still in storage"}
        if not di.present(run, cmd, lref):
            b = build_labelled(ctx, cmd, env, base, lref, bid, tag=f"restore-{bid}")
            r = dict(r, labelled=lref, labelled_status="REBUILT" if b.returncode == 0 else "BUILD_FAILED",
                     error=None if b.returncode == 0 else (b.stderr or b.stdout)[-200:])
        out.append(dict(r, labelled=lref, block_id=bid))
    return out


def engine_cmd(ctx):
    """(argv prefix, env) for image load/inspect/build on the selected backend."""
    if podman_active(ctx):
        write_configs(ctx)   # before ANY podman call: otherwise podman would default storage elsewhere
        return ["podman"], podman_env(ctx)
    return None, None


def engine_name(ctx):
    return ENGINE_PODMAN if podman_active(ctx) else ENGINE_SHARED


def podman_argv(ctx_or_root, which=None):
    """Self-contained argv prefix (`env -u ... K=V ... podman`) for call sites that run `cmd + [...]`
    without an env: the VASYA podman environment is carried in the argv, nothing else changes."""
    pm = (which or shutil.which)("podman")
    if not pm:
        return None
    full = podman_env(ctx_or_root, base={})
    return (["env", "-u", "CONTAINERS_STORAGE_CONF", "-u", "DOCKER_HOST"]
            + [f"{k}={v}" for k, v in sorted(full.items())] + [pm])


def receipt_cmd(r, root, docker_cmd):
    """argv prefix to act on a receipted image/container: podman receipts NEVER go to the shared daemon."""
    if r.get("engine") == ENGINE_PODMAN:
        root = r.get("root") or root
        # storage gone (root removed / teardown done) -> nothing can be left; never let podman re-create dirs
        return podman_argv(root) if root and podman_paths(root)["graphroot"].exists() else None
    return docker_cmd()


def _own_service_pid(p, root):
    try:
        pid = int(p["pid"].read_text().strip())
        env = Path(f"/proc/{pid}/environ").read_bytes()
    except (OSError, ValueError):
        return None
    return pid if str(root).encode() in env else None


def stop_service(ctx_or_root, timeout=10):
    """Stop VASYA's podman API service (only a process whose env names this root) and drop its socket."""
    root = _root(ctx_or_root)
    p = podman_paths(root)
    pid = _own_service_pid(p, root)
    st = "ABSENT"
    if pid:
        try:
            os.kill(pid, 15)
            t0 = time.time()
            while time.time() - t0 < timeout and Path(f"/proc/{pid}").exists():
                time.sleep(0.2)
            st = "STOPPED"
        except OSError:
            pass
    for x in (p["sock"], p["pid"]):
        try:
            x.unlink()
        except OSError:
            pass
    return st


def teardown(ctx_or_root, run=subprocess.run, which=shutil.which):
    """Full uninstall: stop VASYA's podman service (only if its env names this root) and remove the
    rootless storage via `podman unshare rm -rf` (sub-uid owned files), path-checked under the root."""
    root = _root(ctx_or_root)
    p = podman_paths(root)
    out = {"service": "ABSENT", "storage": "ABSENT"}
    if not p["base"].exists():
        return out
    out["service"] = stop_service(root)
    pm = which("podman")
    targets = [x for x in (p["graphroot"], p["runroot"], p["xdg_data"]) if x.exists()]
    for x in targets:
        assert Path(x).resolve().is_relative_to(root.resolve()), x
    if targets and pm:
        r = run([pm, "unshare", "rm", "-rf", *map(str, targets)], env=podman_env(root),
                capture_output=True, text=True)
        out["storage"] = "REMOVED" if r.returncode == 0 else "FAILED: " + (r.stderr or "")[-200:]
    elif targets:
        out["storage"] = "PODMAN_MISSING"
    return out


# ---------------------------------------------------------------- gns3server patch (build time)

def _sha(b):
    return hashlib.sha256(b).hexdigest()


def patch_state(pyroot):
    """PATCHED | LEGACY (pre-merge one-liner) | STOCK | PARTIAL for one runtime dir containing gns3server/."""
    txt = {f: (Path(pyroot) / f).read_text(encoding="utf-8") for f in PATCH_FILES}
    full = [all(m in txt[f] for m in PATCH_MARKERS[f]) for f in PATCH_FILES]
    if all(full):
        return "PATCHED"
    if any(full):
        return "PARTIAL"
    if LEGACY_SOCK_PATCH in txt[PATCH_FILES[0]]:
        return "LEGACY"
    return "STOCK"


def patch_gns3server(tree, patch_file=PATCH_FILE, patch_bin=None):
    """Apply the tested 3-part patch to every bundled gns3server under `tree` (VASYA's copies only).
    Idempotent; a pre-merge one-line patch is upgraded. Files are rewritten as NEW inodes (os.replace),
    never through a hardlink, so the build tree is never modified. Returns [(<__init__.py>, status)]."""
    patch_bin = patch_bin or shutil.which("patch")
    out = []
    for f in sorted(Path(tree).rglob(PATCH_FILES[0])):
        pyroot = f.parents[3]
        st = patch_state(pyroot)
        if st == "PATCHED":
            out.append((str(f), "ALREADY"))
            continue
        if st == "PARTIAL" or not patch_bin:
            out.append((str(f), "PARTIAL_PATCH" if st == "PARTIAL" else "NO_PATCH_TOOL"))
            continue
        with tempfile.TemporaryDirectory(prefix="vasya-patch-") as td:
            for rel in PATCH_FILES:
                d = Path(td) / rel
                d.parent.mkdir(parents=True, exist_ok=True)
                t = (pyroot / rel).read_text(encoding="utf-8")
                if rel == PATCH_FILES[0] and st == "LEGACY":
                    t = t.replace(LEGACY_SOCK_PATCH, SOCK_PATCH_OLD, 1)
                d.write_text(t, encoding="utf-8")
            r = subprocess.run([patch_bin, "-p1", "--batch", "--forward", "--no-backup-if-mismatch",
                                "-d", td, "-i", str(patch_file)], capture_output=True, text=True)
            if r.returncode != 0 or patch_state(td) != "PATCHED":
                out.append((str(f), "PATTERN_NOT_FOUND"))
                continue
            for rel in PATCH_FILES:
                dst = pyroot / rel
                tmp = dst.with_name(dst.name + ".vasya-tmp")
                tmp.write_bytes((Path(td) / rel).read_bytes())
                os.replace(tmp, dst)
        out.append((str(f), "UPGRADED" if st == "LEGACY" else "PATCHED"))
    return out


def init_su_state(pyroot):
    txt = (Path(pyroot) / INIT_SH).read_text(encoding="utf-8")
    return "PATCHED" if INIT_SU_MARKER in txt else "STOCK"


def patch_init_su(tree, patch_file=INIT_SU_PATCH_FILE, patch_bin=None):
    """Apply patch 4 to every bundled gns3server init.sh under `tree`. Idempotent; new inode (os.replace)
    with the original mode kept (init.sh must stay executable). Returns [(<init.sh>, status)]."""
    patch_bin = patch_bin or shutil.which("patch")
    out = []
    for f in sorted(Path(tree).rglob(INIT_SH)):
        pyroot = f.parents[4]
        if init_su_state(pyroot) == "PATCHED":
            out.append((str(f), "ALREADY")); continue
        if not patch_bin:
            out.append((str(f), "NO_PATCH_TOOL")); continue
        with tempfile.TemporaryDirectory(prefix="vasya-patch-") as td:
            d = Path(td) / INIT_SH
            d.parent.mkdir(parents=True)
            d.write_bytes(f.read_bytes())
            r = subprocess.run([patch_bin, "-p1", "--batch", "--forward", "--no-backup-if-mismatch",
                                "-d", td, "-i", str(patch_file)], capture_output=True, text=True)
            if r.returncode != 0 or init_su_state(td) != "PATCHED":
                out.append((str(f), "PATTERN_NOT_FOUND")); continue
            tmp = f.with_name(f.name + ".vasya-tmp")
            tmp.write_bytes(d.read_bytes())
            shutil.copymode(f, tmp)
            os.replace(tmp, f)
        out.append((str(f), "PATCHED"))
    return out


def patch_all(tree):
    """Every VASYA gns3server patch, in order. {patch name: [(file, status)]}."""
    return {PATCH_NAME: patch_gns3server(tree), INIT_SU_PATCH_NAME: patch_init_su(tree)}


def patch_record(tree, app_dir):
    """VASYA_PATCHES.json content: the patch, its sha256 and the patched files' sha256 per runtime."""
    files = {}
    for f in sorted(Path(tree).rglob(PATCH_FILES[0])):
        pyroot = f.parents[3]
        for rel in PATCH_FILES:
            q = pyroot / rel
            files[str(q.relative_to(app_dir))] = _sha(q.read_bytes())
    init_files = {}
    for f in sorted(Path(tree).rglob(INIT_SH)):
        init_files[str(f.relative_to(app_dir))] = _sha(f.read_bytes())
    return {"patch": PATCH_NAME, "patch_sha256": _sha(PATCH_FILE.read_bytes()),
            "proven": "Pop!_OS 24.04, rootless podman 4.9.3",
            "env": [SOCK_ENV, FIX_UID_ENV, FIX_GID_ENV],
            "parts": ["VASYA_DOCKER_SOCKET socket override (default /var/run/docker.sock)",
                      "attach/ws 404 -> hijacked POST attach fallback",
                      "VASYA_DOCKER_FIX_UID/GID chown target in _fix_permissions"],
            "files": files,
            "patches": [
                {"patch": PATCH_NAME, "patch_sha256": _sha(PATCH_FILE.read_bytes()), "files": files},
                {"patch": INIT_SU_PATCH_NAME, "patch_sha256": _sha(INIT_SU_PATCH_FILE.read_bytes()),
                 "proven": "Pop!_OS 24.04 (aaa, python-go-perl-php: busybox su exit 139 -> PASS)",
                 "parts": ["init.sh: GNS3_USER empty/root/0 -> exec run-cmd.sh without su; other users unchanged"],
                 "files": init_files}]}


def tar_name(ref):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", ref) + ".tar"


def offline_tar(ctx, ref):
    """docker save tar for `ref` shipped with the release, if any."""
    pr = Path(ctx.payload_root)
    for d in (pr / "docker", pr.parent / "Images" / "docker"):
        p = d / tar_name(ref)
        if p.is_file():
            return p
    return None
