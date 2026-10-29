# SPDX-License-Identifier: GPL-3.0-or-later
"""Automatic acquisition (vasya.fetch): pinned public downloads, private image sources and the
"image not available" path. Everything is served from a local HTTP server; no internet needed."""
import bz2, gzip, hashlib, http.server, io, json, os, subprocess, tarfile, threading, zipfile
from pathlib import Path
import pytest
from conftest import make_payload
from vasya import api
from vasya.fetch import download, images as fimages, lock as L, prepare as fprepare, private, tools as ftools, unpack
from vasya.runtime import docker_images as di, gui_deps as gd

H = lambda b: hashlib.sha256(b).hexdigest()


# ------------------------------------------------------------------ helpers
class _Handler(http.server.SimpleHTTPRequestHandler):
    token = None
    hits = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        _Handler.hits.append(self.path)
        if self.path.startswith("/private/") and self.headers.get("Authorization") != f"Bearer {self.token}":
            self.send_error(401)
            return
        super().do_GET()


@pytest.fixture
def server(tmp_path):
    root = tmp_path / "www"
    root.mkdir()
    _Handler.hits = []
    h = lambda *a, **k: _Handler(*a, directory=str(root), **k)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield root, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture
def online(monkeypatch):
    monkeypatch.setenv("VASYA_OFFLINE", "0")


def _ar(members):
    out = io.BytesIO()
    out.write(b"!<arch>\n")
    for name, data in members:
        out.write(f"{name:<16}{0:<12}{0:<6}{0:<6}{100644:<8}{len(data):<10}`\n".encode())
        out.write(data + (b"\n" if len(data) & 1 else b""))
    return out.getvalue()


def make_deb(files):
    """A minimal Debian package: {member path: bytes} in data.tar.xz."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tf:
        for path, data in files.items():
            ti = tarfile.TarInfo("./" + path)
            ti.size, ti.mode = len(data), 0o755
            tf.addfile(ti, io.BytesIO(data))
    return _ar([("debian-binary", b"2.0\n"), ("control.tar.xz", b""), ("data.tar.xz", buf.getvalue())])


def _lock(tmp_path, monkeypatch, data):
    p = tmp_path / "third_party.lock"
    base = {"format": 1, "tools": {}, "libraries": {}, "images": {}, "docker": {}}
    base.update(data)
    p.write_text(json.dumps(base))
    monkeypatch.setattr(L, "LOCK", p)
    return base


def _ctx(tmp_path, **kw):
    return api.open_ctx(tmp_path / "R", make_payload(tmp_path / "p", **kw))


def _drop(ctx, i=0):
    """Remove one image from the payload so it has to be fetched. Returns (sha, bytes, block)."""
    b = ctx.blocks()[0]
    im = b["images"][i]
    p = ctx.payload.image_path(im["sha256"])
    data = p.read_bytes()
    p.unlink()
    return im["sha256"], data, b


# ------------------------------------------------------------------ download / unpack
def test_download_tries_mirrors_and_verifies(tmp_path, server, online):
    www, url = server
    (www / "good.bin").write_bytes(b"x" * 1000)
    (www / "bad.bin").write_bytes(b"y" * 1000)
    dst = tmp_path / "out.bin"
    r = download.fetch([f"{url}/missing.bin", f"{url}/bad.bin", f"{url}/good.bin"], dst, H(b"x" * 1000), size=1000)
    assert r["status"] == "OK" and r["url"].endswith("/good.bin") and dst.read_bytes() == b"x" * 1000
    assert len(r["errors"]) == 2 and "sha256" in r["errors"][1]
    assert download.fetch([f"{url}/good.bin"], dst, H(b"x" * 1000), size=1000)["reused"] is True
    r = download.fetch([f"{url}/bad.bin"], tmp_path / "o2", H(b"x" * 1000))
    assert r["status"] == "FAIL" and not (tmp_path / "o2").exists() and not list(tmp_path.glob("o2*"))


def test_download_is_refused_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("VASYA_OFFLINE", "1")
    assert download.fetch(["http://127.0.0.1:9/x"], tmp_path / "x", "0" * 64)["status"] == "OFFLINE"


def test_unpack_formats(tmp_path):
    data = os.urandom(5000)
    (tmp_path / "a.gz").write_bytes(gzip.compress(data))
    (tmp_path / "a.bz2").write_bytes(bz2.compress(data))
    with zipfile.ZipFile(tmp_path / "a.zip", "w") as z:
        z.writestr("readme.txt", "x")
        z.writestr("dir/disk.img", data)
    for name, comp, member in (("a.gz", "gzip", None), ("a.bz2", "bzip2", None), ("a.zip", "zip", "disk.img"),
                               ("a.zip", "zip", None)):
        out = unpack.decompress(tmp_path / name, tmp_path / f"out-{name}-{member}", comp, member)
        assert out.read_bytes() == data
    deb = tmp_path / "t.deb"
    deb.write_bytes(make_deb({"usr/bin/tool": b"#!/bin/sh\necho hi\n"}))
    out = unpack.deb_extract(deb, "usr/bin/tool", tmp_path / "tool")
    assert out.read_bytes().startswith(b"#!/bin/sh") and os.access(out, os.X_OK)
    with pytest.raises(FileNotFoundError):
        unpack.deb_extract(deb, "usr/bin/other", tmp_path / "other")


# ------------------------------------------------------------------ tools and libraries
def _tool_lock(tmp_path, monkeypatch, url, deb, member_data, name="vpcs"):
    return _lock(tmp_path, monkeypatch, {"tools": {name: {"version": "0.8.5", "package": {
        "urls": [f"{url}/missing.deb", f"{url}/{name}.deb"], "sha256": H(deb), "size": len(deb),
        "member": f"usr/bin/{name}", "member_sha256": H(member_data)}}}})


def test_tool_is_fetched_verified_and_placed_with_receipt(tmp_path, server, online, monkeypatch):
    www, url = server
    body = b"\x7fELF fake vpcs"
    deb = make_deb({"usr/bin/vpcs": body})
    (www / "vpcs.deb").write_bytes(deb)
    _tool_lock(tmp_path, monkeypatch, url, deb, body)
    ctx = _ctx(tmp_path)
    r = gd.ensure_tool(ctx, "vpcs", which=lambda n: None)
    assert r["status"] == "OK" and r["source"] == "vasya-fetched", r
    placed = gd.runtime_bin(ctx) / "vpcs"
    assert placed.read_bytes() == body and os.access(placed, os.X_OK)
    rec = json.loads(gd.receipt_path(ctx).read_text())
    assert any(k.endswith("vpcs") for k in rec["files"])
    # second run: nothing downloaded again
    n = len(_Handler.hits)
    assert ftools.staged(ctx.layout, "vpcs")["reused"] is True and len(_Handler.hits) == n


def test_system_tool_wins_and_is_never_touched(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    r = gd.ensure_tool(ctx, "vpcs", which=lambda n: "/usr/bin/vpcs")
    assert r == {"status": "OK", "path": "/usr/bin/vpcs", "source": "system"}
    assert not (gd.runtime_bin(ctx) / "vpcs").exists()


def test_tampered_package_is_rejected(tmp_path, server, online, monkeypatch):
    www, url = server
    body = b"\x7fELF fake vpcs"
    deb = make_deb({"usr/bin/vpcs": body})
    _tool_lock(tmp_path, monkeypatch, url, deb, body)
    (www / "vpcs.deb").write_bytes(make_deb({"usr/bin/vpcs": b"evil"}))
    ctx = _ctx(tmp_path)
    r = gd.ensure_tool(ctx, "vpcs", which=lambda n: None)
    assert r["status"] == "BLOCKED" and ("sha256" in r["reason"] or "size" in r["reason"])
    assert not (gd.runtime_bin(ctx) / "vpcs").exists()


def test_tampered_member_is_rejected(tmp_path, server, online, monkeypatch):
    www, url = server
    deb = make_deb({"usr/bin/vpcs": b"other content"})
    (www / "vpcs.deb").write_bytes(deb)
    _tool_lock(tmp_path, monkeypatch, url, deb, b"expected content")
    r = ftools.staged(_ctx(tmp_path).layout, "vpcs")
    assert r["status"] == "FAIL" and "does not match" in r["reason"]


def test_unpinned_tool_is_unknown(tmp_path, monkeypatch):
    _lock(tmp_path, monkeypatch, {})
    assert ftools.staged(_ctx(tmp_path).layout, "vpcs")["status"] == "UNKNOWN"


def test_prepare_fetches_helpers_for_the_selection(tmp_path, server, online, monkeypatch):
    www, url = server
    lk = {"tools": {}}
    for n in ("ubridge", "vpcs", "dynamips"):
        body = f"\x7fELF {n}".encode()
        deb = make_deb({f"usr/bin/{n}": body})
        (www / f"{n}.deb").write_bytes(deb)
        lk["tools"][n] = {"package": {"urls": [f"{url}/{n}.deb"], "sha256": H(deb), "size": len(deb),
                                      "member": f"usr/bin/{n}", "member_sha256": H(body)}}
    _lock(tmp_path, monkeypatch, lk)
    monkeypatch.setattr(gd, "_which", lambda n: None)
    for v in ("VASYA_DYNAMIPS_BIN", "VASYA_UBRIDGE_BIN"):
        monkeypatch.delenv(v, raising=False)
    ctx = _ctx(tmp_path)
    if ctx.platform.name != "linux":
        pytest.skip("helpers are fetched on Linux only")
    rep = fprepare.prepare(ctx, block_ids=["t-qemu0"], images=False)
    assert set(rep["tools"]) == {"ubridge", "vpcs"}
    rep = fprepare.prepare(ctx, block_ids=["t-dyn"], images=False)
    assert rep["tools"]["dynamips"]["status"] == "OK"
    assert os.environ["VASYA_DYNAMIPS_BIN"] == str(gd.runtime_bin(ctx) / "dynamips")


# ------------------------------------------------------------------ public images
@pytest.mark.parametrize("comp", [None, "gzip", "bzip2", "zip"])
def test_public_image_is_fetched_into_the_user_store(tmp_path, server, online, monkeypatch, comp):
    www, url = server
    ctx = _ctx(tmp_path)
    sha, data, b = _drop(ctx)
    e = {"filename": "disk.qcow2", "size": len(data)}
    if comp is None:
        (www / "disk.qcow2").write_bytes(data)
        e["urls"] = [f"{url}/nope", f"{url}/disk.qcow2"]
    else:
        blob = {"gzip": gzip.compress, "bzip2": bz2.compress}.get(comp)
        if blob:
            arc = blob(data)
        else:
            z = io.BytesIO()
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr("disk.qcow2", data)
            arc = z.getvalue()
        (www / "disk.arc").write_bytes(arc)
        e.update(urls=[f"{url}/disk.arc"], compression=comp, download_sha256=H(arc), download_size=len(arc),
                 archive_member="disk.qcow2" if comp == "zip" else None)
    _lock(tmp_path, monkeypatch, {"images": {sha: e}})
    rep = fimages.ensure(ctx, [b["block_id"]], use_private=False)
    assert rep["fetched"] == [sha] and rep["not_available"] == []
    p = ctx.payload.image_path(sha)
    assert p.exists() and H(p.read_bytes()) == sha and str(ctx.layout.user_store) in str(p)
    assert not list(download.cache_dir(ctx.layout).rglob("disk.arc"))      # archive removed
    assert json.loads((ctx.layout.State / "fetch-report.json").read_text())["fetched"] == [sha]
    # the plan now uses the fetched image
    ops = api.plan(ctx, "FULL", block_ids=[b["block_id"]])["operations"]
    assert not [o for o in ops if o["action"] == "IMAGE_NOT_AVAILABLE"]


def test_wrong_public_image_is_not_available(tmp_path, server, online, monkeypatch):
    www, url = server
    ctx = _ctx(tmp_path)
    sha, data, b = _drop(ctx)
    (www / "disk.qcow2").write_bytes(data[:-1] + b"!")
    _lock(tmp_path, monkeypatch, {"images": {sha: {"urls": [f"{url}/disk.qcow2"], "size": len(data)}}})
    rep = fimages.ensure(ctx, [b["block_id"]], use_private=False)
    assert rep["not_available"] == [sha] and not ctx.payload.image_path(sha).exists()


# ------------------------------------------------------------------ "image not available"
def test_missing_image_skips_only_that_device(tmp_path, monkeypatch):
    _lock(tmp_path, monkeypatch, {})
    ctx = _ctx(tmp_path)
    sha, _, b = _drop(ctx)
    rep = fprepare.prepare(ctx, tools=False)
    assert sha in rep["images"]["not_available"]
    p = api.plan(ctx, "FULL")
    na = [o for o in p["operations"] if o["action"] == "IMAGE_NOT_AVAILABLE"]
    assert [o["block_id"] for o in na] == [b["block_id"]]
    assert p["preview"]["images_not_available"][0]["block_id"] == b["block_id"]
    others = [o for o in p["operations"] if o.get("block_id") not in (None, b["block_id"])]
    assert others, "the other devices are still installed"
    from vasya.installer.apply import Applier
    st, info = Applier.op_image_not_available(None, na[0])
    assert st == "BLOCKED" and info["code"] == "IMAGE_NOT_AVAILABLE"


# ------------------------------------------------------------------ private sources
def _manifest(blocks):
    return {"format": 1, "blocks": blocks}


def _private_block(data, name="r1.image", bid="vendor-router"):
    return {"block_id": bid, "name": "Vendor Router", "vendor": "Vendor", "category": "router",
            "runtime": "dynamips", "images": [{"logical_filename": name, "sha256": H(data), "size": len(data)}],
            "appliance": {"name": "Vendor Router", "category": "router", "dynamips": {"platform": "c7200", "ram": 256}}}


def test_source_list_from_env_config_and_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("VASYA_PRIVATE_SOURCES", "/srv/img; gh:someone/private@v1 ;https://h.example/x/")
    assert private.sources() == [{"type": "dir", "path": "/srv/img"},
                                 {"type": "github-release", "repo": "someone/private", "tag": "v1"},
                                 {"type": "https", "url": "https://h.example/x/"}]
    monkeypatch.setenv("VASYA_PRIVATE_SOURCES", "none")
    assert private.sources() == []
    monkeypatch.delenv("VASYA_PRIVATE_SOURCES")
    cf = tmp_path / "ps.json"
    cf.write_text(json.dumps({"sources": [{"type": "dir", "path": "~/x"}]}))
    monkeypatch.setenv("VASYA_PRIVATE_SOURCES_FILE", str(cf))
    assert private.sources() == [{"type": "dir", "path": "~/x"}]
    monkeypatch.setenv("VASYA_PRIVATE_SOURCES_FILE", str(tmp_path / "absent.json"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home" / "VASYA-GNS-LAB" / "Images").mkdir(parents=True)
    monkeypatch.setenv("VASYA_OFFLINE", "0")
    monkeypatch.setattr(private, "_gh", lambda run=None: "someone")
    assert private.sources() == [{"type": "dir", "path": str(tmp_path / "home/VASYA-GNS-LAB/Images")},
                                 {"type": "github-release", "repo": "someone/vasya-gns-lab-private", "tag": "images"}]
    assert private.describe({"type": "https", "url": "https://u:p@h.example/x/?t=1"}) == "https://h.example/x/"


def test_private_folder_source_adds_device_and_image(tmp_path, monkeypatch):
    _lock(tmp_path, monkeypatch, {})
    data = os.urandom(3000)
    src = tmp_path / "private"
    (src / "dynamips").mkdir(parents=True)
    (src / "dynamips" / "r1.image").write_bytes(data)
    (src / private.MANIFEST).write_text(json.dumps(_manifest([_private_block(data)])))
    monkeypatch.setenv("VASYA_PRIVATE_SOURCES", str(src))
    ctx = _ctx(tmp_path)
    rep = fimages.ensure(ctx)
    assert rep["private_manifest"]["status"] == "OK" and rep["fetched"] == [H(data)]
    assert ctx.payload.image_path(H(data)).read_bytes() == data
    assert (src / "dynamips" / "r1.image").exists()                  # the source is only read
    b = ctx.block("vendor-router")
    assert b and b["private"] and ctx.appliance_json(b)["dynamips"]["platform"] == "c7200"
    # offline later: the cached manifest still provides the device
    monkeypatch.setenv("VASYA_PRIVATE_SOURCES", "none")
    assert private.sync_manifest(ctx.layout)["status"] == "CACHED"
    assert any(x["block_id"] == "vendor-router" for x in api.open_ctx(tmp_path / "R", ctx.payload.root).blocks())


def test_private_image_with_wrong_checksum_is_not_used(tmp_path, monkeypatch):
    _lock(tmp_path, monkeypatch, {})
    data = os.urandom(3000)
    src = tmp_path / "private"
    src.mkdir()
    (src / "r1.image").write_bytes(b"not the licensed image")
    (src / private.MANIFEST).write_text(json.dumps(_manifest([_private_block(data)])))
    monkeypatch.setenv("VASYA_PRIVATE_SOURCES", str(src))
    ctx = _ctx(tmp_path)
    rep = fimages.ensure(ctx)
    assert rep["not_available"] == [H(data)] and "does not match" in rep["images"][H(data)]["reason"]
    ops = api.plan(ctx, "FULL")["operations"]
    assert any(o["action"] == "IMAGE_NOT_AVAILABLE" and o["block_id"] == "vendor-router" for o in ops)


def test_no_private_source_never_fails(tmp_path, monkeypatch):
    _lock(tmp_path, monkeypatch, {})
    monkeypatch.setenv("VASYA_PRIVATE_SOURCES", str(tmp_path / "does-not-exist"))
    ctx = _ctx(tmp_path)
    rep = fimages.ensure(ctx)
    assert rep["private_manifest"]["status"] == "NONE" and rep["not_available"] == []


def test_private_https_source_sends_the_token(tmp_path, server, online, monkeypatch):
    www, url = server
    _lock(tmp_path, monkeypatch, {})
    data = os.urandom(2000)
    (www / "private").mkdir()
    (www / "private" / "r1.image").write_bytes(data)
    (www / "private" / private.MANIFEST).write_text(json.dumps(_manifest([_private_block(data)])))
    _Handler.token = "s3cret"
    monkeypatch.setenv("VASYA_PRIVATE_SOURCES", f"{url}/private/")
    ctx = _ctx(tmp_path)
    assert fimages.ensure(ctx)["private_manifest"]["status"] == "NONE"     # no token -> 401
    monkeypatch.setenv("VASYA_PRIVATE_TOKEN", "s3cret")
    rep = fimages.ensure(ctx)
    assert rep["fetched"] == [H(data)] and "s3cret" not in json.dumps(rep)
    assert not list((download.cache_dir(ctx.layout) / "private").glob("r1.image"))


def test_private_github_release_uses_gh(tmp_path, online, monkeypatch):
    _lock(tmp_path, monkeypatch, {})
    data = os.urandom(2000)
    assets = {private.MANIFEST: json.dumps(_manifest([_private_block(data)])).encode(), "r1.image": data}
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if cmd[1:3] == ["release", "download"]:
            name, d = cmd[cmd.index("-p") + 1], Path(cmd[cmd.index("-D") + 1])
            if name in assets:
                d.mkdir(parents=True, exist_ok=True)
                (d / name).write_bytes(assets[name])
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return subprocess.CompletedProcess(cmd, 1, "", "asset not found")
        return subprocess.CompletedProcess(cmd, 1, "", "")
    monkeypatch.setattr(private.shutil, "which", lambda n: "/usr/bin/gh" if n == "gh" else None)
    monkeypatch.setenv("VASYA_PRIVATE_SOURCES", "gh:someone/vasya-gns-lab-private@images")
    ctx = _ctx(tmp_path)
    rep = fimages.ensure(ctx, run=fake_run)
    assert rep["fetched"] == [H(data)]
    dl = [c for c in calls if c[1:3] == ["release", "download"]]
    assert all(c[3] == "images" and c[c.index("-R") + 1] == "someone/vasya-gns-lab-private" for c in dl)
    assert ctx.payload.image_path(H(data)).read_bytes() == data


# ------------------------------------------------------------------ docker pins
class FakeEngine:
    def __init__(self, pulled_id):
        self.images, self.pulled_id, self.calls = {}, pulled_id, []

    def __call__(self, a, **k):
        self.calls.append(a)
        sub = a[1:]
        if sub[:2] == ["image", "inspect"]:
            ref = sub[-1]
            return subprocess.CompletedProcess(a, 0 if ref in self.images else 1, self.images.get(ref, ""), "")
        if sub[0] == "pull":
            self.images[sub[-1]] = self.pulled_id
            return subprocess.CompletedProcess(a, 0, "", "")
        if sub[0] == "tag":
            self.images[sub[2]] = self.pulled_id
            return subprocess.CompletedProcess(a, 0, "", "")
        if sub[0] == "rmi":
            self.images.pop(sub[1], None)
            return subprocess.CompletedProcess(a, 0, "", "")
        return subprocess.CompletedProcess(a, 1, "", "")


def _pin():
    pin = next(e for e in di.builtin_entries() if e.get("repo_digest") and e.get("image_id"))
    return pin, pin["refs"][0]


def test_docker_pull_is_by_digest_and_checks_the_image_id(tmp_path, online, monkeypatch):
    monkeypatch.delenv("VASYA_DOCKER_PULL", raising=False)
    pin, ref = _pin()
    eng = FakeEngine(pin["image_id"])
    r = di.pull_pinned(None, ref, ["docker"], run=eng)
    assert r["status"] == "PULLED" and "@sha256:" in r["pinned"]
    pulls = [c for c in eng.calls if c[1] == "pull"]
    assert pulls == [["docker", "pull", "--quiet", di.pinned_source(pin)]]
    assert di.pull_pinned(None, ref, ["docker"], run=eng)["status"] == "PRESENT"


def test_docker_pull_with_wrong_id_is_removed(tmp_path, online, monkeypatch):
    pin, ref = _pin()
    eng = FakeEngine("sha256:" + "0" * 64)
    r = di.pull_pinned(None, ref, ["docker"], run=eng)
    assert r["status"] == "ID_MISMATCH" and di.pinned_source(pin) not in eng.images
    assert not [c for c in eng.calls if c[1] == "tag"]


def test_docker_pull_respects_offline_and_opt_out(monkeypatch):
    pin, ref = _pin()
    monkeypatch.setenv("VASYA_OFFLINE", "1")
    assert di.pull_pinned(None, ref, ["docker"], run=FakeEngine(pin["image_id"]))["status"] == "OFFLINE"
    monkeypatch.setenv("VASYA_OFFLINE", "0")
    monkeypatch.setenv("VASYA_DOCKER_PULL", "0")
    assert di.pull_pinned(None, ref, ["docker"], run=FakeEngine(pin["image_id"]))["status"] == "OFFLINE"
    assert di.pull_pinned(None, "nobody/unpinned:latest", ["docker"])["status"] == "NO_PIN"


def test_pinned_sources_are_official_registries():
    for e in di.builtin_entries():
        src = di.pinned_source(e)
        if src:
            assert src.split("/", 1)[0] in di.PULL_REGISTRIES and "@sha256:" in src, src


def test_podman_pull_uses_a_separate_registries_conf(tmp_path, monkeypatch):
    from vasya.runtime import docker_backend as dbk
    monkeypatch.delenv("VASYA_DOCKER_BACKEND", raising=False)
    ctx = api.open_ctx(tmp_path / "R", make_payload(tmp_path / "p", docker=True))
    p = di.pull_registries_conf(ctx)
    txt = p.read_text()
    assert p != dbk.podman_paths(ctx)["registries_conf"]
    for r in di.PULL_REGISTRIES:
        assert f'location = "{r}"' not in txt
    assert 'short-name-mode = "enforcing"' in txt and "unqualified-search-registries = []" in txt
