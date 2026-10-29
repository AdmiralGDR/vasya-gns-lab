# VASYA GNS LAB 1.1.0 — Удаление / Uninstall guide

## RU
Меню «Удаление» (4 шага): **Что будет удалено** → **Ваши проекты** → **Подтверждение** → **Отчёт**.
Командная строка: `vasya uninstall --level components|full [--remove-docker] [-y]`.

| Уровень | Удаляется | Остаётся |
|---|---|---|
| components | всё, что VASYA добавила в GNS3: шаблоны, образы, appliance-файлы, демо/проверочные проекты | приложение, хранилище образов (Store), Docker-образы — переустановка мгновенная |
| full | components + сервер GNS3 VASYA, ярлык, при желании Docker-образы VASYA, выбранные вами системные пакеты, вся папка VASYA | ваш GNS3, его настройки, ваши шаблоны/образы/проекты вне папки VASYA |

Правила безопасности:
- Удаляется только то, что записано в квитанциях **и** совпадает по sha256/размеру. Изменённый вами файл
  остаётся (KEPT_MODIFIED); файл без квитанции остаётся всегда; по имени ничего не удаляется.
- Образы-жёсткие ссылки (link count > 1) удаляются только как ссылка VASYA — ваша копия цела.
- Docker: удаляется только образ, который VASYA сама скачала/загрузила (не существовавший до неё) и который не
  используется чужими контейнерами. `docker prune` и `rmi -f` не используются никогда.
- Системные пакеты (wireshark, tigervnc-viewer, traceroute, qemu-system-arm) предлагаются к удалению только если
  их не было до VASYA (`was_installed_before=false`) и от них не зависят другие установленные пакеты. Галочки
  по умолчанию сняты; удаление выполняется через pkexec (нужен пароль администратора).
- Проекты внутри папки VASYA: экспорт в ZIP в домашнюю папку, перенос в домашнюю папку или удаление — на ваш выбор.
- Если устройства запущены — VASYA попросит их остановить (или остановит по кнопке «Остановить узлы»).
- Отчёт сохраняется в домашнюю папку (`VASYA-GNS-LAB-UNINSTALL-REPORT.md`), включая найденные «остатки»
  вне папки VASYA, которые не принадлежат VASYA (только список, без удаления), и «Известные внешние побочные эффекты»:
  `~/.vnc`, созданный vncviewer (команда `rm -r ~/.vnc` предлагается, только если папки не было до VASYA; сама не удаляется).

Windows: «Параметры → Приложения → VASYA GNS LAB → Удалить» запускает тот же деинсталлятор
(уровень components, затем удаление файлов приложения). Ваши файлы, положенные в папку установки, не удаляются.

## EN
Menu "Uninstall" (4 steps): **What will be removed** → **Your projects** → **Confirm** → **Report**.
CLI: `vasya uninstall --level components|full [--remove-docker] [-y]`.

| Level | Removed | Kept |
|---|---|---|
| components | everything VASYA added to GNS3: templates, images, appliance files, demo/verify projects | the app, the image store, Docker images — reinstall is instant |
| full | components + VASYA's GNS3 server, shortcut, optionally VASYA's Docker images, system packages you tick, the whole VASYA folder | your GNS3, its settings, your own templates/images/projects outside the VASYA folder |

Safety rules:
- Only what is in a receipt **and** still matches its sha256/size is removed. A file you changed is kept
  (KEPT_MODIFIED); a file without a receipt is always kept; nothing is deleted by name.
- Hardlinked images (link count > 1): only VASYA's link is removed — your copy stays.
- Docker: only images VASYA pulled/loaded itself (not pre-existing) and not used by foreign containers are removed.
  Never `docker prune`, never `rmi -f`.
- System packages (wireshark, tigervnc-viewer, traceroute, qemu-system-arm) are offered for removal only when they were
  not installed before VASYA (`was_installed_before=false`) and no other installed package depends on them. Unticked by
  default; removal runs via pkexec (admin password).
- Projects inside the VASYA folder: export to a ZIP in your home folder, move to your home folder, or delete — your choice.
- If devices are running VASYA asks you to stop them (or stops them with "Stop nodes").
- The report is saved to your home folder (`VASYA-GNS-LAB-UNINSTALL-REPORT.md`), including residue found outside the
  VASYA folder that is not VASYA's (listed only, never deleted), and "Known external side effects": `~/.vnc` created
  by vncviewer — with `rm -r ~/.vnc` suggested only if it did not exist before VASYA (never deleted automatically).

Windows: Settings → Apps → VASYA GNS LAB → Uninstall runs the same uninstaller (components level, then app files).
Files you put into the install folder yourself are not deleted.
