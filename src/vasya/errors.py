# SPDX-License-Identifier: GPL-3.0-or-later
"""Human-readable errors: every failure the user can meet has a code, a plain
RU/EN explanation, what state the system was left in, and a recovery action.
GUI and CLI both render `explain(...)`; nobody shows "something went wrong"."""
import re

# code: (title_ru, title_en, why_ru, why_en, state_ru, state_en, action, action_ru, action_en)
E = {
 "NO_INTERNET": ("Нет подключения к Интернету", "No Internet connection",
                 "Docker-образ не удалось скачать: сервер недоступен.", "A Docker image could not be downloaded: the registry is unreachable.",
                 "Всё, что уже установлено, сохранено. Не скачанные Docker-компоненты помечены как не установленные.",
                 "Everything already installed is kept. Docker components that were not downloaded are marked not installed.",
                 "retry", "Подключитесь к сети и нажмите «Повторить неудавшиеся»", "Reconnect and press “Retry failed”"),
 "PARTIAL_DOCKER_PULL": ("Загрузка Docker-образа оборвалась", "Docker image download was interrupted",
                         "Соединение оборвалось во время загрузки слоёв образа.", "The connection dropped while image layers were downloading.",
                         "Docker не сохраняет недокачанный образ; компонент помечен как не установленный, остальное работает.",
                         "Docker keeps no half-pulled image; the component is marked not installed, everything else works.",
                         "retry", "Нажмите «Повторить неудавшиеся» — загрузка продолжится с уже скачанных слоёв",
                         "Press “Retry failed” — the download continues from cached layers"),
 "CORRUPT_DOWNLOAD": ("Файл комплекта повреждён", "Package file is damaged",
                      "Контрольная сумма SHA-256 не совпала с ожидаемой.", "The SHA-256 checksum does not match.",
                      "Повреждённый файл не установлен и ничего не перезаписано.", "The damaged file was not installed and nothing was overwritten.",
                      "redownload", "Скачайте повреждённую часть заново и запустите установщик ещё раз (уже проверенные части не перекачиваются)",
                      "Re-download the damaged part and run the installer again (verified parts are kept)"),
 "PAYLOAD_DAMAGED": ("Образ в хранилище VASYA повреждён", "Image in the VASYA store is damaged",
                     "Файл образа в папке комплекта не совпадает со своей контрольной суммой.", "A store image does not match its checksum.",
                     "Повреждённый образ не использован.", "The damaged image was not used.",
                     "repair", "Распакуйте комплект заново или нажмите «Восстановить»", "Re-extract the bundle or press “Repair”"),
 "LOW_DISK": ("Недостаточно места на диске", "Not enough disk space",
              "Для установки нужно больше свободного места, чем есть на выбранном диске.", "The selected disk has less free space than the install needs.",
              "Установка не начиналась, ничего не изменено.", "Install did not start; nothing was changed.",
              "choose_folder", "Освободите место или выберите папку на другом диске", "Free space or choose a folder on another disk"),
 "INTERRUPTED": ("Предыдущая операция прервана", "Previous operation was interrupted",
                 "Установщик был закрыт или компьютер выключился посреди операции.", "The installer was closed or the computer stopped mid-operation.",
                 "Журнал операций сохранил каждый шаг; недоделанные файлы известны и будут убраны.",
                 "The journal recorded every step; unfinished files are known and will be cleaned up.",
                 "resume", "Нажмите «Продолжить» (доделать) или «Откатить» (вернуть как было)", "Press “Resume” (finish) or “Roll back” (undo)"),
 "NO_ADMIN": ("Нужны права администратора", "Administrator rights required",
              "Папка назначения недоступна для записи текущему пользователю.", "The target folder is not writable by the current user.",
              "Установка не начиналась, ничего не изменено.", "Install did not start; nothing was changed.",
              "choose_folder", "Выберите папку в домашнем каталоге или выполните показанную команду от имени администратора",
              "Choose a folder in your home directory or run the shown command as administrator"),
 "EXISTING_GNS3": ("Найден установленный GNS3", "Existing GNS3 found",
                   "На компьютере уже есть GNS3 со своими настройками.", "GNS3 with its own settings is already installed.",
                   "Его настройки не изменяются; перед интеграцией делается резервная копия.", "Its settings are not changed; a backup is made before integration.",
                   "mode_integration", "Выберите режим «Добавить в существующий GNS3» или «Полная лаборатория» (отдельный сервер на порту 3088)",
                   "Choose “Add to existing GNS3” or “Complete lab” (separate server on port 3088)"),
 "PORT_CONFLICT": ("Порт занят другой программой", "Port is used by another program",
                   "Порт сервера VASYA уже занят чужим процессом.", "The VASYA server port is taken by another process.",
                   "Чужая программа не тронута; сервер VASYA перенесён на свободный порт.", "The other program is untouched; the VASYA server moved to a free port.",
                   "none", "Ничего делать не нужно — новый порт записан в настройки VASYA", "Nothing to do — the new port is saved in VASYA settings"),
 "BUSY_VM": ("Устройства лаборатории сейчас запущены", "Lab devices are running",
             "Удаление или восстановление затронет образы, которые используют запущенные узлы.", "Uninstall/repair would affect images used by running nodes.",
             "Ничего не изменено.", "Nothing was changed.",
             "stop_nodes", "Остановите узлы в GNS3 (или нажмите «Остановить узлы») и повторите", "Stop the nodes in GNS3 (or press “Stop nodes”) and retry"),
 "IMAGE_NAME_CONFLICT": ("Файл с таким именем уже есть", "A file with this name already exists",
                         "В папке образов GNS3 лежит ваш файл с тем же именем, но другим содержимым.", "Your GNS3 images folder has a different file with the same name.",
                         "Ваш файл НЕ перезаписан; образ VASYA установлен под отдельным именем vasya-<sha>-…", "Your file was NOT overwritten; the VASYA image is installed as vasya-<sha>-…",
                         "none", "Ничего делать не нужно", "Nothing to do"),
 "ALREADY_INSTALLED": ("VASYA уже установлен", "VASYA is already installed",
                       "Повторная установка проверяет и переиспользует то, что уже есть.", "Reinstall verifies and reuses what is already there.",
                       "Повторно ничего не копируется; дубликаты не создаются.", "Nothing is copied twice; no duplicates are created.",
                       "repair", "Для исправления повреждений используйте «Восстановить»", "Use “Repair” to fix damage"),
 "IMAGE_MISSING": ("Образ удалён", "Image was deleted",
                   "Файл образа устройства отсутствует в папке GNS3.", "A device image file is missing from the GNS3 folder.",
                   "Остальные компоненты работают.", "Other components keep working.",
                   "repair", "Нажмите «Восстановить» — образ будет возвращён из хранилища VASYA", "Press “Repair” — the image is restored from the VASYA store"),
 "IMAGE_CORRUPT": ("Образ повреждён", "Image is damaged",
                   "Контрольная сумма образа не совпадает.", "The image checksum does not match.",
                   "Повреждённый файл будет помещён в карантин, а не удалён без следа.", "The damaged file will be quarantined.",
                   "repair", "Нажмите «Восстановить»", "Press “Repair”"),
 "GNS3_UNREACHABLE": ("GNS3 / GNS3 VM недоступен", "GNS3 / GNS3 VM unreachable",
                      "Сервер GNS3 (или GNS3 VM) не отвечает по указанному адресу.", "The GNS3 server (or GNS3 VM) does not answer at the given address.",
                      "Установка не начиналась, ничего не изменено.", "Install did not start; nothing was changed.",
                      "check_gns3", "Запустите GNS3 / GNS3 VM, проверьте адрес и сеть, затем повторите", "Start GNS3 / the GNS3 VM, check address and network, retry"),
 "MISSING_PROGRAMS": ("Не хватает программ", "Required programs are missing",
                      "Для части компонентов нужны системные программы, которых нет.", "Some components need system programs that are not installed.",
                      "Компоненты без нужной программы установятся, но не запустятся.", "Components install but will not run without them.",
                      "show_commands", "Установите перечисленные пакеты (команда показана на экране «План»)", "Install the listed packages (command on the Plan page)"),
 "UBRIDGE_CAPS": ("uBridge без сетевых прав", "uBridge lacks network capabilities",
                  "Docker-узлы и захват трафика требуют, чтобы uBridge имел CAP_NET_ADMIN/CAP_NET_RAW.", "Docker nodes need uBridge with CAP_NET_ADMIN/CAP_NET_RAW.",
                  "Остальные узлы работают.", "Other nodes work.",
                  "show_commands", "Выполните показанную команду setcap (нужен администратор)", "Run the shown setcap command (admin)"),
 "UNKNOWN": ("Ошибка", "Error", "", "", "Журнал операций содержит подробности.", "The operation journal has details.",
             "diagnostics", "Соберите диагностику (экран «Диагностика») и приложите к обращению", "Build diagnostics and attach them"),
}

PATTERNS = [
    (r"PAYLOAD_DAMAGED", "PAYLOAD_DAMAGED"),
    (r"sha-?256 mismatch|checksum mismatch|CORRUPT_PART", "CORRUPT_DOWNLOAD"),
    (r"unexpected EOF|connection reset|short read|context canceled|layer.*(failed|incomplete)", "PARTIAL_DOCKER_PULL"),
    (r"name resolution|no such host|dial tcp|network is unreachable|TLS handshake timeout|"
     r"i/o timeout|Could not resolve|Temporary failure", "NO_INTERNET"),
    (r"No space left|LOW_DISK|not enough (disk|space)", "LOW_DISK"),
    (r"Permission denied|not writable|NO_ADMIN|Operation not permitted", "NO_ADMIN"),
    (r"uBridge requires root|capability to interact", "UBRIDGE_CAPS"),
    (r"busybox", "MISSING_PROGRAMS"),
    (r"address already in use|PORT_CONFLICT", "PORT_CONFLICT"),
    (r"BUSY_VM|is running|locked by", "BUSY_VM"),
    (r"Connection refused|GNS3_UNREACHABLE|API not (reachable|available)|timed out", "GNS3_UNREACHABLE"),
    (r"different content; not overwritten|existing file differs", "IMAGE_NAME_CONFLICT"),
    (r"NEEDS_RECOVERY|INTERRUPTED|incomplete transaction", "INTERRUPTED"),
]


def classify(msg):
    s = str(msg or "")
    if s in E:
        return s
    for rx, code in PATTERNS:
        if re.search(rx, s, re.I):
            return code
    return "UNKNOWN"


def explain(code_or_msg, lang="ru", detail=None):
    code = classify(code_or_msg)
    t = E[code]
    ru = lang == "ru"
    raw = detail if detail is not None else (None if str(code_or_msg) in E else str(code_or_msg))
    return {"code": code, "title": t[0] if ru else t[1], "why": t[2] if ru else t[3],
            "state": t[4] if ru else t[5], "action": t[6], "recovery": t[7] if ru else t[8],
            "detail": (raw or "")[:400]}


def render(x):
    """Plain text block for GUI dialogs / CLI."""
    lines = [f"✖ {x['title']} [{x['code']}]"]
    for k in ("why", "state"):
        if x.get(k):
            lines.append("  " + x[k])
    lines.append("  → " + x["recovery"])
    if x.get("detail"):
        lines.append("  (" + x["detail"].strip().splitlines()[0][:200] + ")")
    return "\n".join(lines)
