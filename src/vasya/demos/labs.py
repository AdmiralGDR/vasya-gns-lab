# SPDX-License-Identifier: GPL-3.0-or-later
"""Demo labs: definitions ship with VASYA; a GNS3 project is created only on user request."""
import json, shutil, subprocess, tempfile, time
from pathlib import Path
from ..gns3.client import GNS3Client
from ..runtime import console
from ..core.util import utc_now

DATA = Path(__file__).resolve().parent.parent / "data" / "demos"


def definitions():
    return [json.load(open(p, encoding="utf-8")) for p in sorted(DATA.glob("*.json"))]


def get(did):
    return next((d for d in definitions() if d["id"] == did), None)


def availability(ctx, d):
    st = ctx.state.load()["components"]
    missing = [b for b in d["required_blocks"] if not st.get(b, {}).get("installed")]
    return {"ready": not missing, "missing_blocks": missing}


def _builtin_template(cl, kind):
    return next((t for t in cl.templates() if t.get("builtin") and t.get("template_type") == kind), None)


def create(ctx, did, api_base):
    d = get(did)
    cl = GNS3Client(api_base, timeout=120)
    name = f"vasya-demo-{did}"
    for p in cl.projects():
        if p["name"] == name:
            cl.delete_project(p["project_id"])
    proj = cl.create_project(name)
    pid = proj["project_id"]
    ids = {}
    for n in d["nodes"]:
        if n.get("builtin"):
            t = _builtin_template(cl, n["builtin"])
        else:
            b = ctx.block(n["block"])
            t = cl.find_template(b["name"], b["runtime"])
        if not t:
            raise RuntimeError(f"template for {n.get('block') or n.get('builtin')} not found")
        node = cl.node_from_template(pid, t["template_id"], n["x"], n["y"])
        cl.update_node(pid, node["node_id"], {"name": n["name"]})
        ids[n["name"]] = node["node_id"]
    links = []
    for a, aad, ap, b, bad, bp in d["links"]:
        links.append(cl.link(pid, ids[a], ap, ids[b], bp, aad, bad)["link_id"])
    with ctx.state.edit() as s:
        s["demos"][did] = {"project_id": pid, "api_base": api_base, "created_at": utc_now(),
                           "nodes": ids, "links": links}
    return {"project_id": pid, "nodes": ids, "links": links, "name": name}


def run_check(ctx, did, boot_wait=6):
    d = get(did)
    info = ctx.state.load()["demos"][did]
    cl = GNS3Client(info["api_base"], timeout=180)
    pid = info["project_id"]
    cl.post(f"/v2/projects/{pid}/nodes/start", timeout=300)
    time.sleep(d.get("boot_wait", boot_wait))
    nodes = {n["name"]: n for n in cl.nodes(pid)}
    transcript = {}
    for n in d["nodes"]:
        if n.get("config_cmds"):
            transcript[n["name"]] = console.run("127.0.0.1", nodes[n["name"]]["console"],
                                                n["config_cmds"], wait=1.5, timeout=20)
        if n.get("ip"):
            nn = nodes[n["name"]]
            cmds = ["ip link set eth0 up", f"ip addr add {n['ip']} dev eth0"]
            if n.get("gw"):
                cmds.append(f"ip route add default via {n['gw']}")
            transcript[n["name"]] = console.run("127.0.0.1", nn["console"], cmds, wait=0.8)
    chk = d["check"]
    cap = None
    if chk["type"] == "capture":
        lid = info["links"][chk.get("link", 0)]
        cl.start_capture(pid, lid, f"vasya-demo-{did}.pcap")
        time.sleep(1)
    src = nodes[chk["from"]]
    out = console.run("127.0.0.1", src["console"], [f"ping -c 3 -W 2 {chk['to']}"], wait=5)
    transcript["ping"] = out
    ok = " 0% packet loss" in out or "3 packets received" in out
    if chk["type"] == "capture":
        time.sleep(1.5)
        lid = info["links"][chk.get("link", 0)]
        link = cl.get(f"/v2/projects/{pid}/links/{lid}")
        cl.stop_capture(pid, lid)
        time.sleep(0.5)
        data = b""
        cpath = link.get("capture_file_path")
        if cpath and Path(cpath).exists():
            data = Path(cpath).read_bytes()          # local (managed / same host) server
        else:
            try:
                data = cl.pcap(pid, lid, timeout=5)  # remote server: stream endpoint
            except Exception:
                pass
        pf = ctx.layout.Reports / f"demo-{did}.pcap"
        pf.write_bytes(data)
        cap = {"pcap": str(pf), "bytes": len(data), "icmp_frames": 0}
        ts = shutil.which("tshark")
        if ts and data:
            r = subprocess.run([ts, "-r", str(pf), "-Y", "icmp"], capture_output=True, text=True)
            cap["icmp_frames"] = len([l for l in r.stdout.splitlines() if l.strip()])
            cap["decoder"] = "tshark"
        elif data:
            cap["icmp_frames"] = _count_icmp(data)
            cap["decoder"] = "builtin-pcap"
        ok = ok and cap["icmp_frames"] > 0
    return {"demo": did, "status": "PASS" if ok else "FAIL", "capture": cap,
            "transcript": {k: v[-800:] for k, v in transcript.items()}}


def remove(ctx, did):
    st = ctx.state.load()
    info = st["demos"].get(did)
    if not info:
        return False
    cl = GNS3Client(info["api_base"])
    try:
        cl.post(f"/v2/projects/{info['project_id']}/nodes/stop", timeout=120)
    except Exception:
        pass
    cl.delete_project(info["project_id"])
    with ctx.state.edit() as s:
        s["demos"].pop(did, None)
    return True


def _count_icmp(data):
    """Minimal pcap parser (Ethernet/IPv4) used when tshark is not installed."""
    import struct
    if len(data) < 24:
        return 0
    endian = "<" if data[:4] in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1") else ">"
    off, n = 24, 0
    while off + 16 <= len(data):
        incl = struct.unpack(endian + "I", data[off + 8:off + 12])[0]
        pkt = data[off + 16:off + 16 + incl]
        if len(pkt) > 23 and pkt[12:14] == b"\x08\x00" and pkt[23] == 1:
            n += 1
        off += 16 + incl
    return n
