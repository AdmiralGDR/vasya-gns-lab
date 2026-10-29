# SPDX-License-Identifier: GPL-3.0-or-later
"""Single state store shared by CLI and GUI (State/state.json)."""
import os
from contextlib import contextmanager
from .util import load_json, write_json, utc_now
from .. import VERSION

DEFAULT = {
    "product_version": VERSION,
    "created_at": None,
    "updated_at": None,
    "mode": None,             # FULL | INTEGRATION | SELECTIVE
    "gns3": {},               # target GNS3: api_base, images_path, appliances_path, managed
    "components": {},         # block_id -> {installed, txid, runtime_verified, verified_at, error}
    "desktop": {},
    "demos": {},
    "first_run_done": False,
    "last_operation": None,
}


class StateStore:
    def __init__(self, layout):
        self.layout = layout
        self.path = layout.state_file

    def load(self):
        data = load_json(self.path, None)
        if data is None:
            data = dict(DEFAULT, created_at=None)
        for k, v in DEFAULT.items():
            data.setdefault(k, v if not isinstance(v, dict) else dict(v))
        return data

    def save(self, data):
        data["updated_at"] = utc_now()
        data.setdefault("created_at", data["updated_at"])
        if not data.get("created_at"):
            data["created_at"] = data["updated_at"]
        write_json(self.path, data)

    @contextmanager
    def edit(self):
        data = self.load()
        yield data
        self.save(data)

    def set_component(self, bid, **fields):
        with self.edit() as d:
            c = d["components"].setdefault(bid, {})
            c.update(fields)


class LockBusy(RuntimeError):
    pass


def _pid_alive(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if h:
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@contextmanager
def root_lock(layout):
    """Exclusive lock so CLI and GUI never mutate the same root concurrently.
    A stale lock (dead pid, e.g. after a crash) is taken over."""
    p = layout.lock_file
    p.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                pid = int(p.read_text().strip() or 0)
            except Exception:
                pid = 0
            if _pid_alive(pid) and pid != os.getpid():
                raise LockBusy(f"root is locked by running process {pid}")
            p.unlink(missing_ok=True)
    else:
        raise LockBusy("could not acquire lock")
    try:
        yield
    finally:
        p.unlink(missing_ok=True)
