# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless GUI tests (offscreen): every screen builds, buttons are wired to the backend,
both themes and both languages render, keyboard navigation works."""
import os
import pytest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton
from vasya.gui.app import MainWindow, Backend, apply_theme
from vasya.gui import i18n, workers

EXPECTED = ["home", "install", "catalog", "verify", "repair", "uninstall", "logs", "diagnostics",
            "tools", "ready"]


@pytest.fixture
def win(qtbot, tmp_path, payload):
    w = MainWindow(Backend(tmp_path / "R", payload))
    qtbot.addWidget(w); w.show()
    yield w
    qtbot.waitUntil(lambda: not workers._running, timeout=60000)


def test_all_screens_and_buttons_connected(win, qtbot):
    assert list(win.screens) == EXPECTED
    for k in EXPECTED:
        win.go(k)
        qtbot.waitUntil(lambda: not workers._running, timeout=60000)
        for b in win.screens[k].findChildren(QPushButton):
            assert b.receivers("2clicked(bool)") + b.receivers("2clicked()") > 0, (k, b.text())


def test_browsing_every_screen_writes_nothing(win, qtbot, tmp_path):
    """Opening the Manager and looking at every screen must not create the VASYA folder."""
    for k in EXPECTED:
        win.go(k)
        qtbot.waitUntil(lambda: not workers._running, timeout=60000)
    assert not (tmp_path / "R").exists(), sorted(str(p) for p in (tmp_path / "R").rglob("*"))


def test_keyboard_navigation(win, qtbot):
    qtbot.keyClick(win, Qt.Key_3, Qt.AltModifier)
    assert win.stack.currentWidget() is win.screens["catalog"]
    qtbot.keyClick(win, Qt.Key_1, Qt.AltModifier)
    assert win.stack.currentWidget() is win.screens["home"]


def test_catalog_filters(win, qtbot):
    win.go("catalog"); c = win.screens["catalog"]
    assert c.table.rowCount() == 186
    c.f_status.setCurrentIndex(c.f_status.findData("READY"))
    assert c.table.rowCount() == 41
    c.q.setText("frr")
    assert c.table.rowCount() >= 1
    c.table.selectRow(0)
    assert "FRR" in c.detail.toPlainText() or "frr" in c.detail.toPlainText().lower()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_themes(qtbot, tmp_path, payload, theme, monkeypatch, qapp):
    monkeypatch.setenv("VASYA_THEME", theme)
    assert apply_theme(qapp) == (theme == "dark")


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_languages(qtbot, tmp_path, payload, lang):
    i18n.set_lang(lang)
    try:
        w = MainWindow(Backend(tmp_path / "R", payload)); qtbot.addWidget(w)
        assert w.nav.item(0).text() == ("Главная" if lang == "ru" else "Home")
        assert all(v[0] and v[1] for v in i18n.S.values())
    finally:
        i18n.set_lang(None)


def _to_plan(win, qtbot, wz, root):
    win.go("install")
    for _ in range(3):
        qtbot.mouseClick(wz.b_next, Qt.LeftButton)
        qtbot.waitUntil(lambda: not workers._running, timeout=60000)
    assert wz.pages.currentIndex() == 3
    wz.root_edit.setText(str(root))
    qtbot.mouseClick(wz.b_next, Qt.LeftButton)
    qtbot.waitUntil(lambda: wz.plan_result is not None and not workers._running, timeout=60000)
    assert wz.pages.currentIndex() == 4


def test_wizard_steps_match_spec(win):
    wz = win.screens["install"]
    i18n.set_lang("ru")
    try:
        from vasya.gui.screens.install_wizard import STEPS
        assert [i18n.tr(s) for s in STEPS] == ["Система", "Режим", "Компоненты", "Папка", "План",
                                               "Установка", "Проверка", "Готово"]
    finally:
        i18n.set_lang(None)
    assert wz.pages.count() == 8
    assert [wz.mode_group.button(i).text().split(" ")[0] for i in range(3)] == ["Complete", "Existing", "Selective"]


def test_wizard_plan_shows_everything_and_makes_no_changes(win, qtbot, tmp_path):
    wz = win.screens["install"]
    _to_plan(win, qtbot, wz, tmp_path / "R")
    html = wz.preview.toPlainText()
    pv = wz.plan_result["preview"]
    assert wz.plan_result["mode"] == "FULL"
    for key in ("plan_space", "plan_dl", "plan_programs", "present_items", "admin", "reboot", "plan_sys"):
        assert i18n.tr(key) in html, key
    assert pv["space_needed_human"] in html and pv["free_human"] in html
    assert wz.b_next.isEnabled() and wz.b_next.text() == i18n.tr("start_install")
    from vasya.core import txn
    from vasya.core.layout import Layout
    assert txn.all_receipts(Layout(tmp_path / "R")) == []
    assert not (tmp_path / "R").exists()


def test_wizard_low_disk_blocks_with_human_message(win, qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("VASYA_TEST_FREE_BYTES", "1000")
    wz = win.screens["install"]
    _to_plan(win, qtbot, wz, tmp_path / "R")
    from vasya.errors import explain
    e = explain("LOW_DISK", i18n.lang())
    assert e["title"] in wz.preview.toPlainText() and e["recovery"] in wz.preview.toPlainText()
    assert not wz.b_next.isEnabled()


def test_uninstall_wizard_projects_choice(win, qtbot, tmp_path):
    import json
    from vasya.core.layout import Layout
    from vasya.runtime import managed_server as ms
    pp = ms.paths(Layout(tmp_path / "R"))["projects_path"] / "1234-abcd"
    pp.mkdir(parents=True)
    (pp / "my-ospf.gns3").write_text(json.dumps({"name": "my-ospf"}))
    (Layout(tmp_path / "R").State).mkdir(parents=True, exist_ok=True)
    us = win.screens["uninstall"]; win.go("uninstall")
    qtbot.waitUntil(lambda: us.inv is not None and not workers._running, timeout=60000)
    assert [p["name"] for p in us.inv["user_projects"]] == ["my-ospf"]
    us.r2.setChecked(True)
    qtbot.mouseClick(us.b_next, Qt.LeftButton)
    assert us.pages.currentIndex() == 1 and "my-ospf" in us.pj_lbl.toPlainText()
    us.rp_export.setChecked(True)
    qtbot.mouseClick(us.b_next, Qt.LeftButton)
    assert us.pages.currentIndex() == 2 and us.b_run.isVisible()
    assert i18n.tr("pj_export") in us.confirm_view.toPlainText()
    us.r1.setChecked(True); qtbot.mouseClick(us.b_back, Qt.LeftButton); qtbot.mouseClick(us.b_back, Qt.LeftButton)
    assert us.pages.currentIndex() == 0
    qtbot.mouseClick(us.b_next, Qt.LeftButton)  # level 1 skips the projects step
    assert us.pages.currentIndex() == 2


def test_progress_sentence_format():
    from vasya.installer.progress_text import describe
    op = {"action": "REGISTER_TEMPLATE", "label": "OpenWrt"}
    assert describe(17, 44, op, "NEW", "ru") == "[17/44] OpenWrt — образ проверен, шаблон установлен"
    assert describe(17, 44, op, "NEW", "en") == "[17/44] OpenWrt — image verified, template installed"


def test_light_theme_resets_dark_palette(qapp, monkeypatch):
    monkeypatch.setenv("VASYA_THEME", "dark"); apply_theme(qapp)
    dark_win = qapp.palette().window().color().lightness()
    monkeypatch.setenv("VASYA_THEME", "light"); apply_theme(qapp)
    assert qapp.palette().window().color().lightness() > dark_win + 80


def test_invalid_root_rejected(win, qtbot):
    wz = win.screens["install"]; win.go("install"); wz.goto(3)
    wz.root_edit.setText("relative/path")
    qtbot.mouseClick(wz.b_next, Qt.LeftButton)
    assert wz.pages.currentIndex() == 3 and wz.loc_msg.text().startswith("✖")


def test_uninstall_wizard_offers_only_removable_system_packages(win, qtbot, tmp_path, monkeypatch):
    from vasya import api
    from vasya.core.layout import Layout
    Layout(tmp_path / "R").State.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(api, "system_packages_offer", lambda ctx: {
        "removable": [{"package": "qemu-system-arm", "for": "openwrt-realview"}],
        "kept": [{"package": "traceroute", "why": "was installed before VASYA"}]})
    seen = {}
    monkeypatch.setattr(api, "uninstall", lambda ctx, level, **kw: seen.update(level=level, **kw) or
                        {"status": "BLOCKED", "error": "test stop", "error_ru": "test stop", "busy": []})
    us = win.screens["uninstall"]; win.go("uninstall")
    qtbot.waitUntil(lambda: us.inv is not None and not workers._running, timeout=60000)
    us.r2.setChecked(True)
    while us.pages.currentIndex() != 2:
        qtbot.mouseClick(us.b_next, Qt.LeftButton)
    assert [c.property("pkg") for c in us.pkg_checks] == ["qemu-system-arm"]
    assert not us.pkg_checks[0].isChecked()                      # never pre-ticked
    assert "traceroute" in us.confirm_view.toPlainText()
    us.pkg_checks[0].setChecked(True)
    monkeypatch.setattr(us, "confirm", lambda *a: True)
    qtbot.mouseClick(us.b_run, Qt.LeftButton)
    qtbot.waitUntil(lambda: "level" in seen and not workers._running, timeout=30000)
    assert seen["level"] == "full" and seen["system_packages"] == ["qemu-system-arm"]


def test_home_import_button_when_no_images(qtbot, tmp_path, monkeypatch):
    from vasya import api
    w = MainWindow(Backend(tmp_path / "R", tmp_path / "empty-payload"))
    qtbot.addWidget(w); w.show()
    hs = w.screens["home"]; w.go("home")
    qtbot.waitUntil(lambda: hs.counts_value is not None and not workers._running, timeout=60000)
    assert hs.b_import.isVisible()
    called = {}
    monkeypatch.setattr(api, "import_payload", lambda ctx, m: called.update(m=m) or {"status": "OK", "files": 3})
    hs.do_import("/x/VASYA-GNS-LAB-1.1.0-Linux.tar.zst.parts.json")
    qtbot.waitUntil(lambda: "m" in called and not workers._running, timeout=30000)
    assert called["m"].endswith(".parts.json")
