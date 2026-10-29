# SPDX-License-Identifier: GPL-3.0-or-later
"""VASYA-DIAGNOSTICS.zip — everything support needs, with secrets redacted.

Never included: project contents (only project names), image binaries,
private keys, passwords/tokens (redacted), Cisco credentials (never stored).
"""
import json, os, platform as _pl, re, time, zipfile
from pathlib import Path
from .core.util import utc_now
from .core import txn as txnmod
from .tools.registry import detect_all

REDACT = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
     "[REDACTED PRIVATE KEY]"),
    (re.compile(r"(?im)^(\s*(password|passwd|secret|token|api[_-]?key|auth[_-]?token)\s*[=:]\s*).+$"),
     r"\1[REDACTED]"),
    (re.compile(r'(?i)("(password|passwd|secret|token|api_key|apikey|authorization)"\s*:\s*)"[^"]*"'),
     r'\1"[REDACTED]"'),
    (re.compile(r"(?i)(authorization:\s*(basic|bearer)\s+)\S+"), r"\1[REDACTED]"),
    (re.compile(r"\b(ghp|gho|github_pat|xox[bpas]|sk|AKIA)[-_A-Za-z0-9]{12,}\b"), "[REDACTED TOKEN]"),
]


def redact(text, home=None):
    for rx, rep in REDACT:
        text = rx.sub(rep, text)
    if home:
        text = text.replace(str(home), "~")
    return text


def build(ctx, out_path=None, extra=None):
    lay = ctx.layout
    out = Path(out_path or (lay.Reports / "VASYA-DIAGNOSTICS.zip"))
    out.parent.mkdir(parents=True, exist_ok=True)
    home = Path.home()
    st = ctx.state.load()
    files = {}
    files["system.json"] = json.dumps({
        "generated_at": utc_now(), "platform": _pl.platform(), "python": _pl.python_version(),
        "machine": _pl.machine(), "product_version": st.get("product_version"),
        "tools": detect_all(ctx.platform, with_versions=True)}, indent=2)
    files["state.json"] = json.dumps(st, indent=2, ensure_ascii=False)
    files["receipts.json"] = json.dumps(txnmod.all_receipts(lay), indent=2, ensure_ascii=False)
    for name in ("operations.log", "operations.jsonl", "gns3server.log"):
        p = lay.Logs / name
        if p.exists():
            data = p.read_bytes()[-5 * 1024 * 1024:]
            files[f"logs/{name}"] = data.decode("utf-8", "replace")
    g = st.get("gns3") or {}
    try:
        from .gns3.client import GNS3Client
        if g.get("api_base"):
            cl = GNS3Client(g["api_base"])
            files["gns3/templates.json"] = json.dumps(
                [{k: t.get(k) for k in ("name", "template_type", "category", "builtin")}
                 for t in cl.templates()], indent=2)
            files["gns3/projects.json"] = json.dumps(
                [{"name": p.get("name"), "status": p.get("status")} for p in cl.projects()], indent=2)
    except Exception as e:
        files["gns3/error.txt"] = str(e)
    conf = Path(g.get("config") or "")
    if g.get("config") and conf.exists():
        files["gns3/gns3_server.conf"] = conf.read_text("utf-8", "replace")
    for p in sorted(lay.Reports.glob("*.md")):
        files[f"reports/{p.name}"] = p.read_text("utf-8", "replace")
    if extra:
        files.update(extra)
    manifest = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in files.items():
            red = redact(text, home)
            z.writestr(name, red)
            manifest.append({"file": name, "bytes": len(red), "redactions": red != text})
        z.writestr("MANIFEST.json", json.dumps({"files": manifest, "policy":
            "secrets/keys redacted; home path -> ~; project contents excluded"}, indent=2))
    return {"path": str(out), "files": manifest}
