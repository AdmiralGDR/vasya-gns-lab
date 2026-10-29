# SPDX-License-Identifier: GPL-3.0-or-later
"""Delivery parts: split, find (also inside Drive zips), verify (cached), join, one-file setup script."""
import hashlib, json, os, subprocess, tarfile, zipfile
from pathlib import Path
import pytest
from vasya.delivery import parts as P
from vasya.delivery.bootstrap import make_setup_script

TOP = "VASYA-GNS-LAB-9.9.9"
pytestmark = pytest.mark.skipif(not __import__("shutil").which("zstd"), reason="zstd missing")


def _bundle(tmp):
    src = tmp / "src" / TOP
    (src / "Payload" / "manifests").mkdir(parents=True)
    (src / "Payload" / "manifests" / "pack.json").write_text("{}")
    (src / "BUNDLE_MANIFEST.json").write_text("{}")
    (src / "install.sh").write_text("#!/bin/sh\necho INSTALLER-RAN \"$VASYA_BUNDLE_DIR\" > \"$HOME/ran.txt\"\n")
    (src / "install.sh").chmod(0o755)
    (src / "blob.bin").write_bytes(os.urandom(300_000))
    arc = tmp / "rel" / f"{TOP}-Linux.tar.zst"
    arc.parent.mkdir()
    subprocess.run(f"tar -C {tmp/'src'} -cf - {TOP} | zstd -q -o {arc}", shell=True, check=True)
    return arc


def _release(tmp, part=64 * 1024):
    arc = _bundle(tmp)
    drive = tmp / "drive"
    man = P.split(arc, drive, part, {"version": "9.9.9", "top_dir": TOP, "extracted_bytes": 400_000})
    script = drive / "setup.sh"
    script.write_text(make_setup_script(man, "setup.sh"))
    return arc, drive, man, script


def _run(script, home, *args, cwd=None):
    env = dict(os.environ, HOME=str(home), LANG="en_US.UTF-8")
    return subprocess.run(["sh", str(script), "--dest", str(home), *args], capture_output=True,
                          text=True, env=env, cwd=cwd or home, timeout=120)


def test_split_is_lossless_and_manifest_matches(tmp_path):
    arc, drive, man, _ = _release(tmp_path)
    assert len(man["parts"]) >= 4 and all(p["size"] <= 64 * 1024 for p in man["parts"])
    joined = b"".join((drive / p["name"]).read_bytes() for p in man["parts"])
    assert joined == arc.read_bytes()
    assert man["sha256"] == hashlib.sha256(joined).hexdigest()


def test_setup_script_finds_verifies_unpacks_and_starts_installer(tmp_path):
    _, drive, man, script = _release(tmp_path)
    home = tmp_path / "home"; home.mkdir(exist_ok=True)
    r = _run(script, home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (home / TOP / "blob.bin").stat().st_size == 300_000
    assert "INSTALLER-RAN" in (home / "ran.txt").read_text()
    assert not any(p.name.startswith(".") and p.name.endswith(".partial") for p in home.iterdir())


def test_missing_part_is_named_and_nothing_unpacked(tmp_path):
    _, drive, man, script = _release(tmp_path)
    (drive / man["parts"][2]["name"]).unlink()
    home = tmp_path / "home"; home.mkdir(exist_ok=True)
    r = _run(script, home, "--no-install")
    assert r.returncode == 6 and man["parts"][2]["name"] in r.stdout
    assert not (home / TOP).exists()


def test_corrupt_part_detected_then_resume_rehashes_only_changed(tmp_path):
    _, drive, man, script = _release(tmp_path)
    bad = drive / man["parts"][1]["name"]
    good = bad.read_bytes()
    bad.write_bytes(b"X" + good[1:])
    home = tmp_path / "home"; home.mkdir(exist_ok=True)
    r = _run(script, home, "--no-install")
    assert r.returncode == 6 and bad.name in r.stdout and not (home / TOP).exists()
    bad.write_bytes(good)  # user re-downloads just that part
    r = _run(script, home, "--no-install")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("cached") == len(man["parts"]) - 1
    assert (home / TOP / "install.sh").exists()


def test_parts_inside_google_drive_zip_downloads(tmp_path):
    _, drive, man, script = _release(tmp_path)
    dl = tmp_path / "home" / "Downloads"; dl.mkdir(parents=True, exist_ok=True)
    half = len(man["parts"]) // 2
    for i, chunk in enumerate((man["parts"][:half], man["parts"][half:])):
        with zipfile.ZipFile(dl / f"VASYA-20261026T000000Z-00{i+1}.zip", "w") as z:
            for p in chunk:
                z.write(drive / p["name"], f"VASYA GNS LAB/{p['name']}")
    for p in man["parts"]:
        (drive / p["name"]).unlink()
    r = _run(script, tmp_path / "home", "--no-install")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "home" / TOP / "blob.bin").exists()


def test_whole_archive_also_accepted_and_checked(tmp_path):
    arc, drive, man, script = _release(tmp_path)
    for p in man["parts"]:
        (drive / p["name"]).unlink()
    (drive / arc.name).write_bytes(arc.read_bytes()[:-10] + b"0123456789")
    home = tmp_path / "home"; home.mkdir(exist_ok=True)
    r = _run(script, home, "--no-install")
    assert r.returncode == 6 and "ARCHIVE_CORRUPT" in r.stdout and not (home / TOP).exists()
    (drive / arc.name).write_bytes(arc.read_bytes())
    r = _run(script, home, "--no-install")
    assert r.returncode == 0 and (home / TOP / "blob.bin").exists()


def test_not_enough_space_refuses_before_unpacking(tmp_path):
    arc = _bundle(tmp_path)
    drive = tmp_path / "drive"
    man = P.split(arc, drive, 64 * 1024, {"version": "9.9.9", "top_dir": TOP, "extracted_bytes": 1 << 60})
    (drive / "setup.sh").write_text(make_setup_script(man, "setup.sh"))
    home = tmp_path / "home"; home.mkdir(exist_ok=True)
    r = _run(drive / "setup.sh", home, "--no-install")
    assert r.returncode == 5 and "Not enough space" in r.stdout and not (home / TOP).exists()


def test_dest_that_does_not_exist_yet_is_created(tmp_path):
    """Found by a run of the real 1.1.0 parts: `--dest /new/dir` crashed in disk_usage."""
    _, drive, man, script = _release(tmp_path)
    home = tmp_path / "home"; home.mkdir(exist_ok=True)
    env = dict(os.environ, HOME=str(home), LANG="en_US.UTF-8")
    dest = tmp_path / "new" / "deeper"
    r = subprocess.run(["sh", str(script), "--dest", str(dest), "--no-install"], capture_output=True,
                       text=True, env=env, cwd=drive, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (dest / TOP / "blob.bin").stat().st_size == 300_000
