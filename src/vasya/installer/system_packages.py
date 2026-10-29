# SPDX-License-Identifier: GPL-3.0-or-later
"""System packages that VASYA asked an administrator to install.

VASYA never runs apt silently. When the user approves a listed admin step (e.g. wireshark,
tigervnc-viewer, traceroute, qemu-system-arm), the state BEFORE the install is recorded in
State/receipts/system-packages.json:
    {"packages": {"<pkg>": {"was_installed_before": bool, "installed_by_vasya": bool,
                            "for": "<tool/block>", "recorded_at": ..., "removed_at": ...}}}
Full uninstall OFFERS removal only for packages with was_installed_before == false that are
still installed and have no installed reverse dependency outside the VASYA-installed set.
`run` is injectable (tests mock dpkg/apt); default runs real commands.
"""
import subprocess
from ..core.util import load_json, write_json, utc_now

FILE = "system-packages.json"


def _run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        return r.returncode, r.stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def path(ctx):
    return ctx.layout.State / "receipts" / FILE


def load(ctx):
    return load_json(path(ctx), {"packages": {}})


def _save(ctx, data):
    path(ctx).parent.mkdir(parents=True, exist_ok=True)
    write_json(path(ctx), data)


def is_installed(pkg, run=_run):
    rc, out = run(["dpkg-query", "-W", "-f=${Status}", pkg])
    return rc == 0 and "install ok installed" in out


def installed_rdepends(pkg, run=_run):
    rc, out = run(["apt-cache", "rdepends", "--installed", "--no-recommends", "--no-suggests",
                   "--no-enhances", "--no-conflicts", "--no-breaks", "--no-replaces", pkg])
    if rc != 0:
        return None  # unknown -> never offer removal
    deps, started = set(), False
    for line in out.splitlines():
        if line.strip() == "Reverse Depends:":
            started = True
            continue
        if started and line.strip():
            deps.add(line.strip().lstrip("|").strip())
    deps.discard(pkg)
    return deps


def install(ctx, pkgs, purpose="", run=_run, approved=False, admin=("pkexec",)):
    """Run an approved admin install and write receipts. Nothing happens unless approved=True."""
    if not approved:
        return {"status": "NEEDS_APPROVAL", "command": " ".join(
            ["sudo", "apt-get", "install", "--no-install-recommends", *pkgs])}
    data = load(ctx)
    before = {p: is_installed(p, run) for p in pkgs}
    for p in pkgs:  # receipt BEFORE the change (crash-safe: we know what was there)
        rec = data["packages"].get(p)
        if rec is None or rec.get("removed_at"):
            data["packages"][p] = {"was_installed_before": before[p], "installed_by_vasya": False,
                                   "for": purpose, "recorded_at": utc_now()}
    _save(ctx, data)
    todo = [p for p in pkgs if not before[p]]
    rc, out = (0, "") if not todo else run([*admin, "apt-get", "install", "-y",
                                            "--no-install-recommends", *todo])
    for p in todo:
        data["packages"][p]["installed_by_vasya"] = is_installed(p, run)
    _save(ctx, data)
    return {"status": "OK" if rc == 0 else "FAIL", "installed": [p for p in todo if
            data["packages"][p]["installed_by_vasya"]], "already_present": [p for p in pkgs if before[p]],
            "output": out[-2000:]}


def offer(ctx, run=_run):
    """What the full-uninstall wizard may offer to remove, with a reason for everything else."""
    data = load(ctx)["packages"]
    ours = {p for p, r in data.items() if r.get("installed_by_vasya") and not r.get("removed_at")}
    removable, kept = [], []
    for p, r in sorted(data.items()):
        if r.get("removed_at"):
            continue
        if r.get("was_installed_before") or not r.get("installed_by_vasya"):
            kept.append({"package": p, "why": "was installed before VASYA"}); continue
        if not is_installed(p, run):
            kept.append({"package": p, "why": "no longer installed"}); continue
        rd = installed_rdepends(p, run)
        if rd is None:
            kept.append({"package": p, "why": "could not check reverse dependencies"}); continue
        foreign = sorted(rd - ours)
        if foreign:
            kept.append({"package": p, "why": "needed by " + ", ".join(foreign[:5])}); continue
        removable.append({"package": p, "for": r.get("for")})
    return {"removable": removable, "kept": kept}


def remove(ctx, chosen, run=_run, admin=("pkexec",)):
    """Remove only chosen packages that are still in the offer (re-checked now)."""
    ok = {r["package"] for r in offer(ctx, run)["removable"]}
    todo = [p for p in chosen if p in ok]
    refused = [p for p in chosen if p not in ok]
    if not todo:
        return {"status": "NOTHING", "removed": [], "refused": refused}
    rc, out = run([*admin, "apt-get", "remove", "-y", *todo])
    data = load(ctx)
    gone = [p for p in todo if not is_installed(p, run)]
    for p in gone:
        data["packages"][p]["removed_at"] = utc_now()
    _save(ctx, data)
    return {"status": "OK" if rc == 0 and len(gone) == len(todo) else "FAIL",
            "removed": gone, "refused": refused, "output": out[-2000:]}
