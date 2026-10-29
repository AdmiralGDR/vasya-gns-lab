# SPDX-License-Identifier: GPL-3.0-or-later
"""System-package receipts + full-uninstall removal offer, with mocked dpkg/apt."""
from vasya import api
from vasya.installer import system_packages as sp


class FakeApt:
    def __init__(self, installed, rdeps):
        self.installed, self.rdeps, self.calls = set(installed), rdeps, []

    def __call__(self, cmd):
        self.calls.append(cmd)
        if cmd[0] == "dpkg-query":
            p = cmd[-1]
            return (0, "install ok installed") if p in self.installed else (1, "")
        if cmd[0] == "apt-cache":
            p = cmd[-1]
            deps = [d for d in self.rdeps.get(p, []) if d in self.installed]
            return 0, f"{p}\nReverse Depends:\n" + "".join(f"  {d}\n" for d in deps)
        if "apt-get" in cmd:
            i = cmd.index("-y")
            for p in cmd[i + 1:]:
                if p.startswith("-"):
                    continue
                (self.installed.add if "install" in cmd else self.installed.discard)(p)
            return 0, "ok"
        return 127, "unexpected"


def test_install_needs_approval_and_records_state_before(tmp_path):
    ctx = api.open_ctx(tmp_path / "R", tmp_path / "nopayload")
    apt = FakeApt({"traceroute"}, {})
    assert sp.install(ctx, ["wireshark"], run=apt)["status"] == "NEEDS_APPROVAL"
    assert not any("apt-get" in c for c in apt.calls)
    r = sp.install(ctx, ["wireshark", "traceroute", "tigervnc-viewer", "qemu-system-arm"],
                   "tools", run=apt, approved=True)
    assert r["status"] == "OK" and r["already_present"] == ["traceroute"]
    recs = sp.load(ctx)["packages"]
    assert recs["traceroute"]["was_installed_before"] is True
    assert recs["wireshark"]["was_installed_before"] is False and recs["wireshark"]["installed_by_vasya"]


def test_offer_only_vasya_installed_without_foreign_rdepends(tmp_path):
    ctx = api.open_ctx(tmp_path / "R", tmp_path / "nopayload")
    apt = FakeApt({"traceroute", "user-tool"},
                  {"tigervnc-viewer": ["user-tool"],          # user software needs it -> keep
                   "qemu-system-arm": ["wireshark"]})        # only VASYA's own package -> ok
    sp.install(ctx, ["wireshark", "traceroute", "tigervnc-viewer", "qemu-system-arm"],
               run=apt, approved=True)
    o = sp.offer(ctx, run=apt)
    assert sorted(x["package"] for x in o["removable"]) == ["qemu-system-arm", "wireshark"]
    why = {k["package"]: k["why"] for k in o["kept"]}
    assert "before" in why["traceroute"] and "user-tool" in why["tigervnc-viewer"]
    r = sp.remove(ctx, ["wireshark", "traceroute", "tigervnc-viewer"], run=apt)
    assert r["removed"] == ["wireshark"] and sorted(r["refused"]) == ["tigervnc-viewer", "traceroute"]
    assert "traceroute" in apt.installed and "tigervnc-viewer" in apt.installed


def test_full_uninstall_offers_and_removes_chosen(tmp_path):
    ctx = api.open_ctx(tmp_path / "R", tmp_path / "nopayload")
    ctx.layout.State.mkdir(parents=True, exist_ok=True)
    apt = FakeApt(set(), {})
    sp.install(ctx, ["wireshark", "qemu-system-arm"], run=apt, approved=True)
    rep = api.uninstall(ctx, "full", system_packages=["qemu-system-arm"], pkg_run=apt,
                        report_dir=tmp_path / "rep", force=True)
    s = rep["system_packages"]
    assert {x["package"] for x in s["offer"]["removable"]} == {"wireshark", "qemu-system-arm"}
    assert s["result"]["removed"] == ["qemu-system-arm"]
    assert "wireshark" in apt.installed and "qemu-system-arm" not in apt.installed
    assert not (tmp_path / "R").exists()
