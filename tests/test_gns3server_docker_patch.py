# SPDX-License-Identifier: GPL-3.0-or-later
"""The 6 regression tests of gns3server-2.2.61-vasya-docker-socket.patch (verbatim in
tests/gns3server_patch/regress_vasya_docker_socket.py), each run in a subprocess against a scratch copy of
the bundled gns3server runtime patched by vasya.runtime.docker_backend.patch_gns3server."""
import os, shutil, subprocess, sys
from pathlib import Path
import pytest
from vasya.runtime import docker_backend as dbk

from conftest import GNS3RT as _RT
GNS3RT = _RT / f"py{sys.version_info[0]}{sys.version_info[1]}"
HERE = Path(__file__).resolve().parent / "gns3server_patch"
TESTS = ["test_default_unset", "test_empty_falls_back", "test_override", "test_patch_marker_present",
         "test_fix_uid_default_is_host_uid", "test_attach_ws_404_falls_back_to_hijack"]
pytestmark = pytest.mark.skipif(not GNS3RT.exists() or not shutil.which("patch"),
                                reason="no gns3server runtime for this python / no patch tool")


@pytest.fixture(scope="module")
def patched_rt(tmp_path_factory):
    d = tmp_path_factory.mktemp("rt") / GNS3RT.name
    shutil.copytree(GNS3RT, d, symlinks=True, ignore=shutil.ignore_patterns("__pycache__", "bin"))
    assert dbk.patch_gns3server(d.parent) == [(str(d / dbk.PATCH_FILES[0]), "PATCHED")]
    return d


def test_regression_file_has_exactly_the_six_tests():
    src = (HERE / "regress_vasya_docker_socket.py").read_text()
    assert sorted(l.split("def ")[1].split("(")[0] for l in src.splitlines() if l.strip().startswith("def test_")) == sorted(TESTS)


@pytest.mark.parametrize("name", TESTS)
def test_patch_regression(patched_rt, name):
    env = {k: v for k, v in os.environ.items() if not k.startswith("VASYA_DOCKER")}
    env["PYTHONPATH"] = str(patched_rt)
    r = subprocess.run([sys.executable, "-m", "unittest", "-v", f"regress_vasya_docker_socket.TestVasyaDockerSocket.{name}"],
                       cwd=HERE, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "OK" in r.stderr, r.stderr[-2000:]
    import_check = subprocess.run([sys.executable, "-c", "import gns3server,sys;print(gns3server.__file__)"],
                                  env=env, capture_output=True, text=True)
    assert import_check.stdout.startswith(str(patched_rt)), "must test the patched copy, not an installed gns3server"
