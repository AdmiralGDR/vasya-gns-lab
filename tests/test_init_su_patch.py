# SPDX-License-Identifier: GPL-3.0-or-later
"""VASYA gns3server patch 4: container init.sh skips busybox `su` when the container
user is root. Regression: root (unset/root/0) -> run-cmd.sh without su; any other user still goes
through `su <user> -p --`; the patched file is otherwise the stock 2.2.61 init.sh (lines added only)."""
import difflib, hashlib, os, shutil, stat, subprocess
from pathlib import Path
import pytest
from vasya.runtime import docker_backend as dbk

FIX = Path(__file__).parent / "gns3server_patch" / "init_su"
STOCK, PATCHED = FIX / "init.sh.orig", FIX / "init.sh.patched"
STOCK_MD5, PATCHED_MD5 = "e8416376", "2b6ea884f2c4f8368d89f4fef25eefc0"
PRE_NOTICE_MD5 = "e209da409e4c071d20fb664a063619fb"     # same patch before the 5(a) notice line was added
from conftest import GNS3RT as BUILD, STAGE_DIR
STAGE = STAGE_DIR / "App" / "runtime" / "gns3server"
PYS = ("py310", "py311", "py312", "py313")


def _md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


def _tree(tmp_path, n=4):
    for py in PYS[:n]:
        f = tmp_path / py / dbk.INIT_SH
        f.parent.mkdir(parents=True)
        shutil.copyfile(STOCK, f)
        os.chmod(f, 0o755)
    return tmp_path


def test_fixtures_are_the_tested_files():
    assert _md5(STOCK).startswith(STOCK_MD5) and _md5(PATCHED) == PATCHED_MD5
    assert hashlib.sha256(dbk.INIT_SU_PATCH_FILE.read_bytes()).hexdigest() == \
        "f8bcb91b56ca5c1beb4368c104259b24f8cb706ea06efde221201bcc399afb14"


def test_patch_all_four_copies_identical_to_tested_mode_kept_idempotent(tmp_path):
    t = _tree(tmp_path)
    r = dbk.patch_init_su(t)
    assert [s for _, s in r] == ["PATCHED"] * 4
    for py in PYS:
        f = t / py / dbk.INIT_SH
        assert _md5(f) == PATCHED_MD5
        assert stat.S_IMODE(f.stat().st_mode) == 0o755
        assert dbk.init_su_state(t / py) == "PATCHED"
    assert [s for _, s in dbk.patch_init_su(t)] == ["ALREADY"] * 4
    assert all(_md5(t / py / dbk.INIT_SH) == PATCHED_MD5 for py in PYS)


def test_patched_default_otherwise_unchanged():
    a, b = STOCK.read_text().splitlines(), PATCHED.read_text().splitlines()
    ops = [o for o in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes() if o[0] != "equal"]
    assert [o[0] for o in ops] == ["insert", "insert"], ops  # lines added only, nothing removed/changed
    notice = b[ops[0][3]:ops[0][4]]                            # GPL-3.0 section 5(a) notice after the copyright
    assert len(notice) == 1 and notice[0].startswith("# Modified by AdmiralGDR on 2026-10-26")
    added = b[ops[1][3]:ops[1][4]]
    assert len(added) == 6 and added[0].startswith(dbk.INIT_SU_MARKER)
    assert a[-1] == b[-1] == 'exec su ${GNS3_USER-root} -p -- /gns3/run-cmd.sh "$OLD_PATH" "$@"'
    assert b.index(added[0]) == len(b) - 7                      # just before the final exec su


def test_patch_all_reports_both_patches(tmp_path, monkeypatch):
    t = _tree(tmp_path, 1)
    monkeypatch.setattr(dbk, "patch_gns3server", lambda tree: [("x", "ALREADY")])
    r = dbk.patch_all(t)
    assert set(r) == {dbk.PATCH_NAME, dbk.INIT_SU_PATCH_NAME} and r[dbk.INIT_SU_PATCH_NAME][0][1] == "PATCHED"


def test_pattern_not_found_leaves_file(tmp_path):
    f = tmp_path / "py313" / dbk.INIT_SH
    f.parent.mkdir(parents=True); f.write_text("#!/bin/sh\necho other\n")
    assert dbk.patch_init_su(tmp_path)[0][1] == "PATTERN_NOT_FOUND"
    assert f.read_text() == "#!/bin/sh\necho other\n"


def _run_tail(src, tmp_path, user):
    """Run the startup tail of init.sh (from '# continue normal docker startup') with stub run-cmd.sh
    and stub su; /etc/passwd replaced by a fixture."""
    txt = src.read_text()
    tail = txt[txt.index("# continue normal docker startup"):]
    g = tmp_path / "gns3"; g.mkdir(exist_ok=True)
    (g / "run-cmd.sh").write_text('#!/bin/sh\necho "RUN $*"\n')
    bin_ = tmp_path / "bin"; bin_.mkdir(exist_ok=True)
    (bin_ / "su").write_text('#!/bin/sh\necho "SU $*"\n')
    for x in (g / "run-cmd.sh", bin_ / "su"):
        os.chmod(x, 0o755)
    (tmp_path / "passwd").write_text("root:x:0:0::/root:/bin/sh\nalice:x:1000:1000::/home/alice:/bin/sh\n")
    tail = tail.replace("/gns3/", str(g) + "/").replace("/etc/passwd", str(tmp_path / "passwd"))
    sh = tmp_path / "tail.sh"; sh.write_text('OLD_PATH=/usr/bin:/bin\n' + tail)
    env = {"PATH": f"{bin_}:/usr/bin:/bin"}
    if user is not None:
        env["GNS3_USER"] = user
    r = subprocess.run(["/bin/sh", str(sh), "echo", "hi"], env=env, capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.mark.parametrize("user", [None, "", "root", "0"])
def test_root_skips_su(tmp_path, user):
    assert _run_tail(PATCHED, tmp_path, user) == "RUN /usr/bin:/bin echo hi"


@pytest.mark.parametrize("user,name", [("nobody", "nobody"), ("alice", "alice"), ("1000", "alice")])
def test_non_root_still_uses_su(tmp_path, user, name):
    assert _run_tail(PATCHED, tmp_path, user) == f"SU {name} -p -- {tmp_path}/gns3/run-cmd.sh /usr/bin:/bin echo hi"


@pytest.mark.parametrize("user", [None, "root"])
def test_stock_init_used_su_for_root(tmp_path, user):
    """The bug patch 4 fixes: stock init.sh runs `su root` (busybox su crashed in old-glibc images)."""
    assert _run_tail(STOCK, tmp_path, user).startswith("SU root -p -- ")


@pytest.mark.skipif(not STAGE.is_dir(), reason="set VASYA_TEST_STAGE to a staged bundle")
def test_release_stage_copies_patched_build_tree_stock():
    got = sorted(STAGE.glob("py3*/" + dbk.INIT_SH))
    assert len(got) == 4
    for f in got:
        assert _md5(f) in (PATCHED_MD5, PRE_NOTICE_MD5) and stat.S_IMODE(f.stat().st_mode) == 0o755
    for f in sorted(BUILD.glob("py3*/" + dbk.INIT_SH)):     # build inputs are never patched in place
        assert _md5(f).startswith(STOCK_MD5)
    import json
    rec = json.loads((STAGE / "VASYA_PATCHES.json").read_text())
    p4 = [p for p in rec["patches"] if p["patch"] == dbk.INIT_SU_PATCH_NAME][0]
    assert len(p4["files"]) == 4
