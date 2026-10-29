# SPDX-License-Identifier: GPL-3.0-or-later
"""VASYA-managed GNS3 server living entirely inside the ONE-ROOT (Full mode).

The user's own ~/.config/GNS3 is never read or written by this server: it is
started with an explicit --config pointing to <root>/GNS3/gns3_server.conf.
"""
import os, signal, socket, subprocess, sys, time
from pathlib import Path
from ..gns3.client import GNS3Client

DEFAULT_PORT = 3088  # agreed: VASYA's own server, never the user's 3080


def free_port(start=DEFAULT_PORT):
    for p in range(start, start + 50):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("no free port for managed GNS3 server")


def port_busy(port):
    """True only if something is LISTENING (TIME_WAIT leftovers do not count)."""
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", int(port)))
            return False
        except OSError:
            return True


def relocate_if_busy(layout, port):
    """PORT_CONFLICT recovery: if our server is not running but its port is taken by
    a foreign process, move VASYA's server to the next free port (the other program
    is never touched). Returns (port, changed_from_or_None)."""
    if running_pid(layout) or not port_busy(port):
        return port, None
    new = free_port(int(port) + 1)
    cfg = paths(layout)["config"]
    if cfg.exists():
        import re
        txt = cfg.read_text(encoding="utf-8")
        cfg.write_text(re.sub(r"(?m)^port = \d+$", f"port = {new}", txt), encoding="utf-8")
    return new, port


def paths(layout):
    g = layout.managed_gns3
    return {"config": g / "gns3_server.conf", "images_path": g / "images",
            "appliances_path": g / "appliances", "projects_path": g / "projects",
            "configs_path": g / "configs", "symbols_path": g / "symbols",
            "pidfile": layout.State / "managed-gns3.pid", "log": layout.Logs / "gns3server.log"}


def write_config(layout, port, ubridge=None, dynamips=None, enable_kvm=True, vpcs=None):
    p = paths(layout)
    for k in ("images_path", "appliances_path", "projects_path", "configs_path", "symbols_path"):
        p[k].mkdir(parents=True, exist_ok=True)
    lines = ["[Server]", "host = 127.0.0.1", f"port = {port}",
             f"images_path = {p['images_path']}", f"projects_path = {p['projects_path']}",
             f"appliances_path = {p['appliances_path']}", f"configs_path = {p['configs_path']}",
             f"symbols_path = {p['symbols_path']}", "report_errors = False", "auth = False"]
    if ubridge:
        lines.append(f"ubridge_path = {ubridge}")
    if dynamips:
        lines += ["", "[Dynamips]", f"dynamips_path = {dynamips}"]
    if vpcs:
        lines += ["", "[VPCS]", f"vpcs_path = {vpcs}"]
    lines += ["", "[Qemu]", f"enable_kvm = {bool(enable_kvm)}", "allow_unsafe_options = True", ""]
    p["config"].write_text("\n".join(lines), encoding="utf-8")
    return p["config"]


def running_pid(layout):
    pf = paths(layout)["pidfile"]
    if not pf.exists():
        return None
    try:
        pid = int(pf.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        return None


def start(layout, server_bin, port, wait=40, extra_path=None, extra_env=None):
    p = paths(layout)
    if running_pid(layout):
        return running_pid(layout)
    env = dict(os.environ)
    xdg = layout.managed_gns3 / "xdg"
    for k, sub in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                   ("XDG_CACHE_HOME", "cache"), ("XDG_STATE_HOME", "state")):
        (xdg / sub).mkdir(parents=True, exist_ok=True)
        env[k] = str(xdg / sub)  # isolation: never create ~/.config/GNS3
    env.update(extra_env or {})
    if extra_path:
        env["PATH"] = os.pathsep.join([*extra_path, env.get("PATH", "")])
    p["log"].parent.mkdir(parents=True, exist_ok=True)
    log = open(p["log"], "ab")
    kw = {"start_new_session": True} if os.name != "nt" else {"creationflags": 0x00000200}
    proc = subprocess.Popen([server_bin, "--config", str(p["config"]), "--local",
                             "--port", str(port), "--host", "127.0.0.1"],
                            stdout=log, stderr=subprocess.STDOUT, env=env, **kw)
    p["pidfile"].write_text(str(proc.pid))
    cl = GNS3Client(f"http://127.0.0.1:{port}")
    t0 = time.time()
    while time.time() - t0 < wait:
        if proc.poll() is not None:
            raise RuntimeError(f"gns3server exited rc={proc.returncode}; see {p['log']}")
        if cl.version(timeout=0.5):
            return proc.pid
        time.sleep(0.4)
    raise RuntimeError("managed gns3server did not answer in time")


def stop(layout, timeout=15):
    """Stop VASYA's gns3server, then VASYA's own podman service (started for it; no-op if absent)."""
    r = _stop_gns3(layout, timeout)
    if os.name != "nt":
        from . import docker_backend as dbk
        dbk.stop_service(layout.root)
    return r


def _stop_gns3(layout, timeout=15):
    pid = running_pid(layout)
    pf = paths(layout)["pidfile"]
    if not pid:
        pf.unlink(missing_ok=True)
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            os.kill(pid, 0)
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass
        except ProcessLookupError:
            break
        time.sleep(0.2)
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    pf.unlink(missing_ok=True)
    return True
