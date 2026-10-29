# SPDX-License-Identifier: GPL-3.0-or-later
"""One human sentence per step: '[17/44] OpenWrt — образ проверен, шаблон установлен'."""
PHRASES = {
 "MANAGED_GNS3": ("сервер GNS3 VASYA запущен (порт {port})", "VASYA GNS3 server running (port {port})"),
 "PLACE_IMAGE": ("образ проверен и размещён", "image verified and placed"),
 "PLACE_IMAGE_ALT": ("образ размещён под отдельным именем (ваш файл не тронут)", "image placed under a separate name (your file untouched)"),
 "REUSE_IMAGE": ("образ уже на месте, проверен", "image already present, verified"),
 "PLACE_APPLIANCE": ("описание устройства добавлено", "appliance file added"),
 "ENSURE_DOCKER_IMAGE": ("Docker-образ загружен и помечен", "Docker image pulled and labelled"),
 "REGISTER_TEMPLATE": ("образ проверен, шаблон установлен", "image verified, template installed"),
 "REUSE_TEMPLATE": ("шаблон уже есть, используется повторно", "template already exists, reused"),
 "INSTALL_APP": ("программа VASYA Manager скопирована", "VASYA Manager app copied"),
 "DESKTOP_FILES_IN_ROOT": ("ярлык подготовлен в папке VASYA", "shortcut prepared in the VASYA folder"),
 "DESKTOP_ENTRY": ("ярлык добавлен в меню приложений", "applications-menu entry added"),
}
NAMES = {"MANAGED_GNS3": ("Сервер GNS3", "GNS3 server"), "INSTALL_APP": ("VASYA Manager", "VASYA Manager"),
         "DESKTOP_FILES_IN_ROOT": ("Ярлык", "Shortcut"), "DESKTOP_ENTRY": ("Ярлык", "Shortcut")}


def describe(i, n, op, res, lang="ru", detail=None):
    k = 0 if lang == "ru" else 1
    a = op.get("action", "")
    name = op.get("label") or NAMES.get(a, (a, a))[k]
    if res == "FAIL":
        from ..errors import explain
        e = explain(detail or "", lang)
        txt = ("ошибка: " if k == 0 else "error: ") + e["title"]
    elif res in ("RUNNING", "START"):
        txt = "выполняется…" if k == 0 else "in progress…"
    elif res == "SKIP":
        txt = "пропущено" if k == 0 else "skipped"
    else:
        txt = PHRASES.get(a, (a.lower(), a.lower()))[k].format(port=op.get("port", ""))
    return f"[{i}/{n}] {name} — {txt}"
