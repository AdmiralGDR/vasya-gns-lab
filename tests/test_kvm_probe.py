# SPDX-License-Identifier: GPL-3.0-or-later
"""KVM functional probe: /dev/kvm writable is not enough (a nested KVM host was found to hang)."""
import os, stat
from vasya.tools import registry


def _fake(tmp_path, body):
    p = tmp_path / "qemu-fake"
    p.write_text("#!/bin/sh\n" + body + "\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def test_hanging_kvm_is_unusable(tmp_path):
    registry._KVM_CACHE.clear()
    assert registry.kvm_functional(_fake(tmp_path, "sleep 30"), timeout=1) is False


def test_clean_quit_is_usable(tmp_path):
    registry._KVM_CACHE.clear()
    assert registry.kvm_functional(_fake(tmp_path, "cat >/dev/null; exit 0"), timeout=5) is True


def test_missing_qemu(tmp_path):
    assert registry.kvm_functional(None) is False
    registry._KVM_CACHE.clear()
    assert registry.kvm_functional(str(tmp_path / "nope")) is False
