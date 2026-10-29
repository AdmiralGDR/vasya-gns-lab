# SPDX-License-Identifier: GPL-3.0-or-later
import json, os, shutil, subprocess, sys, hashlib
from pathlib import Path
import pytest

# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared fixtures.

Integration tests use real external programs and build outputs only when they are pointed at them
(otherwise they are skipped):
  VASYA_GNS3SERVER_BIN  gns3server 2.2.61 executable
  VASYA_TEST_PATH       extra PATH entries (os.pathsep-separated), e.g. dirs with dynamips/ubridge/vpcs
  VASYA_TEST_GNS3RT     dir with py310..py313 gns3-server 2.2.61 builds (pip --target)
  VASYA_TEST_STAGE      a staged bundle (output dir of scripts/build_bundle.py, e.g. .../VASYA-GNS-LAB-1.1.0)
  VASYA_TEST_PACK       a full payload with images/sha256 (private profile input)
  VASYA_TEST_LEGACY, VASYA_TEST_RC_PACK, VASYA_TEST_OLD_PACK   the 1.0.1 code base (legacy checks)
Unit tests never use the network: VASYA_OFFLINE=1 and no private image sources are forced here;
the fetch tests serve their downloads from a local HTTP server.
"""
SRC = Path(__file__).resolve().parent.parent / "src"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SRC))
GNS3SERVER = os.environ.get("VASYA_GNS3SERVER_BIN", "")
if GNS3SERVER:
    os.environ["VASYA_GNS3SERVER_BIN"] = GNS3SERVER
if os.environ.get("VASYA_TEST_PATH"):
    os.environ["PATH"] = os.pathsep.join([os.environ["VASYA_TEST_PATH"], os.environ.get("PATH", "")])
os.environ["VASYA_OFFLINE"] = "1"
os.environ["VASYA_PRIVATE_SOURCES"] = "none"


def env_path(name, *sub):
    """Path from an env var (joined with `sub`), or None when the variable is not set."""
    v = os.environ.get(name)
    return Path(v, *sub) if v else None


_NONE = Path("/nonexistent/vasya-test-input")       # unset input: tests that need it skip
GNS3RT = env_path("VASYA_TEST_GNS3RT") or _NONE
STAGE_DIR = env_path("VASYA_TEST_STAGE") or _NONE
PACK_DIR = env_path("VASYA_TEST_PACK") or _NONE
# the 1.0.1 code base, only for the tests that document why 1.1.0 does not reuse it
LEGACY = env_path("VASYA_TEST_LEGACY") or _NONE           # 1.0.1 work tree (phaseA/, evidence/rollback/)
RC_PACK = env_path("VASYA_TEST_RC_PACK") or _NONE         # fixed 1.0.1 Pack (lib/rollback.py)
OLD_PACK = env_path("VASYA_TEST_OLD_PACK") or _NONE       # shipped 1.0.1 Pack
# fontconfig mmaps its cache; keeping it in a per-test fake HOME that pytest deletes made Qt
# die with SIGBUS at interpreter exit. One session-wide cache dir outside the fake homes.
os.environ.setdefault("XDG_CACHE_HOME", "/tmp/vasya-test-xdg-cache")

have_gns3 = pytest.mark.skipif(not GNS3SERVER or not Path(GNS3SERVER).exists(),
                               reason="gns3server not available (set VASYA_GNS3SERVER_BIN)")
have_docker = pytest.mark.skipif(shutil.which("docker") is None or
                                 subprocess.run(["docker", "info"], capture_output=True).returncode,
                                 reason="docker not usable")


def _blob(path, size, seed):
    h = hashlib.sha256(seed.encode()).digest()
    with open(path, "wb") as f:
        f.write(b"QFI\xfb" + b"\0" * 60)
        n = 64
        while n < size:
            f.write(h * 128); n += len(h) * 128
    return path


def make_payload(dst, n_images=3, size=2 * 1024 * 1024, docker=False, dyn_elf=False):
    dst = Path(dst)
    (dst / "images/sha256").mkdir(parents=True, exist_ok=True)
    (dst / "manifests").mkdir(parents=True, exist_ok=True)
    blocks = []
    imgs = []
    for i in range(n_images):
        tmp = dst / f"tmp{i}"
        _blob(tmp, size, f"img{i}")
        sha = hashlib.sha256(tmp.read_bytes()).hexdigest()
        os.replace(tmp, dst / "images/sha256" / sha)
        imgs.append({"logical_filename": f"t-disk{i}.qcow2", "sha256": sha,
                     "size": (dst / "images/sha256" / sha).stat().st_size,
                     "disk_slot": "hda_disk_image" if i % 2 == 0 else "hdb_disk_image"})
    for i in range(0, n_images, 2):
        bid = f"t-qemu{i}"
        app = dst / "appliances" / bid / f"{bid}.gns3a"
        app.parent.mkdir(parents=True, exist_ok=True)
        app.write_text(json.dumps({"name": bid, "category": "router", "qemu": {"ram": 64,
                                    "adapters": 2, "console_type": "telnet"}}))
        blocks.append({"block_id": bid, "name": f"VASYA Test QEMU {i}", "runtime": "qemu",
                       "category": "router", "template": f"appliances/{bid}/{bid}.gns3a",
                       "appliance_meta_ok": True, "images": imgs[i:i + 2], "docker_image": None})
    dyn = dst / "appliances/t-dyn/t-dyn.gns3a"
    dyn.parent.mkdir(parents=True, exist_ok=True)
    dyn.write_text(json.dumps({"name": "t-dyn", "category": "router",
                               "dynamips": {"platform": "c7200", "ram": 256}}))
    dyn_img = imgs[-1]
    if dyn_elf:  # GNS3 only lists IOS images that are 32-bit big-endian ELF files
        tmp = dst / "tmp-ios"
        tmp.write_bytes(b"\x7fELF\x01\x02\x01" + b"\0" * 9 + hashlib.sha256(b"ios").digest() * 4096)
        sha = hashlib.sha256(tmp.read_bytes()).hexdigest()
        os.replace(tmp, dst / "images/sha256" / sha)
        dyn_img = {"logical_filename": "t-ios.image", "sha256": sha,
                   "size": (dst / "images/sha256" / sha).stat().st_size}
    blocks.append({"block_id": "t-dyn", "name": "VASYA Test Dynamips", "runtime": "dynamips",
                   "category": "router", "template": "appliances/t-dyn/t-dyn.gns3a",
                   "appliance_meta_ok": True, "images": [dyn_img], "docker_image": None})
    if docker:
        d = dst / "appliances/t-docker/t-docker.gns3a"
        d.parent.mkdir(parents=True, exist_ok=True)
        d.write_text(json.dumps({"name": "t-docker", "category": "multilayer_switch",
                                 "docker": {"adapters": 2, "console_type": "telnet"}}))
        blocks.append({"block_id": "t-docker", "name": "VASYA Test Docker", "runtime": "docker",
                       "category": "multilayer_switch", "template": "appliances/t-docker/t-docker.gns3a",
                       "appliance_meta_ok": True, "images": [], "docker_image": "alpine:latest"})
    (dst / "manifests/pack.json").write_text(json.dumps({"product_version": "1.1.0-test",
                                                        "blocks": blocks}))
    return dst


@pytest.fixture
def payload(tmp_path):
    return make_payload(tmp_path / "payload")


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Never touch the real ~/.local/share/applications or ~/.config of the user running the tests."""
    h = tmp_path / "home"
    h.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    return h


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "VASYA-ROOT"
    yield r
    _teardown_root(r)


def _teardown_root(r, payload=None):
    """Even when a test fails, undo everything it installed (no stray servers/images)."""
    from vasya.runtime import managed_server as ms
    from vasya.core.layout import Layout
    if Path(r).exists() and (Path(r) / "State").exists():
        try:
            from vasya import api
            api.uninstall(api.open_ctx(r, payload or Path(r)), "full")
        except Exception:
            pass
    ms.stop(Layout(r))


@pytest.fixture
def ctx(root, payload):
    from vasya import api
    return api.open_ctx(root, payload)


def cli(root, payload, *args, env=None, check=False):
    e = dict(os.environ, PYTHONPATH=str(SRC))
    e.update(env or {})
    r = subprocess.run([sys.executable, "-m", "vasya", "--root", str(root), "--payload", str(payload),
                        "--json", *args], capture_output=True, text=True, env=e, timeout=900)
    if check:
        assert r.returncode == 0, r.stdout + r.stderr
    return r


@pytest.fixture
def shared_daemon(monkeypatch):
    """Tests that exercise the shared-daemon backend explicitly (the Linux default is rootless podman)."""
    monkeypatch.setenv("VASYA_DOCKER_BACKEND", "shared-daemon")
    return "shared-daemon"
