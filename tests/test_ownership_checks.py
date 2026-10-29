# SPDX-License-Identifier: GPL-3.0-or-later
"""The 12 ownership checks of the 1.0.1 rollback hotfix (test_rollback_ownership.py, which passed on
a real Pop!_OS install) ported to 1.1.0's receipt model: a resource is deleted only if it is in a receipt AND its state (size+sha256)
still matches. Name alone — including VASYA-looking names and same-named templates — is never enough."""
import hashlib, json, subprocess, sys
from pathlib import Path
import pytest
from vasya.installer import rollback as rb

H = lambda b: hashlib.sha256(b).hexdigest()
A, B = b"owned-image" * 500, b"other-image" * 500
APP = b'{"name":"Foo"}'


class FakeClient:
    deleted = []
    templates = [{"template_id": "tid-owned", "name": "Foo", "usage": "x [VASYA GNS LAB]"},
                 {"template_id": "tid-user-same-name", "name": "Foo", "usage": "user's"}]

    def __init__(self, base, *a, **k): pass
    def version(self): return {"version": "2.2.61"}
    def find_template(self, name, ttype=None):
        return next((t for t in self.templates if t["name"] == name), None)
    def delete_template(self, tid):
        FakeClient.deleted.append(tid); return True


@pytest.fixture
def world(tmp_path, monkeypatch):
    FakeClient.deleted = []
    monkeypatch.setattr(rb, "GNS3Client", FakeClient)
    img = tmp_path / "images" / "QEMU"; img.mkdir(parents=True)
    apps = tmp_path / "appliances"; apps.mkdir()
    f = {"owned_ok": (img / "owned.qcow2", A), "owned_modified": (img / "modified.qcow2", B),
         "not_in_receipt": (img / "user-own.qcow2", A),
         "vasya_named_foreign": (img / ("vasya-" + "0" * 16 + "-x.qcow2"), b"x"),
         "leftover_ok": (img / f"vasya-{H(A)[:16]}-owned.qcow2", A),
         "leftover_namematch_diff": (img / f"vasya-{H(A)[:16]}-tampered.qcow2", B),
         "app_owned_ok": (apps / "vasya-foo-foo.gns3a", APP),
         "app_owned_modified": (apps / "vasya-foo-bar.gns3a", b'{"user":"edited"}'),
         "app_vasya_not_in_receipt": (apps / "vasya-user-thing.gns3a", b"{}")}
    for p, data in f.values():
        p.write_bytes(data)
    rec = lambda k, sha, role: {"kind": "file", "path": str(f[k][0]), "sha256": sha, "role": role}
    receipts = [rec("owned_ok", H(A), "image"), rec("owned_modified", H(A), "image"),
                rec("leftover_ok", H(A), "image"), rec("leftover_namematch_diff", H(A), "image"),
                rec("app_owned_ok", H(APP), "appliance"), rec("app_owned_modified", H(APP), "appliance"),
                {"kind": "template", "api_base": "http://stub", "name": "Foo", "template_type": "qemu",
                 "template_id": "tid-owned", "tag": "[VASYA GNS LAB]"}]
    results = {Path(r.get("path", r.get("template_id"))).name: rb.undo_resource(None, r) for r in receipts}
    return f, results


REMOVED = {"owned_ok", "leftover_ok", "app_owned_ok"}
KEPT = {"owned_modified", "not_in_receipt", "vasya_named_foreign", "leftover_namematch_diff",
        "app_owned_modified", "app_vasya_not_in_receipt"}


@pytest.mark.parametrize("key", sorted(REMOVED))
def test_owned_and_matching_is_removed(world, key):            # checks 1, 5, 7
    f, _ = world
    assert not f[key][0].exists()


@pytest.mark.parametrize("key", sorted(KEPT))
def test_unowned_or_changed_is_kept(world, key):               # checks 2, 3, 4, 6, 8, 9
    f, _ = world
    assert f[key][0].exists()


def test_kept_contents_unchanged(world):                       # check 10
    f, _ = world
    assert f["owned_modified"][0].read_bytes() == B
    assert f["app_owned_modified"][0].read_bytes() == b'{"user":"edited"}'


def test_only_owned_template_deleted(world):                   # check 11
    assert FakeClient.deleted == ["tid-owned"]


def test_refusals_reported(world):                             # check 12
    _, res = world
    assert res["modified.qcow2"][0] == "KEPT_MODIFIED" and "content changed" in res["modified.qcow2"][1]
    assert res["vasya-foo-bar.gns3a"][0] == "KEPT_MODIFIED"


def test_template_without_id_needs_vasya_tag(monkeypatch):
    """Crash between INTENT and COMMIT: no template_id. A same-named template without VASYA's
    usage tag is not ours and must survive."""
    FakeClient.deleted = []
    monkeypatch.setattr(rb, "GNS3Client", FakeClient)
    monkeypatch.setattr(FakeClient, "templates", [{"template_id": "tid-user", "name": "Foo", "usage": "user's"}])
    st, _ = rb.undo_resource(None, {"kind": "template", "api_base": "x", "name": "Foo", "tag": "[VASYA GNS LAB]"})
    assert st == "ABSENT" and FakeClient.deleted == []


from conftest import LEGACY, RC_PACK
HOTFIX = LEGACY / "evidence" / "rollback"


@pytest.mark.skipif(not ((HOTFIX / "rollback.py").exists() and RC_PACK.exists()),
                    reason="1.0.1 code base not available (VASYA_TEST_LEGACY, VASYA_TEST_RC_PACK)")
def test_legacy_hotfix_passes_its_own_12_checks(tmp_path):
    """Re-run of the deployed 1.0.1 rollback hotfix with its own test (scratch copy of
    Pack/lib only; the 1.0.1 tree is read, never modified)."""
    import shutil
    pack = tmp_path / "Pack"
    shutil.copytree(RC_PACK / "lib", pack / "lib")
    shutil.copy2(HOTFIX / "rollback.py", pack / "lib" / "rollback.py")
    r = subprocess.run([sys.executable, str(HOTFIX / "test_rollback_ownership.py"), str(pack), str(tmp_path / "s")],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "OWNERSHIP PASS" in r.stdout, r.stdout[-2000:] + r.stderr[-2000:]
    checks = json.loads(r.stdout[r.stdout.index('{\n "result"'):r.stdout.rindex("OWNERSHIP")])["checks"]
    assert len(checks) == 12 and all(checks.values())
