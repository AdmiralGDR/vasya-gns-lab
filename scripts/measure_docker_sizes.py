#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Measure compressed download size of each Docker image in the pack (linux/amd64)
from the registry manifest (no pull). Writes src/vasya/data/docker_sizes.json."""
import json, subprocess, sys, time
from pathlib import Path
pack = json.load(open(sys.argv[1]))
out = {}
for ref in sorted({b["docker_image"] for b in pack["blocks"] if b.get("docker_image")}):
    r = subprocess.run(["docker", "manifest", "inspect", "-v", ref], capture_output=True, text=True, timeout=120)
    if r.returncode:
        out[ref] = {"bytes": None, "error": r.stderr.strip()[-200:]}
        continue
    d = json.loads(r.stdout)
    items = d if isinstance(d, list) else [d]
    pick = next((i for i in items if (i.get("Descriptor", {}).get("platform") or {}).get("architecture") in ("amd64", None)
                 and (i.get("Descriptor", {}).get("platform") or {}).get("os", "linux") == "linux"), items[0])
    m = pick.get("SchemaV2Manifest") or pick.get("OCIManifest") or {}
    size = sum(l.get("size", 0) for l in m.get("layers", [])) + (m.get("config") or {}).get("size", 0)
    out[ref] = {"bytes": size or None}
    print(ref, size, flush=True)
dst = Path(__file__).resolve().parent.parent / "src/vasya/data/docker_sizes.json"
json.dump({"measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "method": "docker manifest inspect -v (compressed layers, linux/amd64)",
           "images": out}, open(dst, "w"), indent=1)
print("total", sum(v["bytes"] or 0 for v in out.values()))
