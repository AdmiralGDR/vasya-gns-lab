# SPDX-License-Identifier: GPL-3.0-or-later
"""Cisco Packet Tracer: detection + import of a user-provided OFFICIAL installer.

Policy: VASYA never bundles, downloads or mirrors Packet Tracer and never asks
for / stores Cisco NetAcad credentials. The only link shown is the official
NetAcad lab-downloads page. The user downloads the installer themselves; VASYA
can verify that the file they point to is a Packet Tracer installer and record
its SHA-256, then hand off to the OS installer (which needs the user's consent).
"""
import os, platform as _pl, shutil, subprocess, tarfile, io
from pathlib import Path
from ..core.util import hashes_file, human_bytes

OFFICIAL_URL = "https://www.netacad.com/resources/lab-downloads"
STATES = ("INSTALLED", "AVAILABLE_TO_INSTALL", "USER_ACTION_REQUIRED", "UNSUPPORTED", "NOT_TESTED")


def detect(platform, imported=None):
    res = {"status": "NOT_TESTED", "path": None, "version": None, "official_url": OFFICIAL_URL,
           "notes": []}
    machine = _pl.machine().lower()
    if machine not in ("x86_64", "amd64"):
        res.update(status="UNSUPPORTED", notes=[f"Packet Tracer ships for x86_64 only (host {machine})"])
        return res
    for c in platform.packet_tracer_candidates():
        if Path(c).exists():
            res.update(status="INSTALLED", path=str(c))
            break
    if res["status"] != "INSTALLED":
        w = platform.which("packettracer") or platform.which("PacketTracer")
        if w:
            res.update(status="INSTALLED", path=w)
    if res["status"] != "INSTALLED" and platform.name == "linux" and shutil.which("dpkg-query"):
        r = subprocess.run(["dpkg-query", "-W", "-f=${Status} ${Version}", "packettracer"],
                           capture_output=True, text=True)
        if r.returncode == 0 and "install ok installed" in r.stdout:
            res.update(status="INSTALLED", version=r.stdout.split()[-1], path="dpkg:packettracer")
    if res["status"] == "INSTALLED":
        return res
    if imported and Path(imported.get("path", "")).exists() and imported.get("verified"):
        res.update(status="AVAILABLE_TO_INSTALL", installer=imported)
        res["notes"].append("Verified official installer imported; installation needs your confirmation")
    else:
        res.update(status="USER_ACTION_REQUIRED")
        res["notes"].append("Download the installer yourself from the official NetAcad page "
                            "(free Cisco account). VASYA never asks for your Cisco password.")
    return res


def _deb_control(path):
    """Read control file of a .deb (ar archive) without dpkg."""
    with open(path, "rb") as f:
        if f.read(8) != b"!<arch>\n":
            return None
        while True:
            hdr = f.read(60)
            if len(hdr) < 60:
                return None
            name = hdr[:16].decode().strip().rstrip("/")
            size = int(hdr[48:58].decode().strip())
            data = f.read(size)
            if size % 2:
                f.read(1)
            if name.startswith("control.tar"):
                mode = {"control.tar.gz": "r:gz", "control.tar.xz": "r:xz",
                        "control.tar.zst": None}.get(name, "r:*")
                if mode is None:
                    return {"_raw": "zstd control (not parsed)"}
                with tarfile.open(fileobj=io.BytesIO(data), mode=mode) as t:
                    for m in t.getmembers():
                        if m.name.endswith("control"):
                            txt = t.extractfile(m).read().decode("utf-8", "replace")
                            return dict(l.split(":", 1) for l in txt.splitlines()
                                        if ":" in l and not l.startswith(" "))
                return None


def verify_installer(path, platform_name):
    p = Path(path)
    out = {"path": str(p), "verified": False, "checks": []}
    if not p.is_file():
        out["error"] = "file not found"
        return out
    sha, md5, size = hashes_file(p)
    out.update(sha256=sha, size=size, size_human=human_bytes(size))
    if size < 50 * 1024 * 1024:
        out["checks"].append("FAIL size < 50 MiB (official installers are ~200+ MiB)")
        return out
    if platform_name == "linux":
        ctl = _deb_control(p)
        if not ctl:
            out["checks"].append("FAIL not a Debian package")
            return out
        pkg = (ctl.get("Package") or "").strip()
        maint = (ctl.get("Maintainer") or "").strip()
        out.update(package=pkg, version=(ctl.get("Version") or "").strip(), maintainer=maint)
        ok_pkg = pkg.lower() == "packettracer"
        ok_maint = "cisco" in maint.lower()
        out["checks"] += [("PASS" if ok_pkg else "FAIL") + f" package name '{pkg}'",
                          ("PASS" if ok_maint else "FAIL") + f" maintainer '{maint}'"]
        out["verified"] = ok_pkg and ok_maint
        out["install_command"] = f"sudo apt install {p}"
    else:
        with open(p, "rb") as f:
            is_pe = f.read(2) == b"MZ"
        out["checks"].append(("PASS" if is_pe else "FAIL") + " PE executable")
        sig = authenticode(p)
        out["signature"] = sig
        ok = is_pe and sig.get("status") == "Valid" and "cisco" in (sig.get("signer") or "").lower()
        out["checks"].append(("PASS" if ok else "FAIL") + f" Authenticode {sig}")
        out["verified"] = ok
        out["install_command"] = f'"{p}"'
    return out


def authenticode(p):
    if os.name != "nt":
        return {"status": "NOT_TESTED", "signer": None, "note": "Authenticode check needs Windows"}
    ps = ("$s=Get-AuthenticodeSignature -LiteralPath '%s';"
          "Write-Output ($s.Status.ToString()+'|'+$s.SignerCertificate.Subject)") % str(p).replace("'", "''")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    st, _, signer = (r.stdout.strip() + "|").partition("|")
    return {"status": st, "signer": signer.strip("|")}
