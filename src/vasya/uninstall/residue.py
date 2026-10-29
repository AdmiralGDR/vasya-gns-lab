# SPDX-License-Identifier: GPL-3.0-or-later
"""Residue scan after uninstall — every key must be 0 for CLEAN_UNINSTALL."""
import os, subprocess
from pathlib import Path
from ..gns3.client import GNS3Client
from ..gns3.templates import VASYA_USAGE_TAG
from ..installer.apply import docker_cmd

KEYS = ("VASYA_FILES_LEFT", "TEMPLATES_LEFT", "VM_LEFT", "DOCKER_OBJECTS_LEFT",
        "SHORTCUTS_LEFT", "SYSTEM_CHANGES_LEFT")


def scan(inventory, api_bases, root=None, level="full", remove_docker=True, docker_root=None):
    """inventory: list of owned resources captured BEFORE uninstall."""
    left = {k: [] for k in KEYS}
    for r in inventory:
        k = r.get("kind")
        if k == "file":
            extra = (r["path"] + ".md5sum") if r.get("role") == "image" else None
            for p in (r.get("path"), r.get("partial"), extra):
                if p and (Path(p).exists() or Path(p).is_symlink()):
                    left["VASYA_FILES_LEFT"].append(p)
        elif k == "desktop_file" and Path(r["path"]).exists():
            left["SHORTCUTS_LEFT"].append(r["path"])
        elif k in ("docker_image", "docker_labeled_image") and remove_docker:
            from ..runtime.docker_backend import receipt_cmd
            cmd = receipt_cmd(r, root, docker_cmd)
            if cmd and subprocess.run(cmd + ["image", "inspect", r["ref"]],
                                      capture_output=True).returncode == 0:
                left["DOCKER_OBJECTS_LEFT"].append(r["ref"])
        elif k == "system_change":
            left["SYSTEM_CHANGES_LEFT"].append(r.get("what"))
    # sweep target dirs for stray VASYA artefacts (partials, alt-named images)
    dirs = {str(Path(r["path"]).parent) for r in inventory if r.get("kind") == "file"}
    for d in dirs:
        dp = Path(d)
        if dp.exists():
            for f in dp.iterdir():
                if f.name.endswith(".vasya-partial") or (f.name.startswith("vasya-") and
                                                         str(f) not in left["VASYA_FILES_LEFT"]):
                    if root and str(f).startswith(str(root)) and level != "full":
                        continue
                    left["VASYA_FILES_LEFT"].append(str(f))
    if level == "full" and root and Path(root).exists():
        left["VASYA_FILES_LEFT"].append(str(root))
    for base in api_bases:
        cl = GNS3Client(base)
        if cl.version() is None:
            continue
        for t in cl.templates():
            if VASYA_USAGE_TAG in (t.get("usage") or ""):
                left["TEMPLATES_LEFT"].append(f"{t['name']} ({t['template_id']})")
        for p in cl.projects():
            if p.get("name", "").startswith(("vasya-verify-", "vasya-demo-")):
                left["VM_LEFT"].append(f"project {p['name']}")
    cmd = docker_cmd()
    if cmd:
        from ..installer.apply import root_tag
        droot = docker_root or root
        rl = [] if not droot else ["--filter", f"label=org.vasya.root={root_tag(droot)}"]
        r = subprocess.run(cmd + ["ps", "-a", "--filter", "label=org.vasya.owner=vasya-gns-lab", *rl, "-q"],
                           capture_output=True, text=True)
        left["DOCKER_OBJECTS_LEFT"] += [f"container {c}" for c in r.stdout.split() if c]
        if remove_docker:
            r = subprocess.run(cmd + ["images", "-q", "--filter", "label=org.vasya.owner=vasya-gns-lab", *rl],
                               capture_output=True, text=True)
            have = set(left["DOCKER_OBJECTS_LEFT"])
            left["DOCKER_OBJECTS_LEFT"] += [f"image {i}" for i in sorted(set(r.stdout.split()))
                                            if f"image {i}" not in have]
    if root and os.name != "nt":
        r = subprocess.run(["pgrep", "-af", str(root)], capture_output=True, text=True)
        me = str(os.getpid())
        for ln in r.stdout.splitlines():
            pid = ln.split()[0]
            emu = "qemu-system" in ln or "dynamips" in ln
            if pid != me and (emu or (level == "full" and "gns3server" in ln)):
                left["VM_LEFT"].append(f"process {ln[:120]}")
    counts = {k: len(v) for k, v in left.items()}
    from ..gns3.remote_compute import manual_cleanup_hint
    manual = [manual_cleanup_hint(r) for r in inventory if r.get("kind") == "remote_image"]
    return {"counts": counts, "items": left, "clean": all(v == 0 for v in counts.values()),
            "manual_remote_steps": manual}


def render(report):
    c = report["residue"]["counts"]
    lines = ["# UNINSTALL REPORT — VASYA GNS LAB", "",
             f"- level: {report['level']}", f"- root: `{report['root']}`",
             f"- started: {report['started_at']}", f"- finished: {report.get('finished_at')}",
             f"- resources in inventory: {report['inventory_count']}",
             f"- removed: {report['removed']}  absent: {report['absent']}  kept: {report['kept']}", ""]
    lines += [f"{k}: {c[k]}" for k in KEYS]
    gc = report.get("gns3_config") or {}
    lines.append(f"EXISTING_GNS3_CONFIG: {gc.get('status', 'NOT_APPLICABLE')}"
                 + (f" ({gc.get('path')})" if gc.get("path") else ""))
    lines += ["", f"CLEAN_UNINSTALL: {'PASS' if report['residue']['clean'] else 'FAIL'}", ""]
    for k, v in report["residue"]["items"].items():
        for x in v:
            lines.append(f"- {k}: {x}")
    if report.get("kept_items"):
        lines += ["", "## Intentionally kept"] + [f"- {x}" for x in report["kept_items"]]
    if report.get("external_side_effects"):
        lines += ["", "## Known external side effects (outside the VASYA folder, not deleted)"]
        lines += [f"- `{x['path']}` — {x['why']}. {x['suggestion']}" for x in report["external_side_effects"]]
    if report.get("preserved"):
        lines += ["", "## Preserved (not VASYA-owned)"] + [f"- {x}" for x in report["preserved"]]
    return "\n".join(lines) + "\n"
