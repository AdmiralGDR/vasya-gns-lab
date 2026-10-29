# SPDX-License-Identifier: GPL-3.0-or-later
"""RU/EN strings. Language follows the system locale; VASYA_LANG=ru|en overrides."""
import locale, os

S = {
 "app_title": ("VASYA GNS LAB Manager", "VASYA GNS LAB Manager"),
 "nav_home": ("Главная", "Home"), "nav_install": ("Установка", "Install"),
 "nav_catalog": ("Каталог", "Catalog"), "nav_verify": ("Проверка", "Verify"),
 "nav_repair": ("Восстановление", "Repair"), "nav_uninstall": ("Удаление", "Uninstall"),
 "nav_logs": ("Журнал", "Logs"), "nav_diag": ("Диагностика", "Diagnostics"),
 "nav_tools": ("Инструменты", "Tools"), "nav_ready": ("Лаборатория", "Lab"),
 "version": ("Версия", "Version"), "root": ("Папка VASYA", "VASYA folder"),
 "gns3": ("GNS3", "GNS3"), "present": ("найден", "found"), "absent": ("не найден", "not found"),
 "managed": ("собственный сервер VASYA", "VASYA-managed server"),
 "existing": ("существующий GNS3", "existing GNS3"),
 "runtimes": ("Среды выполнения", "Runtimes"), "components": ("Компоненты", "Components"),
 "catalog_n": ("в каталоге", "in catalog"), "ready_n": ("готовы к установке", "ready"),
 "installed_n": ("установлены", "installed"), "verified_n": ("проверены запуском", "runtime-verified"),
 "errors_n": ("с ошибками", "with errors"), "refresh": ("Обновить", "Refresh"),
 "verdict": ("Состояние", "State"),
 "V_NOT_INSTALLED": ("Не установлено", "Not installed"),
 "V_INSTALLED_UNVERIFIED": ("Установлено, запуск не проверен", "Installed, not runtime-verified"),
 "V_HEALTHY_VERIFIED": ("Всё работает (проверено запуском)", "Healthy (runtime-verified)"),
 "V_DEGRADED": ("Есть ошибки — нужна проверка/восстановление", "Errors — verify / repair"),
 "V_NEEDS_RECOVERY": ("Прерванная операция — нажми «Продолжить»", "Interrupted operation — resume"),
 "import_payload": ("Загрузить образы из скачанного архива…", "Load images from the downloaded archive…"),
 "import_hint": ("Образов ещё нет. Укажите файл VASYA-GNS-LAB-…-Linux.tar.zst.parts.json рядом с частями .partNNN",
                 "No images yet. Choose the VASYA-GNS-LAB-…-Linux.tar.zst.parts.json next to the .partNNN files"),
 "resume": ("Продолжить прерванную установку", "Resume interrupted install"),
 "next": ("Далее", "Next"), "back": ("Назад", "Back"), "cancel": ("Отмена", "Cancel"),
 "start_install": ("Установить", "Install"), "finish": ("Готово", "Finish"),
 "w1": ("Добро пожаловать", "Welcome"), "w2": ("Проверка системы", "System check"),
 "w3": ("Режим установки", "Install mode"), "w4": ("Выбор компонентов", "Components"),
 "w5": ("Расположение", "Location"), "w6": ("Что изменится", "Change preview"),
 "w7": ("Установка", "Installing"), "w8": ("Завершено", "Done"),
 "mode_full": ("Полная лаборатория — собственный GNS3-сервер VASYA внутри папки VASYA (порт 3088). Ваш GNS3 не затрагивается.",
               "Full lab — VASYA's own GNS3 server inside the VASYA folder (port 3088). Your GNS3 is untouched."),
 "mode_integration": ("Интеграция — добавить компоненты в уже установленный GNS3 (его настройки не меняются, делается резервная копия).",
                      "Integration — add components to your existing GNS3 (config untouched, backed up)."),
 "mode_selective": ("Выборочно — только отмеченные компоненты", "Selective — only the checked components"),
 "allow_copy": ("Разрешить полное копирование образов, если жёсткая ссылка невозможна", "Allow full image copies when hardlinks are impossible"),
 "register_menu": ("Добавить в меню приложений (~/.local/share/applications)", "Add to the applications menu"),
 "space": ("Будет скопировано", "Will copy"), "linked": ("Будет связано (без копирования)", "Linked (no copy)"),
 "free": ("Свободно", "Free"), "downloads": ("Загрузки", "Downloads"), "deps": ("Не хватает программ", "Missing programs"),
 "present_items": ("Уже есть (будет переиспользовано)", "Already present (reused)"),
 "admin": ("Нужны права администратора", "Administrator rights needed"),
 "reboot": ("Нужен перезаход/перезагрузка", "Re-login / reboot needed"),
 "safe_cancel": ("Отмена в любой момент откатит всё, что успело создаться.", "Cancel at any time rolls back everything created so far."),
 "conflicts": ("Конфликты (ваши файлы НЕ перезаписываются)", "Conflicts (your files are NOT overwritten)"),
 "blocked": ("Заблокировано (нужно разрешить копирование)", "Blocked (copy not allowed)"),
 "yes": ("да", "yes"), "no": ("нет", "no"), "none": ("нет", "none"),
 "search": ("Поиск…", "Search…"), "all": ("Все", "All"), "status": ("Статус", "Status"),
 "category": ("Категория", "Category"), "runtime": ("Среда", "Runtime"),
 "own_image": ("Указать собственный образ…", "Use my own image…"),
 "register": ("Зарегистрировать", "Register"), "details": ("Подробности", "Details"),
 "verify_static": ("Проверить файлы и шаблоны", "Verify files & templates"),
 "verify_all_ok": ("Всё в порядке: проверено компонентов — {n}, проблем нет.", "All good: {n} components checked, no problems."),
 "verify_bad": ("Найдено проблем: {n}. Нажмите «Восстановить» — VASYA вернёт исходные файлы из своего хранилища.",
                "Problems found: {n}. Press \u201cRepair\u201d — VASYA restores the original files from its store."),
 "verify_rt_ok": ("Запуск проверен: {p} из {t} устройств создаются, запускаются и отвечают в консоли.",
                  "Runtime verified: {p} of {t} devices create, start and answer on the console."),
 "go_repair": ("Восстановить…", "Repair…"),
 "verify_runtime": ("Проверить запуском (создать/старт/консоль/стоп)", "Runtime check (create/start/console/stop)"),
 "repair_btn": ("Восстановить установку", "Repair installation"),
 "un_level1": ("Удалить компоненты лаборатории из GNS3 (VASYA остаётся для быстрой переустановки)",
               "Remove lab components from GNS3 (keep VASYA for quick reinstall)"),
 "un_level2": ("Полностью удалить VASYA GNS LAB (включая папку VASYA)", "Completely remove VASYA GNS LAB (incl. VASYA folder)"),
 "un_docker": ("Удалить Docker-образы, загруженные VASYA (используемые другими контейнерами — не трогаются)",
               "Remove Docker images pulled by VASYA (images used by other containers are kept)"),
 "un_keep_projects": ("Сохранить мои проекты из лаборатории VASYA в домашнюю папку", "Back up my VASYA-lab projects to home"),
 "un_run": ("Удалить", "Uninstall"), "un_confirm": ("Точно удалить? Действие необратимо.", "Really uninstall? This cannot be undone."),
 "diag_btn": ("Собрать VASYA-DIAGNOSTICS.zip", "Build VASYA-DIAGNOSTICS.zip"),
 "diag_note": ("Пароли, ключи и токены вырезаются; содержимое проектов не включается.", "Passwords, keys, tokens redacted; project contents excluded."),
 "open_folder": ("Открыть папку", "Open folder"),
 "pt": ("Cisco Packet Tracer (необязательно)", "Cisco Packet Tracer (optional)"),
 "pt_import": ("Указать скачанный установщик…", "Select downloaded installer…"),
 "pt_link": ("Официальная страница NetAcad", "Official NetAcad page"),
 "pt_note": ("VASYA не скачивает и не включает Packet Tracer и никогда не спрашивает пароль Cisco.",
             "VASYA never downloads/bundles Packet Tracer and never asks for Cisco passwords."),
 "ready_title": ("Лаборатория готова", "Your lab is ready"),
 "ready_text": ("Что дальше: откройте GNS3, выберите устройства в каталоге слева и соединяйте их. Ниже — готовые демо-лаборатории (создаются только по вашему выбору).",
                "Next: open GNS3, drag devices and connect them. Demo labs below are created only on your request."),
 "demo_create": ("Создать проект", "Create project"), "demo_check": ("Запустить проверку", "Run check"),
 "demo_remove": ("Удалить демо", "Remove demo"), "open_gns3": ("Открыть GNS3", "Open GNS3"),
 "busy": ("Выполняется…", "Working…"), "done": ("Готово", "Done"), "error": ("Ошибка", "Error"),
 "menu_register": ("Добавить в меню приложений", "Add to app menu"),
 "menu_unregister": ("Убрать из меню приложений", "Remove from app menu"),
 "lang": ("Язык", "Language"),
 "s1": ("Система", "System"), "s2": ("Режим", "Mode"), "s3": ("Компоненты", "Components"),
 "s4": ("Папка", "Folder"), "s5": ("План", "Plan"), "s6": ("Установка", "Install"),
 "s7": ("Проверка", "Verify"), "s8": ("Готово", "Done"),
 "m_complete": ("Complete Lab — полная лаборатория", "Complete Lab"),
 "m_complete_d": ("Собственный сервер GNS3 VASYA внутри папки VASYA (порт 3088) и все 44 компонента. Ваш GNS3 и его настройки не затрагиваются. Рекомендуется.",
                  "VASYA's own GNS3 server inside the VASYA folder (port 3088) plus all 44 components. Your GNS3 and its settings are untouched. Recommended."),
 "m_existing": ("Existing GNS3 — добавить в мой GNS3", "Existing GNS3 — add to my GNS3"),
 "m_existing_d": ("Шаблоны и образы добавляются в уже установленный GNS3 (на Windows — в GNS3 VM). Его конфигурация не меняется, делается резервная копия.",
                  "Templates and images are added to your installed GNS3 (on Windows: the GNS3 VM). Its configuration is not changed; a backup is made."),
 "m_selective": ("Selective — выборочно", "Selective"),
 "m_selective_d": ("Только отмеченные на следующем шаге компоненты (в лабораторию VASYA или в ваш GNS3).",
                   "Only the components you tick on the next step (into the VASYA lab or your GNS3)."),
 "sel_all": ("Отметить все", "Select all"), "sel_none": ("Снять все", "Select none"),
 "api_label": ("Адрес GNS3 (для режима Existing GNS3), например http://127.0.0.1:3080 или адрес GNS3 VM",
               "GNS3 address (Existing GNS3 mode), e.g. http://127.0.0.1:3080 or the GNS3 VM address"),
 "plan_space": ("Место на диске", "Disk space"), "plan_need": ("потребуется", "required"),
 "plan_dl": ("Загрузка из Интернета", "Internet download"), "plan_programs": ("Программы", "Programs"),
 "plan_sys": ("Изменения вне папки VASYA (каждое отдельно)", "Changes outside the VASYA folder (each one listed)"),
 "plan_nosys": ("Нет — всё остаётся внутри папки VASYA", "None — everything stays inside the VASYA folder"),
 "plan_existing": ("Найден ваш GNS3", "Your GNS3 was found"), "plan_nochange": ("Пока вы не нажмёте «Установить», ничего не меняется.", "Nothing changes until you press Install."),
 "required": ("нужна", "required"), "optional": ("необязательна", "optional"),
 "cur_op": ("Сейчас", "Now"), "verify_wait": ("Проверяю файлы и шаблоны…", "Verifying files and templates…"),
 "retry_failed": ("Повторить неудавшиеся", "Retry failed"), "rollback": ("Откатить установку", "Roll back install"),
 "open_lab": ("Открыть лабораторию", "Open the lab"), "stop_nodes": ("Остановить узлы", "Stop nodes"),
 "un_s1": ("Что будет удалено", "What will be removed"), "un_s2": ("Ваши проекты", "Your projects"),
 "un_s3": ("Подтверждение", "Confirm"), "un_s4": ("Отчёт", "Report"),
 "pj_export": ("Экспортировать в ZIP-архив в домашней папке", "Export to a ZIP archive in your home folder"),
 "pj_keep": ("Сохранить: перенести папки проектов в домашнюю папку", "Keep: move project folders to your home folder"),
 "pj_delete": ("Удалить вместе с VASYA", "Delete together with VASYA"),
 "pj_none": ("Ваших проектов внутри папки VASYA нет — этот шаг пропускается.", "No projects of yours inside the VASYA folder — step skipped."),
 "theme": ("Тема", "Theme"),
}

_lang = None


def lang():
    global _lang
    if _lang is None:
        env = os.environ.get("VASYA_LANG")
        if env in ("ru", "en"):
            _lang = env
        else:
            loc = (locale.getlocale()[0] or os.environ.get("LANG") or "").lower()
            _lang = "ru" if loc.startswith("ru") else "en"
    return _lang


def set_lang(v):
    global _lang
    _lang = v


def tr(key):
    v = S.get(key)
    if not v:
        return key
    return v[0] if lang() == "ru" else v[1]
