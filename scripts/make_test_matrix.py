#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""junit xml -> docs/TEST_MATRIX.csv (one row per test; platform column = where it ran)."""
import csv, sys, xml.etree.ElementTree as ET
from pathlib import Path

AREA = {"test_gui": "GUI", "test_template_fixes": "Template fix regressions (D1-D7)", "test_error": "Error scenarios", "test_fetch": "Automatic downloads", "test_public": "Public release content",
        "test_vpcs": "Runtime/VPCS", "test_gui_deps": "D4 GUI libs", "test_parts": "Delivery/parts",
        "test_bootstrap": "Delivery/Setup.sh", "test_payload": "Payload import", "test_rollback": "Rollback/ownership",
        "test_uninstall": "Uninstall", "test_kvm": "KVM probe", "test_docker": "Docker backend", "test_podman": "Docker backend (rootless podman)",
        "test_gns3server_docker_patch": "gns3server 3-part docker patch", 
        "test_syspkg": "System-package receipts", "test_windows": "Windows build"}


def area(mod):
    for k, v in AREA.items():
        if mod.startswith(k):
            return v
    return mod.replace("test_", "").replace("_", " ")


def main(xml_path, out, platform="Debian 13 build host (x86_64, Xvfb)"):
    root = ET.parse(xml_path).getroot()
    rows = []
    for tc in root.iter("testcase"):
        mod = tc.get("classname", "").split(".")[-1]
        st = "PASS"
        for tag, s in (("failure", "FAIL"), ("error", "ERROR"), ("skipped", "SKIPPED")):
            e = tc.find(tag)
            if e is not None:
                st = s
                note = (e.get("message") or "")[:160]
                break
        else:
            note = ""
        rows.append([area(mod), mod, tc.get("name"), platform, st, f"{float(tc.get('time', 0)):.1f}", note])
    rows.sort()
    for plat in ("Pop!_OS 24.04 / Ubuntu 24.04 desktop", "Windows 10/11"):
        rows.append(["Release acceptance", "-", "install/verify/uninstall on real host", plat, "PENDING" if
                     plat.startswith("Pop") else "UNVERIFIED", "", "needs a run on a real desktop"])
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["area", "module", "test", "platform", "status", "seconds", "note"])
        w.writerows(rows)
    c = {}
    for r in rows:
        c[r[4]] = c.get(r[4], 0) + 1
    print(c)


if __name__ == "__main__":
    main(*sys.argv[1:3])
