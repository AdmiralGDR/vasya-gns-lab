# SPDX-License-Identifier: GPL-3.0-or-later
"""Write-ahead transaction journal.

Root cause of the 006 rollback residue (~20 image blobs left): 1.0.1 only
wrote the receipt *after* apply_plan() finished, so a crash mid-install left
copied images that no receipt referenced. Here every mutation is recorded as
an INTENT (fsync'd) *before* it happens and COMMITTED after it is verified.
Rollback / resume read the WAL, so a killed process can always be undone.
"""
import json, os
from pathlib import Path
from .util import utc_now, new_id, load_json, write_json

INCOMPLETE = "INCOMPLETE"


class Transaction:
    def __init__(self, layout, kind="install", txid=None, meta=None):
        self.layout = layout
        self.txid = txid or new_id(f"tx-{kind}-")
        self.kind = kind
        self.path = layout.txn_dir / f"{self.txid}.wal.jsonl"
        self.seq = 0
        if txid is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._append({"type": "BEGIN", "kind": kind, "meta": meta or {}})

    # -- low level -------------------------------------------------------
    def _append(self, rec):
        self.seq += 1
        rec = dict(rec, seq=self.seq, at=utc_now(), txid=self.txid)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return rec

    def intent(self, op_id, resource):
        """Record that we are ABOUT to create `resource` (dict with kind ...)."""
        return self._append({"type": "INTENT", "op_id": op_id, "resource": resource})

    def commit(self, op_id, resource=None):
        return self._append({"type": "COMMIT", "op_id": op_id, "resource": resource})

    def abort_op(self, op_id, error):
        return self._append({"type": "ABORT_OP", "op_id": op_id, "error": str(error)[:500]})

    def end(self, status, summary=None):
        rec = self._append({"type": "END", "status": status, "summary": summary or {}})
        write_json(self.layout.receipts_dir / f"{self.txid}.json", receipt_from_wal(self.path))
        return rec

    def mark_rolled_back(self, by_txid):
        return self._append({"type": "ROLLED_BACK", "by": by_txid})

    def mark_released(self, op_id, by_txid):
        """Resource handed over/removed by a later transaction (repair/uninstall)."""
        return self._append({"type": "RELEASED", "op_id": op_id, "by": by_txid})


def read_wal(path):
    recs = []
    p = Path(path)
    if not p.exists():
        return recs
    with open(p, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                recs.append(json.loads(ln))
            except json.JSONDecodeError:
                # torn last line after a crash — ignore it (fsync per record)
                continue
    return recs


def receipt_from_wal(path):
    recs = read_wal(path)
    begin = next((r for r in recs if r["type"] == "BEGIN"), {})
    end = next((r for r in recs if r["type"] == "END"), None)
    rolled = any(r["type"] == "ROLLED_BACK" for r in recs)
    intents, committed, aborted, released = {}, {}, set(), set()
    for r in recs:
        t = r["type"]
        if t == "INTENT":
            intents[r["op_id"]] = r["resource"]
        elif t == "COMMIT":
            committed[r["op_id"]] = r.get("resource") or intents.get(r["op_id"])
        elif t == "ABORT_OP":
            aborted.add(r["op_id"])
        elif t == "RELEASED":
            released.add(r["op_id"])
    pending = {k: v for k, v in intents.items() if k not in committed and k not in aborted}
    return {
        "txid": begin.get("txid") or Path(path).name.split(".wal")[0],
        "kind": begin.get("kind"),
        "meta": begin.get("meta"),
        "started_at": begin.get("at"),
        "ended_at": end.get("at") if end else None,
        "status": end.get("status") if end else INCOMPLETE,
        "summary": end.get("summary") if end else {},
        "rolled_back": rolled,
        "committed": [dict(v, op_id=k) for k, v in committed.items() if k not in released],
        "pending": [dict(v, op_id=k) for k, v in pending.items() if k not in released],
        "aborted": sorted(aborted),
        "released": sorted(released),
    }


def all_receipts(layout):
    out = []
    d = layout.txn_dir
    if not d.exists():
        return out
    for p in sorted(d.glob("*.wal.jsonl")):
        out.append(receipt_from_wal(p))
    return out


def open_tx(layout, txid):
    t = Transaction(layout, txid=txid)
    t.seq = len(read_wal(t.path))
    return t


def incomplete(layout):
    return [r for r in all_receipts(layout) if r["status"] == INCOMPLETE and not r["rolled_back"]]


def owned_resources(layout):
    """Inventory of everything VASYA created and still owns (committed+pending)."""
    res = []
    for r in all_receipts(layout):
        if r["rolled_back"]:
            continue
        for x in r["committed"]:
            res.append(dict(x, txid=r["txid"], state="COMMITTED"))
        for x in r["pending"]:
            res.append(dict(x, txid=r["txid"], state="PENDING"))
    return res
