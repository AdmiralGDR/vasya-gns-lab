# SPDX-License-Identifier: GPL-3.0-or-later
"""Device consoles: probe and drive telnet consoles; build terminal launch commands."""
import os, re, shutil, socket, time

IAC = 255


def probe(host, port, timeout=3.0, want_bytes=True):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout) as s:
            if not want_bytes:
                return {"ok": True, "bytes": 0}
            s.settimeout(timeout)
            try:
                s.sendall(b"\r\n")
                data = s.recv(4096)
            except socket.timeout:
                data = b""
            return {"ok": True, "bytes": len(data)}
    except OSError as e:
        return {"ok": False, "error": str(e)}


def _strip_telnet(b):
    out, i = bytearray(), 0
    while i < len(b):
        if b[i] == IAC and i + 2 < len(b):
            i += 3
            continue
        out.append(b[i]); i += 1
    return out.decode("utf-8", "replace")


def run(host, port, commands, wait=1.5, timeout=8.0):
    """Send shell commands over a telnet console and return the transcript."""
    with socket.create_connection((host, int(port)), timeout=timeout) as s:
        s.settimeout(0.5)
        buf = b""

        def drain(t):
            nonlocal buf
            end = time.time() + t
            while time.time() < end:
                try:
                    d = s.recv(65536)
                    if not d:
                        break
                    buf += d
                except socket.timeout:
                    pass
        s.sendall(b"\r\n"); drain(1.0)
        for c in commands:
            s.sendall(c.encode() + b"\r\n")
            drain(wait)
    return _strip_telnet(buf)


def terminal_command(host, port, console_type="telnet"):
    """Command line to open a console in the user's terminal / viewer."""
    if console_type == "vnc":
        v = shutil.which("vncviewer") or shutil.which("gvncviewer") or shutil.which("remote-viewer")
        if not v:
            return None
        return [v, f"{host}::{port}"] if "vncviewer" in v else [v, f"vnc://{host}:{port}"]
    if os.name == "nt":
        return ["cmd", "/c", "start", "telnet", host, str(port)]
    for term in ("gnome-terminal", "x-terminal-emulator", "konsole", "xterm"):
        t = shutil.which(term)
        if t:
            if term == "gnome-terminal":
                return [t, "--", "telnet", host, str(port)]
            return [t, "-e", f"telnet {host} {port}"]
    return ["telnet", host, str(port)]
