# SPDX-License-Identifier: GPL-3.0-or-later
"""HTML renderers for the plan screen and human-readable error cards."""
from html import escape as h
from .i18n import tr, lang
from ..errors import explain

OK, BAD, WARN = "#2e9d52", "#d23c3c", "#c98a00"


def _yn(b):
    return tr("yes") if b else tr("no")


def mark(ok):
    return f'<b style="color:{OK if ok else BAD}">{"✔" if ok else "✖"}</b>'


def plan_html(p, blocked=None):
    pv = p["preview"]
    ru = lang() == "ru"
    o = [f"<h3>{tr('s5')}: {p['summary']['operations']} "
         f"{'операций' if ru else 'operations'}, {pv['blocks']} {'компонентов' if ru else 'components'}</h3>"]
    if blocked:
        o.append(error_html(blocked))
    o.append(f"<p><b>{tr('plan_space')}:</b> {tr('plan_need')} <b>{h(pv['space_needed_human'])}</b> "
             f"({tr('space').lower()} {h(pv['bytes_to_copy_human'])}; {tr('linked').lower()} {h(pv['bytes_linked_human'])}) · "
             f"{tr('free').lower()} <b>{h(pv['free_human'])}</b> {mark(pv['space_ok'])}</p>")
    dl = pv.get("downloads") or []
    o.append(f"<p><b>{tr('plan_dl')}:</b> " + (f"<b>{h(pv['download_human'])}</b> — {len(dl)} Docker "
             f"{'образов (сжатый размер, измерен в реестре)' if ru else 'images (compressed, measured from the registry)'}"
             if dl else tr("none")) + "</p>")
    if dl:
        o.append("<p style='margin-left:16px;font-size:small'>" + ", ".join(
            f"{h(d['ref'])} ({_hb(d.get('bytes'))})" for d in dl) + "</p>")
    o.append(f"<p><b>{tr('plan_programs')}:</b></p><table cellspacing=0 cellpadding=2 style='margin-left:16px'>")
    for pr in pv.get("programs", []):
        st = mark(pr["present"]) if pr["required"] or pr["present"] else f'<span style="color:{WARN}">–</span>'
        o.append(f"<tr><td>{st}</td><td><b>{h(pr['id'])}</b></td><td>{tr('required') if pr['required'] else tr('optional')}</td>"
                 f"<td>{h(pr['path'] or ('→ ' + pr['package']))}</td></tr>")
    o.append("</table>")
    o.append(f"<p><b>{tr('present_items')}:</b> {len(pv['already_present'])}"
             + (f" · {'повторная установка: дубликаты не создаются' if ru else 'reinstall: no duplicates created'}"
                if pv.get("reinstall") else "") + "</p>")
    o.append(f"<p><b>{tr('admin')}:</b> {_yn(pv['admin_required'])} {h(pv.get('admin_reason') or '')}</p>")
    rb = pv.get("reboot_or_relogin") or []
    if ru:
        rb = [x.replace("(re-login required)", "(нужно выйти и войти снова)") for x in rb]
    o.append(f"<p><b>{tr('reboot')}:</b> {h('; '.join(rb)) if rb else tr('no')}</p>")
    sc = [c for c in pv.get("system_changes", []) if not c.get("inside_root")]
    o.append(f"<p><b>{tr('plan_sys')}:</b> " + ("" if sc else tr("plan_nosys")) + "</p>")
    if sc:
        o.append("<ol>")
        for c in sc:
            o.append(f"<li><b>{h(_what(c, ru))}</b> [{h(_KIND.get(c['kind'], (c['kind'],) * 2)[0 if ru else 1])}]" + (" — <span style='color:%s'>%s</span>" % (WARN, tr('admin')) if c.get("admin") else "")
                     + f"<br><code>{h(c['command'])}</code><br><small>{'отмена' if ru else 'undo'}: {h(c['undo'])}</small></li>")
        o.append("</ol>")
    ex = pv.get("existing_gns3") or {}
    if ex.get("found"):
        o.append(f"<p><b>{tr('plan_existing')}:</b> {h(ex.get('config') or ex.get('api_base') or ex.get('gui') or '')}"
                 f" — {'его настройки не изменяются' if ru else 'its settings are not changed'}.</p>")
    if pv["conflicts"]:
        o.append(f"<p><b>{tr('conflicts')}:</b></p><ul>" + "".join(
            f"<li>{h(c['path'])} → {h(c['installed_as'])}</li>" for c in pv["conflicts"]) + "</ul>")
    if pv["blocked_images"]:
        o.append(f"<p style='color:{BAD}'><b>{tr('blocked')}:</b> {len(pv['blocked_images'])}</p>")
    tgt = p["target"]
    o.append(f"<p><b>GNS3:</b> {h(str(tgt.get('api_base') or ''))} "
             f"({tr('managed') if tgt.get('managed') else tr('existing')})</p>")
    o.append(f"<p><i>{tr('safe_cancel')} {tr('plan_nochange')}</i></p>")
    return "\n".join(o)


def _hb(n):
    from ..core.util import human_bytes
    return human_bytes(n) if n else "?"


def error_html(err_or_msg):
    e = err_or_msg if isinstance(err_or_msg, dict) and "title" in err_or_msg else explain(err_or_msg, lang())
    return (f"<div style='border-left:4px solid {BAD};padding-left:8px;margin:6px 0'>"
            f"<b style='color:{BAD}'>✖ {h(e['title'])}</b> <small>[{e['code']}]</small><br>{h(e['why'])}<br>"
            f"<i>{h(e['state'])}</i><br><b>→ {h(e['recovery'])}</b>"
            + (f"<br><small style='color:gray'>{h(e['detail'][:300])}</small>" if e.get("detail") else "") + "</div>")


_KIND = {"package": ("пакет", "package"), "group": ("группа", "group"),
         "capability": ("права файла", "capability"), "program": ("программа", "program"),
         "docker_images": ("Docker-образы", "Docker images"), "shortcut": ("ярлык", "shortcut")}


def _what(c, ru):
    """Backend descriptions are English (they also go to logs/CLI); the RU GUI
    shows a translated sentence for the kinds whose text is fixed."""
    if not ru:
        return c["what"]
    w = c["what"]
    if c["kind"] == "docker_images":
        n = w.split()[0]
        if "podman" in w:
            return (f"{n} Docker-образа(ов) в собственном rootless-хранилище podman внутри папки VASYA (из "
                    "офлайн-архивов, без загрузки из Интернета; ваш Docker не используется и не меняется)")
        return (f"{n} Docker-образа(ов) в общем Docker (с меткой org.vasya.owner; при удалении VASYA "
                "убираются, если их не используют другие контейнеры)")
    if c["kind"] == "shortcut":
        return "ярлык vasya-gns-lab.desktop в меню приложений"
    if c["kind"] == "group":
        return w.replace("user → group", "пользователь → группа")
    return w
