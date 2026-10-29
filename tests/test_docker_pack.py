# SPDX-License-Identifier: GPL-3.0-or-later
"""Separate Docker image pack (VASYA-GNS-LAB-<ver>-Docker-Images): built from tested archives as hardlinks,
streamed into < 100 MB parts; Setup.sh auto-detects it, verifies the parts, joins and unpacks only the pinned
files into <VASYA>/Images/docker; absent pack -> clear message, Docker components 'image pack missing'."""
import hashlib, io, json, os, subprocess, sys, tarfile
from pathlib import Path
import pytest
from vasya.delivery import parts as P
from vasya.delivery.bootstrap import make_setup_script, docker_pack_spec
from vasya.runtime import docker_images as di
from vasya import VERSION

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_docker_pack as bdp  # noqa: E402

TOP = "VASYA-GNS-LAB-9.9.9"
pytestmark = pytest.mark.skipif(not __import__("shutil").which("zstd"), reason="zstd missing")


def _core(tmp):
    src = tmp / "src" / TOP
    (src / "Payload" / "manifests").mkdir(parents=True)
    (src / "Payload" / "manifests" / "pack.json").write_text("{}")
    (src / "BUNDLE_MANIFEST.json").write_text("{}")
    (src / "install.sh").write_text("#!/bin/sh\necho INSTALLER-RAN > \"$HOME/ran.txt\"\n"); (src / "install.sh").chmod(0o755)
    arc = tmp / "rel" / f"{TOP}-Linux.tar.zst"; arc.parent.mkdir()
    subprocess.run(f"tar -C {tmp/'src'} -cf - {TOP} | zstd -q -o {arc}", shell=True, check=True)
    return P.split(arc, tmp / "drive", 64 * 1024, {"version": "9.9.9", "top_dir": TOP, "extracted_bytes": 1000})


def _store(tmp):
    s = tmp / "store"; s.mkdir()
    pins = []
    for i, n in enumerate(("a-111111111111.tar.zst", "b-222222222222.tar.zst", "c-333333333333.tar.zst")):
        b = os.urandom(50_000 + i * 70_000)
        (s / n).write_bytes(b)
        pins.append({"archive": n, "archive_sha256": hashlib.sha256(b).hexdigest(), "archive_bytes": len(b)})
    side = {"a-111111111111.tar.zst.sha256": b"x  Images/docker/a\n", "index.json": b'{"a": 1}\n'}
    for n, b in side.items():
        (s / n).write_bytes(b)
    return s, docker_pack_spec(pins, side, "9.9.9")


def _pack(tmp, monkeypatch, part=40_000):
    s, D = _store(tmp)
    monkeypatch.setattr(bdp, "spec", lambda: D)
    out = tmp / "drive-docker" / D["pack"]
    monkeypatch.setattr(sys, "argv", ["x", "--src", str(s), "--stage", str(tmp / "stage-docker"), "--out", str(out),
                                      "--part-size", str(part)])
    bdp.main()
    return s, D, out


def _setup(tmp, D):
    man = _core(tmp)
    script = tmp / "drive" / "setup.sh"
    script.write_text(make_setup_script(man, "setup.sh", D))
    return script


def _run(script, home, *args):
    env = dict(os.environ, HOME=str(home), LANG="en_US.UTF-8"); env.pop("VASYA_ROOT", None)
    return subprocess.run(["sh", str(script), "--dest", str(home), "--no-install", *args], capture_output=True,
                          text=True, env=env, cwd=home, timeout=120)


def test_split_stream_equals_split(tmp_path):
    b = os.urandom(300_000); f = tmp_path / "x.bin"; f.write_bytes(b)
    m1 = P.split(f, tmp_path / "a", 70_000)
    m2 = P.split_stream(io.BytesIO(b), "x.bin", tmp_path / "b", 70_000)
    assert m1 == m2 and m1["sha256"] == hashlib.sha256(b).hexdigest() and len(m1["parts"]) == 5


def test_pack_build_hardlinks_parts_and_sums(tmp_path, monkeypatch):
    s, D, out = _pack(tmp_path, monkeypatch)
    stage = tmp_path / "stage-docker" / D["top_dir"] / "Images" / "docker"
    for n in D["files"]:
        assert os.stat(stage / n).st_ino == os.stat(s / n).st_ino      # stored once
    man = json.loads((out / f"{D['archive']}.parts.json").read_text())
    assert man["kind"] == "docker-images" and all(p["size"] <= 40_000 for p in man["parts"])
    assert not (out / D["archive"]).exists()                            # no whole .tar on disk
    joined = b"".join((out / p["name"]).read_bytes() for p in man["parts"])
    assert hashlib.sha256(joined).hexdigest() == man["sha256"]
    with tarfile.open(fileobj=io.BytesIO(joined)) as tf:
        names = sorted(m.name for m in tf if m.isfile())
    assert names == sorted([f"{D['top_dir']}/PACK.json"] + [f"{D['top_dir']}/Images/docker/{n}" for n in D["files"]])
    r = subprocess.run(["sha256sum", "-c", f"{D['pack']}.SHA256SUMS", "--ignore-missing"], cwd=out,
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.count(": OK") == len(man["parts"]) + 1


def test_pack_build_refuses_missing_or_bad_archives(tmp_path, monkeypatch):
    s, D = _store(tmp_path)
    (s / "b-222222222222.tar.zst").write_bytes(b"tampered")
    (s / "c-333333333333.tar.zst").unlink()
    monkeypatch.setattr(bdp, "spec", lambda: D)
    monkeypatch.setattr(sys, "argv", ["x", "--src", str(s), "--stage", str(tmp_path / "st"), "--out", str(tmp_path / "o")])
    with pytest.raises(SystemExit) as e:
        bdp.main()
    assert "SIZE b-222222222222.tar.zst" in str(e.value) and "MISSING c-333333333333.tar.zst" in str(e.value)
    assert not (tmp_path / "o").exists()


def test_pack_build_respects_12gib_floor(tmp_path, monkeypatch):
    s, D = _store(tmp_path)
    monkeypatch.setattr(bdp, "spec", lambda: D)
    monkeypatch.setattr(bdp, "FLOOR", 1 << 62)
    monkeypatch.setattr(sys, "argv", ["x", "--src", str(s), "--stage", str(tmp_path / "st"), "--out", str(tmp_path / "o")])
    with pytest.raises(SystemExit) as e:
        bdp.main()
    assert "12 GiB floor" in str(e.value) and not (tmp_path / "st").exists()


def test_setup_detects_verifies_joins_into_vasya_images_docker(tmp_path, monkeypatch):
    s, D, out = _pack(tmp_path, monkeypatch)
    script = _setup(tmp_path, D)
    home = tmp_path / "home"; home.mkdir(exist_ok=True)
    r = _run(script, home, "--search", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    dst = home / "VASYA-GNS-LAB" / "Images" / "docker"
    assert sorted(p.name for p in dst.iterdir()) == sorted(D["files"])
    for n in D["files"]:
        assert (dst / n).read_bytes() == (s / n).read_bytes()
    assert "Found the Docker image pack" in r.stdout and "5 files verified (SHA-256)" in r.stdout
    assert (home / TOP / "install.sh").exists()
    r2 = _run(script, home, "--search", str(out))
    assert "Docker images already in place" in r2.stdout


def test_setup_finds_pack_in_sibling_drive_folder_and_custom_root(tmp_path, monkeypatch):
    s, D, out = _pack(tmp_path, monkeypatch)
    script = _setup(tmp_path, D)
    sib = tmp_path / D["pack"]; out.rename(sib)          # <release>/drive  and  <release>/<pack>
    home = tmp_path / "home"; home.mkdir(exist_ok=True)
    r = _run(script, home, "--root", str(tmp_path / "R"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(list((tmp_path / "R" / "Images" / "docker").iterdir())) == 5


def test_setup_without_pack_says_image_pack_missing(tmp_path):
    _, D = _store(tmp_path)
    script = _setup(tmp_path, D)
    home = tmp_path / "home"; home.mkdir(exist_ok=True)
    r = _run(script, home)
    assert r.returncode == 0 and "image pack missing" in r.stdout and D["pack"] in r.stdout
    assert (home / TOP / "install.sh").exists() and not (home / "VASYA-GNS-LAB").exists()


def test_setup_corrupt_part_installs_nothing_from_pack(tmp_path, monkeypatch):
    s, D, out = _pack(tmp_path, monkeypatch)
    script = _setup(tmp_path, D)
    man = json.loads((out / f"{D['archive']}.parts.json").read_text())
    bad = out / man["parts"][1]["name"]; bad.write_bytes(b"X" + bad.read_bytes()[1:])
    home = tmp_path / "home"; home.mkdir(exist_ok=True)
    r = _run(script, home, "--search", str(out))
    assert r.returncode == 7 and bad.name in r.stdout and "Nothing from the pack was installed" in r.stdout
    assert not (home / "VASYA-GNS-LAB" / "Images" / "docker").exists() or \
        not any((home / "VASYA-GNS-LAB" / "Images" / "docker").iterdir())


def _evil_pack(tmp, D, members):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, b in members:
            ti = tarfile.TarInfo(name); ti.size = len(b); tf.addfile(ti, io.BytesIO(b))
    out = tmp / "evil"; out.mkdir()
    P.split_stream(io.BytesIO(buf.getvalue()), D["archive"], out, 40_000)   # parts.json consistent with content
    return out


@pytest.mark.parametrize("case", ["tampered", "traversal", "missing"])
def test_setup_trusts_only_pinned_files(tmp_path, case):
    s, D = _store(tmp_path)
    pre = f"{D['top_dir']}/Images/docker/"
    mem = [(pre + n, (s / n).read_bytes()) for n in D["files"]]
    if case == "tampered":
        mem[0] = (mem[0][0], b"evil" + mem[0][1][4:])
    elif case == "traversal":
        mem.append((pre + "../../../../evil.sh", b"rm -rf ~"))
    else:
        mem = mem[1:]
    out = _evil_pack(tmp_path, D, mem)
    script = _setup(tmp_path, D)
    home = tmp_path / "home"; home.mkdir(exist_ok=True)
    r = _run(script, home, "--search", str(out))
    assert r.returncode == 7, r.stdout + r.stderr
    dst = home / "VASYA-GNS-LAB" / "Images" / "docker"
    assert not dst.exists() or not any(dst.iterdir())
    assert not list(tmp_path.rglob("evil.sh"))


def test_setup_verify_only_and_docker_only(tmp_path, monkeypatch):
    s, D, out = _pack(tmp_path, monkeypatch)
    script = _setup(tmp_path, D)
    home = tmp_path / "home"; home.mkdir(exist_ok=True)
    r = _run(script, home, "--search", str(out), "--verify-only")
    assert r.returncode == 0 and "Docker image pack: parts OK." in r.stdout
    assert not (home / "VASYA-GNS-LAB").exists() and not (home / TOP).exists()
    r = _run(script, home, "--search", str(out), "--docker-only")
    assert r.returncode == 0 and not (home / TOP).exists()
    assert len(list((home / "VASYA-GNS-LAB" / "Images" / "docker").iterdir())) == 5


def test_real_spec_pins_all_20_archives_and_sidecars():
    D = bdp.spec()
    assert D["pack"] == f"VASYA-GNS-LAB-{VERSION}-Docker-Images" and len(D["files"]) == 41
    arcs = {n: f for n, f in D["files"].items() if n.endswith(".tar.zst")}
    assert len(arcs) == 20 and sum(f["size"] for f in arcs.values()) == 3966929514
    assert D["files"]["index.json"]["sha256"] == "76a5c4d28ec0fca588143b1e7a914ac77bc2fa96613d261b50b22fac75f8a6e5"
    for n, f in arcs.items():   # the archive's own .sha256 sidecar agrees with the pin
        side = (ROOT / "packaging" / "docker-pack" / (n + ".sha256")).read_text().split()
        assert side[0] == f["sha256"] and side[1].endswith(n)


def test_app_reports_image_pack_missing(tmp_path, monkeypatch):
    from vasya import api
    from conftest import make_payload
    ctx = api.open_ctx(tmp_path / "R", make_payload(tmp_path / "p", docker=True))
    st = di.pack_status(ctx)
    assert st["status"] == "MISSING" and st["present"] == 0 and len(st["missing"]) == 20
    d = ctx.layout.root / "Images" / "docker"; d.mkdir(parents=True)
    e = di.pin_for_ref("alpine"); (d / e["archive"]).write_bytes(b"x")
    st = di.pack_status(ctx)
    assert st["status"] == "PARTIAL" and st["present"] == 1
    msg = di.pack_missing_reason(ctx, "gns3/ipterm:latest")
    assert msg.startswith("image pack missing: ipterm-355646d78a41.tar.zst") and di.pack_name() in msg
    r = di.restore(ctx, "gns3/ipterm:latest", ["false"])
    assert r["status"] == "NO_ARCHIVE" and "image pack missing" in r["message"]


def test_plan_preview_shows_image_pack_missing(tmp_path, monkeypatch):
    from vasya import api
    from vasya.runtime import docker_backend as dbk
    from conftest import make_payload
    monkeypatch.delenv("VASYA_DOCKER_BACKEND", raising=False)
    monkeypatch.setattr(dbk, "podman_prereqs", lambda which=None: [])
    ctx = api.open_ctx(tmp_path / "R", make_payload(tmp_path / "p", docker=True))
    p = api.plan(ctx, "FULL")
    pk = p["preview"].get("docker_image_pack")
    assert pk and pk["status"] == "MISSING" and pk["note"].startswith("image pack missing: 0/20")
