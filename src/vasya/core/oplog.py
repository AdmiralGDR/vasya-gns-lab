# SPDX-License-Identifier: GPL-3.0-or-later
"""Operation log: one JSON line per operation, shared by CLI and GUI.

Every entry carries operation_id, transaction id, before/after state,
expected/actual checksum and the rollback action that undoes it.
"""
import json, os, threading
from pathlib import Path
from .util import utc_now

_LOCK = threading.Lock()


class OpLog:
    def __init__(self, logs_dir, txid=None):
        self.dir = Path(logs_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.jsonl = self.dir / "operations.jsonl"
        self.text = self.dir / "operations.log"
        self.txid = txid
        self.listeners = []

    def log(self, action, target, result, *, operation_id=None, before=None, after=None,
            expected_sha256=None, actual_sha256=None, rollback=None, error=None,
            duration_ms=None, **extra):
        entry = {
            "timestamp": utc_now(), "txid": self.txid, "operation_id": operation_id,
            "action": action, "target": str(target) if target is not None else None,
            "before": before, "after": after, "expected_sha256": expected_sha256,
            "actual_sha256": actual_sha256, "result": result, "rollback": rollback,
            "error": error, "duration_ms": duration_ms,
        }
        entry.update(extra)
        line = (f"{entry['timestamp']} {self.txid or '-'} {operation_id or '-'} "
                f"{action} {entry['target']} -> {result}" + (f" ERROR={error}" if error else ""))
        with _LOCK:
            with open(self.jsonl, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            with open(self.text, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        for cb in list(self.listeners):
            try:
                cb(entry, line)
            except Exception:
                pass
        return entry


def read_entries(logs_dir, limit=None, txid=None):
    p = Path(logs_dir) / "operations.jsonl"
    if not p.exists():
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                e = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if txid and e.get("txid") != txid:
                continue
            out.append(e)
    return out[-limit:] if limit else out
