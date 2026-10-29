# SPDX-License-Identifier: GPL-3.0-or-later
"""Pinned third-party sources (data/third_party.lock, JSON)."""
import json
from pathlib import Path

LOCK = Path(__file__).resolve().parent.parent / "data" / "third_party.lock"


def load(path=None):
    p = Path(path) if path else LOCK
    if not p.is_file():
        return {"format": 1, "tools": {}, "libraries": {}, "images": {}, "docker": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def image(sha256, lock=None):
    return (lock or load()).get("images", {}).get(sha256)


def tool(name, lock=None):
    return (lock or load()).get("tools", {}).get(name)


def library(name, lock=None):
    return (lock or load()).get("libraries", {}).get(name)
