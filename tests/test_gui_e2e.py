# SPDX-License-Identifier: GPL-3.0-or-later
"""Real GUI-driven end-to-end (pytest-qt, offscreen) against gns3server 2.2.61:
wizard install (Complete Lab) -> static + runtime verify -> deliberately delete one image and
corrupt another -> repair from the GUI -> uninstall wizard level 2 (projects exported) ->
residue all zeros -> system snapshot before == after. Screenshots of every screen."""
import json, os, platform, tempfile, time
from pathlib import Path
import pytest
from conftest import have_gns3, have_docker

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
from PySide6.QtCore import Qt
from vasya.gui.app import MainWindow, Backend, apply_theme
from vasya.gui import workers, i18n
from vasya import api
from vasya.core import txn as txnmod
from vasya.core.util import sha256_file
from e2e_snapshot import snapshot, diff

E2E_LANG = os.environ.get("VASYA_E2E_LANG", "ru")
E2E_THEME = os.environ.get("VASYA_E2E_THEME", "light")
# screenshots and the JSON report go to VASYA_E2E_SHOTS (default: a temp dir)
EVID = Path(os.environ.get("VASYA_E2E_SHOTS") or Path(tempfile.gettempdir()) / "vasya-e2e") / \
    ("gui" if (E2E_LANG, E2E_THEME) == ("ru", "light") else f"gui-{E2E_LANG}-{E2E_THEME}")
# payload with images, built by scripts/make_payload.py (default location: tmp/payload-gui, not tracked)
PAYLOAD = Path(os.environ.get("VASYA_TEST_GUI_PAYLOAD")
               or Path(__file__).resolve().parent.parent / "tmp" / "payload-gui")


def shot(w, name):
    EVID.mkdir(parents=True, exist_ok=True)
    w.grab().save(str(EVID / f"{name}.png"))


def wait_idle(qtbot, timeout=900000):
    qtbot.waitUntil(lambda: not workers._running, timeout=timeout)
    qtbot.wait(80)


@have_gns3
@have_docker
@pytest.mark.skipif(not PAYLOAD.exists(), reason="run scripts/make_payload.py for tmp/payload-gui")
def test_gui_full_cycle(qtbot, tmp_path, qapp, isolated_home, shared_daemon):
    from conftest import _teardown_root
    root = tmp_path / "VASYA-GNS-LAB"
    for old in EVID.glob("*.png"):
        old.unlink()
    i18n.set_lang(E2E_LANG)
    os.environ["VASYA_THEME"] = E2E_THEME
    try:
        _gui_cycle(qtbot, root, qapp, isolated_home)
    finally:
        i18n.set_lang(None)
        _teardown_root(root, PAYLOAD)


def _gui_cycle(qtbot, root, qapp, home):
    apply_theme(qapp)
    before = snapshot(home, root)
    ev = {"where": platform.platform(), "root": str(root),
          "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    w = MainWindow(Backend(root, PAYLOAD)); w.auto_confirm = True
    qtbot.addWidget(w); w.resize(1280, 820); w.show()
    w.go("home"); wait_idle(qtbot); shot(w, "01-home-before")
    assert w.screens["home"].verdict_value == "NOT_INSTALLED"
    wiz = w.screens["install"]; w.go("install"); wiz.goto(0); wait_idle(qtbot)
    shot(w, "02-wizard-1-system")
    qtbot.mouseClick(wiz.b_next, Qt.LeftButton); wiz.r_full.setChecked(True); shot(w, "03-wizard-2-mode")
    qtbot.mouseClick(wiz.b_next, Qt.LeftButton); shot(w, "04-wizard-3-components")
    qtbot.mouseClick(wiz.b_next, Qt.LeftButton); wiz.root_edit.setText(str(root)); shot(w, "05-wizard-4-folder")
    qtbot.mouseClick(wiz.b_next, Qt.LeftButton); wait_idle(qtbot); shot(w, "06-wizard-5-plan")
    assert wiz.plan_result["mode"] == "FULL" and wiz.blocked is None and wiz.b_next.isEnabled()
    ev["plan_preview"] = {k: wiz.plan_result["preview"][k] for k in
                          ("space_needed_human", "free_human", "download_human", "admin_required",
                           "reboot_or_relogin", "system_changes", "deps_missing")}
    assert not root.exists(), "plan must not create anything"
    qtbot.mouseClick(wiz.b_next, Qt.LeftButton)  # «Установить»
    qtbot.waitUntil(lambda: wiz.cur_lbl.text().startswith("[") and wiz.bar.value() >= 4, timeout=900000)
    shot(w, "07-wizard-6-progress")
    ev["progress_sample"] = wiz.cur_lbl.text()
    qtbot.waitUntil(lambda: wiz.install_result is not None, timeout=900000)
    wait_idle(qtbot)
    assert wiz.install_result["status"] == "OK", wiz.install_result.get("failed")
    assert wiz.pages.currentIndex() == 6 and wiz.verify_result["status"] == "PASS"
    shot(w, "08-wizard-7-verify")
    qtbot.mouseClick(wiz.b_runtime, Qt.LeftButton); wait_idle(qtbot); shot(w, "09-wizard-7-verify-runtime")
    rv = wiz.runtime_result
    ev["runtime_verify"] = {"status": rv["status"], "passed": rv["passed"], "total": rv["total"],
                            "results": {r["block_id"]: r["steps"] for r in rv["results"]}}
    assert rv["passed"] == rv["total"] == 4, rv
    qtbot.mouseClick(wiz.b_next, Qt.LeftButton); shot(w, "10-wizard-8-done")
    assert wiz.pages.currentIndex() == 7 and wiz.b_open.isVisible() and not wiz.b_retry.isVisible()
    ev["install"] = {"status": wiz.install_result["status"], "txid": wiz.install_result["txid"],
                     "ops": len(wiz.install_result["results"]), "log_lines": wiz.out.toPlainText().splitlines()}
    w.go("home"); wait_idle(qtbot); shot(w, "11-home-healthy")
    assert w.screens["home"].verdict_value == "HEALTHY_VERIFIED"
    ev["cli_verdict"] = api.verdict(api.status(api.open_ctx(root, PAYLOAD)))
    ev["gui_verdict"] = w.screens["home"].verdict_value
    assert ev["cli_verdict"] == ev["gui_verdict"]
    w.go("catalog"); wait_idle(qtbot); cat = w.screens["catalog"]
    assert cat.table.rowCount() == 186
    cat.q.setText("cisco"); qtbot.wait(100); cat.table.selectRow(0); shot(w, "12-catalog")
    cat.q.setText("")
    # --- deliberate damage: delete the FRR image, corrupt the c7200 image ---
    ctx = api.open_ctx(root, PAYLOAD)
    imgs = {x["block_id"]: x for x in txnmod.owned_resources(ctx.layout) if x.get("role") == "image"}
    frr, c72 = Path(imgs["frr"]["path"]), Path(imgs["cisco-ios-c7200-p-mz-123-19"]["path"])
    frr.unlink()
    c72.unlink(); c72.write_bytes(b"\0corrupted by the E2E test\0" * 4096)
    vs = w.screens["verify"]; w.go("verify")
    qtbot.mouseClick(vs.b_static, Qt.LeftButton); wait_idle(qtbot)
    codes = sorted(c.get("code") for c in vs.last_result["checks"] if c["status"] == "FAIL")
    assert codes == ["IMAGE_CORRUPT", "IMAGE_MISSING"], codes
    assert vs.b_repair.isVisible() and "FRR" in vs.summary.text(), vs.summary.text()
    shot(w, "13-verify-damage-detected")
    rs = w.screens["repair"]
    qtbot.mouseClick(vs.b_repair, Qt.LeftButton)  # the human summary leads straight to Repair
    assert w.stack.currentWidget() is rs
    qtbot.mouseClick(rs.b, Qt.LeftButton); wait_idle(qtbot); shot(w, "14-repair-done")
    assert rs.last_result["status"] == "OK" and rs.last_result["damaged_before"] == 2, rs.last_result
    assert sha256_file(frr) == imgs["frr"]["sha256"] and sha256_file(c72) == imgs["cisco-ios-c7200-p-mz-123-19"]["sha256"]
    w.go("verify"); qtbot.mouseClick(vs.b_static, Qt.LeftButton); wait_idle(qtbot)
    assert vs.last_result["status"] == "PASS" and not vs.b_repair.isVisible()
    shot(w, "14b-verify-after-repair")
    ev["damage_repair"] = {"detected": codes, "repair": rs.last_result["status"],
                           "quarantined": rs.last_result["quarantined"], "static_after": vs.last_result["status"]}
    w.go("logs"); shot(w, "15-logs")
    ds = w.screens["diagnostics"]; w.go("diagnostics")
    qtbot.mouseClick(ds.b, Qt.LeftButton); wait_idle(qtbot); shot(w, "16-diagnostics")
    ev["diagnostics_zip"] = str(ds.path)
    w.go("tools"); wait_idle(qtbot); shot(w, "17-tools")
    fr = w.screens["ready"]; w.go("ready"); wait_idle(qtbot); shot(w, "18-lab-ready")
    for i in range(fr.demos.count()):
        if fr.demos.item(i).data(Qt.UserRole) == "wireshark-capture":
            fr.demos.setCurrentRow(i)
    qtbot.mouseClick(fr.b_create, Qt.LeftButton); wait_idle(qtbot)
    qtbot.mouseClick(fr.b_check, Qt.LeftButton); wait_idle(qtbot); shot(w, "19-demo-capture")
    ev["demo_capture"] = {k: fr.last_result[k] for k in ("status", "capture")} if fr.last_result else fr.last_error
    assert fr.last_result and fr.last_result["status"] == "PASS" and fr.last_result["capture"]["icmp_frames"] > 0
    qtbot.mouseClick(fr.b_remove, Qt.LeftButton); wait_idle(qtbot)
    # a project of the user's own, inside the managed lab -> uninstall must ask
    from vasya.gns3.client import GNS3Client
    GNS3Client(ctx.state.load()["gns3"]["api_base"]).create_project("my-ospf-lab")
    us = w.screens["uninstall"]; w.go("uninstall"); wait_idle(qtbot)
    us.r2.setChecked(True); shot(w, "20-uninstall-1-inventory")
    qtbot.mouseClick(us.b_next, Qt.LeftButton)
    assert us.pages.currentIndex() == 1
    us.rp_export.setChecked(True); shot(w, "21-uninstall-2-projects")
    qtbot.mouseClick(us.b_next, Qt.LeftButton); shot(w, "22-uninstall-3-confirm")
    qtbot.mouseClick(us.b_run, Qt.LeftButton); wait_idle(qtbot); shot(w, "23-uninstall-4-report")
    rep = us.report
    ev["uninstall"] = {"counts": rep["residue"]["counts"], "clean": rep["residue"]["clean"],
                       "report": rep["report_path"], "projects_saved_to": rep.get("projects_saved_to"),
                       "self_removal": rep.get("self_removal")}
    assert rep["residue"]["clean"], rep["residue"]
    assert all(v == 0 for v in rep["residue"]["counts"].values())
    assert not root.exists()
    z = Path(rep["projects_saved_to"]); assert z.exists() and z.suffix == ".zip"
    time.sleep(2)
    after = snapshot(home, root)
    d = diff(before, after)
    ev["snapshot_before"], ev["snapshot_after"], ev["snapshot_diff"] = before, after, d
    allowed = {"home_files": {"added": [z.name], "removed": []}}
    (EVID / "E2E_GUI_EVIDENCE.json").write_text(json.dumps(ev, indent=2, default=str, ensure_ascii=False))
    assert {k: v for k, v in d.items() if k != "listening"} == allowed, d
    assert not set(d.get("listening", {}).get("added", [])), d
