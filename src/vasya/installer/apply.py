# SPDX-License-Identifier: GPL-3.0-or-later
"""Execute a plan inside a WAL transaction (intent -> act -> verify -> commit)."""
import os, shutil, subprocess, time
from pathlib import Path
from ..core.cas import place_file, partial_path
from ..core.util import sha256_file
from ..gns3.client import GNS3Client, GNS3Error
from ..gns3.templates import build_template, VASYA_USAGE_TAG
from ..runtime import managed_server as ms
from ..desktop import integration as desk


OWNER_LABEL = "org.vasya.owner"
OWNER_VALUE = "vasya-gns-lab"


def root_tag(root):
    import hashlib
    return hashlib.sha256(str(root).encode()).hexdigest()[:10]


def labelled_ref(ref, root=""):
    name, _, tag = ref.rpartition(":") if ":" in ref.split("/")[-1] else (ref, "", "latest")
    safe = "".join(c if c.isalnum() or c in "._-" else "-" for c in name.lower()).strip("-.")
    rid = f"r{root_tag(root)}/" if root else ""
    return f"vasya-gns-lab/{rid}{safe}:{tag or 'latest'}"


class Cancelled(Exception):
    pass


def _crash_hook(op):
    """Test-only fault injection: kill the process for real at a chosen point."""
    want = os.environ.get("VASYA_TEST_CRASH_OP")
    if not want or want != op["op_id"]:
        return None
    mode = os.environ.get("VASYA_TEST_CRASH_MODE", "mid_copy")

    def hook(src, dst):
        if mode == "mid_copy":
            size = os.path.getsize(src)
            with open(src, "rb") as fi, open(dst, "wb") as fo:
                fo.write(fi.read(max(1, size // 2)))
                fo.flush(); os.fsync(fo.fileno())
            os._exit(137)
        shutil.copyfile(src, dst)
    return hook if mode == "mid_copy" else None


def docker_cmd():
    d = shutil.which("docker")
    if not d:
        return None
    if not (Path.home() / ".docker").exists() and os.environ.get("VASYA_ROOT_DOCKER_CONFIG"):
        # don't create ~/.docker just for VASYA; keep the CLI config inside the root
        return [d, "--config", os.environ["VASYA_ROOT_DOCKER_CONFIG"]]
    if os.name != "nt" and os.geteuid() != 0:
        r = subprocess.run([d, "info"], capture_output=True, text=True, timeout=20)
        if r.returncode != 0 and os.environ.get("VASYA_DOCKER_SUDO") == "1":
            return ["sudo", "-n", d]
    return [d]


class Applier:
    def __init__(self, ctx, plan, txn, oplog, pull_docker=True, cancel=None, progress=None):
        self.ctx, self.plan, self.txn, self.log = ctx, plan, txn, oplog
        self.pull_docker = pull_docker
        self.cancel = cancel
        self.progress = progress or (lambda *a: None)
        t = plan["target"]
        self.client = GNS3Client(t["api_base"]) if t.get("api_base") else None
        self.overrides = {}
        self.results = []

    def run(self):
        ops = self.plan["operations"]
        for i, op in enumerate(ops, 1):
            if self.cancel is not None and self.cancel.is_set():
                raise Cancelled()
            t0 = time.time()
            if getattr(self.progress, "wants_start", False):
                self.progress(i, len(ops), op, "RUNNING")
            res, err, after = "OK", None, None
            try:
                res, after = getattr(self, "op_" + op["action"].lower())(op)
            except Cancelled:
                raise
            except Exception as e:
                res, err = "FAIL", str(e)[:800]
                self.txn.abort_op(op["op_id"], err)
            self.log.log(op["action"], op.get("target"), res, operation_id=op["op_id"],
                         block_id=op.get("block_id"), after=after, error=err,
                         expected_sha256=op.get("sha256"),
                         duration_ms=int((time.time() - t0) * 1000))
            if res == "BLOCKED" and isinstance(after, dict):
                err = after.get("reason")
            self.results.append({"op_id": op["op_id"], "action": op["action"],
                                 "block_id": op.get("block_id"), "label": op.get("label"),
                                 "result": res, "error": err})
            op["last_error"] = err
            if isinstance(after, dict) and after.get("port"):
                op["port"] = after["port"]
            self.progress(i, len(ops), op, res)
            if self.cancel is not None and self.cancel.is_set():
                raise Cancelled()
        return self.results

    # ---------------------------------------------------------------- ops
    def op_managed_gns3(self, op):
        lay = self.ctx.layout
        cfg = ms.paths(lay)["config"]
        new = not cfg.exists()
        if new:
            self.txn.intent(op["op_id"], {"kind": "managed_gns3", "config": str(cfg),
                                          "dir": str(lay.managed_gns3), "port": op["port"]})
            from ..tools.registry import detect_all, kvm_functional
            det = detect_all(self.ctx.platform)
            kvm = bool(det.get("kvm", {}).get("accessible")) and \
                kvm_functional(det.get("qemu", {}).get("path"))
            if det.get("kvm", {}).get("accessible") and not kvm:
                self.log.log("KVM_UNUSABLE", "/dev/kvm", "WARN", operation_id=op["op_id"],
                             after={"enable_kvm": False, "why": "test VM with -accel kvm hung; "
                                    "QEMU nodes run without acceleration (slow)"})
            vp = None
            if self.ctx.platform.name == "linux":
                from ..runtime.gui_deps import ensure_vpcs
                v = ensure_vpcs(self.ctx)
                vp = v.get("path") if v["status"] == "OK" else None
                self.log.log("VPCS_" + v.get("source", "fetched").upper().replace("-", "_"), vp or "-",
                             v["status"], operation_id=op["op_id"], after={k: v.get(k) for k in ("reason", "reused")})
            ms.write_config(lay, op["port"], ubridge=det.get("ubridge", {}).get("path"),
                            dynamips=det.get("dynamips", {}).get("path"), enable_kvm=kvm, vpcs=vp)
            from ..runtime import gui_profile
            gp = gui_profile.write_profile(lay, vpcs=vp)
            self.log.log("GNS3_GUI_PROFILE", gp["path"], "OK", operation_id=op["op_id"], after={"set": gp["set"]})
        if not op.get("server_bin"):
            raise RuntimeError("gns3server binary not found — install GNS3 server 2.2.61")
        port, moved = ms.relocate_if_busy(lay, op["port"])
        if moved:
            self.log.log("PORT_CONFLICT_RELOCATED", str(cfg), "OK", operation_id=op["op_id"],
                         before={"port": moved}, after={"port": port})
            op["port"] = port
        from ..runtime import docker_backend as dbk
        def _ensure(ctx):
            sv = dbk.ensure_service(ctx)
            self.log.log("PODMAN_SERVICE", sv["sock"], sv["status"], operation_id=op["op_id"])
        senv = dbk.prepare_server_env(   # {} unless podman active + socket up; restores missing images first
            self.ctx, ensure=_ensure,
            log=lambda r: self.log.log("DOCKER_IMAGE_" + r["status"], r.get("ref"), "OK" if r["status"] in
                                       ("PRESENT", "RESTORED") else "FAIL", operation_id=op["op_id"], after=r))
        ms.start(lay, op["server_bin"], op["port"], extra_env=senv)
        if new:
            self.txn.commit(op["op_id"])
        with self.ctx.state.edit() as st:
            st["gns3"] = {"managed": True, "port": op["port"], "api_base": f"http://127.0.0.1:{op['port']}",
                          "config": str(cfg), "server_bin": op["server_bin"],
                          "images_path": str(ms.paths(lay)["images_path"]),
                          "appliances_path": str(ms.paths(lay)["appliances_path"])}
        self.client = GNS3Client(f"http://127.0.0.1:{op['port']}")
        return ("NEW" if new else "REUSE"), {"port": op["port"], "port_moved_from": moved}

    def _place(self, op, role):
        dst = Path(op["target"])
        if dst.exists():
            if op.get("sha256") and sha256_file(dst) != op["sha256"]:
                from ..catalog.fixups import equivalent_empty_disk
                if equivalent_empty_disk(dst, op["source"]):
                    return "REUSE", {"path": str(dst), "note": "GNS3 built-in blank disk (same size); not owned"}
                raise RuntimeError("target appeared with different content; not overwritten")
            return "REUSE", {"path": str(dst)}
        res = {"kind": "file", "path": str(dst), "sha256": op.get("sha256"), "role": role,
               "partial": str(partial_path(dst)), "block_id": op.get("block_id")}
        self.txn.intent(op["op_id"], res)
        methods = op.get("methods") or ("copy",)
        hook = _crash_hook(op)
        if hook:
            methods = ("copy",)
        try:
            method, actual = place_file(op["source"], dst, expected_sha=op.get("sha256"),
                                        methods=methods, copy_hook=hook,
                                        verify_link=(op.get("size") or 0) <= 256 * 1024 ** 2)
        except RuntimeError as e:
            if "mismatch" in str(e):
                raise RuntimeError(f"PAYLOAD_DAMAGED: store object {Path(op['source']).name[:16]}… "
                                   f"fails its checksum (hardlinked copy was modified in place?) — "
                                   f"re-extract the release or run update from a good payload") from None
            raise
        res["method"] = method
        if not op.get("sha256"):
            res["sha256"] = sha256_file(dst)
        st = os.lstat(dst)   # identity of what we placed: rollback re-checks it before deleting
        res.update(size=st.st_size, ino=st.st_ino, dev=st.st_dev)
        self.txn.commit(op["op_id"], res)
        return "NEW", {"path": str(dst), "method": method, "sha256": actual or res["sha256"]}

    def op_place_image(self, op):
        return self._place(op, "image")

    def op_place_image_alt(self, op):
        r = self._place(op, "image")
        self.overrides[op["logical"]] = Path(op["target"]).name
        return r

    def op_upload_image(self, op):
        from ..gns3 import remote_compute as rc
        if not self.client:
            raise RuntimeError("GNS3 API not available for upload to compute " + op["compute_id"])
        res = {"kind": "remote_image", "api_base": self.client.base, "compute_id": op["compute_id"],
               "emulator": op["emulator"], "filename": op["filename"], "sha256": op.get("sha256"),
               "block_id": op.get("block_id")}
        self.txn.intent(op["op_id"], res)
        if sha256_file(op["source"]) != op["sha256"]:
            raise RuntimeError(f"PAYLOAD_DAMAGED: {Path(op['source']).name[:16]}… fails its checksum")
        md5 = rc.upload(self.client, op["compute_id"], op["emulator"], op["filename"], op["source"])
        rc.verify_uploaded(self.client, op["compute_id"], op["emulator"], op["filename"], md5)
        res["md5"] = md5
        self.txn.commit(op["op_id"], res)
        if op.get("logical") and op["logical"] != op["filename"]:
            self.overrides[op["logical"]] = op["filename"]
        return "NEW", {"compute": op["compute_id"], "filename": op["filename"], "md5": md5}

    def op_reuse_remote_image(self, op):
        return "REUSE", {"compute": op["compute_id"], "filename": op["filename"]}

    def op_reuse_image(self, op):
        if op.get("verify_at_apply") and sha256_file(op["target"]) != op["sha256"]:
            raise RuntimeError("existing file differs (same size) — refusing to use it")
        return "REUSE", None

    def op_place_appliance(self, op):
        return self._place(op, "appliance")

    def op_reuse_template(self, op):
        return "REUSE", {"template_id": op.get("template_id")}

    def op_register_template(self, op):
        if not self.client:
            return "SKIP", {"reason": "GNS3 API not available"}
        b = self.ctx.block(op["block_id"])
        body = build_template(b, self.ctx.appliance_json(b), self.overrides or None,
                              self.plan["target"].get("compute_id") or "local")
        if body is None:
            return "SKIP", {"reason": "unsupported runtime"}
        found = self.client.find_template(body["name"], body["template_type"])
        if found:
            return "REUSE", {"template_id": found.get("template_id")}
        res = {"kind": "template", "api_base": self.client.base, "name": body["name"],
               "template_type": body["template_type"], "tag": VASYA_USAGE_TAG,
               "block_id": op["block_id"]}
        self.txn.intent(op["op_id"], res)
        t = self.client.create_template(body)
        res["template_id"] = t.get("template_id")
        self.txn.commit(op["op_id"], res)
        return "NEW", {"template_id": res["template_id"]}

    def op_ensure_docker_image(self, op):
        """Ensure base image (pull = receipted), then build a thin labelled image
        (FROM base + LABEL org.vasya.owner) that the template uses, so every
        container GNS3 creates for VASYA inherits the owner label."""
        from ..runtime import docker_backend as dbk
        why = dbk.unavailable_reason(self.ctx)   # podman prerequisites missing / Windows GNS3 VM path
        if why:
            return "BLOCKED", {"reason": why}
        pcmd, penv = dbk.engine_cmd(self.ctx)   # rootless podman (Linux default) or explicit shared daemon
        cmd = pcmd or docker_cmd()
        run = (lambda a, **k: subprocess.run(a, env=penv, **k)) if penv else subprocess.run
        if not cmd:
            return "SKIP", {"reason": "docker not installed"}
        ref = op["target"]
        pulled = False
        from ..runtime import docker_images as di
        pin = di.pin_for_ref(ref) or {}
        # podman storage is VASYA's own: the tag must be the pinned image (else re-restore from the archive).
        # Shared daemon: a user's pre-existing image under that tag is reused, never replaced.
        have = (di.present(run, cmd, ref, pin.get("image_id")) if pcmd
                else run(cmd + ["image", "inspect", ref], capture_output=True).returncode == 0)
        if not have:
            arc = di.find(self.ctx, ref)
            if pcmd and not arc:
                # no offline archive: pull the pinned digest from the official registry (VASYA's own
                # podman storage), image ID checked against the pin; any failure only skips this device
                pr = (di.pull_pinned(self.ctx, ref, cmd, env=penv) if self.pull_docker and di.pull_allowed()
                      else {"status": "OFFLINE"})
                if pr["status"] not in ("PULLED", "PRESENT"):
                    return "SKIP", {"reason": di.pack_missing_reason(self.ctx, ref), "code": "IMAGE_PACK_MISSING",
                                    "pull": pr}
                res = {"kind": "docker_image", "ref": ref, "block_id": op.get("block_id"),
                       "preexisting": False, "source": "registry", "pinned": pr.get("pinned"),
                       "image_id": pin.get("image_id"), "engine": dbk.engine_name(self.ctx),
                       "root": str(self.ctx.layout.root)}
                self.txn.intent(op["op_id"], res)
                self.txn.commit(op["op_id"], res)
                pulled, have = True, True
        if not have:
            if not self.pull_docker and not arc:
                return "SKIP", {"reason": "docker pull disabled"}
            res = {"kind": "docker_image", "ref": ref, "block_id": op.get("block_id"),
                   "preexisting": False, "source": "offline-archive" if arc else "registry",
                   "engine": dbk.engine_name(self.ctx), "root": str(self.ctx.layout.root)}
            if arc:
                res.update(archive=arc["archive"], archive_sha256=arc["archive_sha256"],
                           image_id=arc.get("image_id"))
            self.txn.intent(op["op_id"], res)
            if arc:
                rr = di.restore(self.ctx, ref, cmd, env=penv, run=run)   # sha256+manifest+ID+tag verified
                if rr["status"] not in ("RESTORED", "PRESENT"):
                    raise RuntimeError(f"offline image {ref}: {rr['status']} {rr.get('error') or ''}")
            else:
                src = ref
                if pin.get("repo_digest"):      # pinned: pull the exact tested manifest, then tag it
                    src = di.repo_of(ref) + "@" + pin["repo_digest"]
                    res["pinned"] = src
                r = run(cmd + ["pull", src], capture_output=True, text=True, timeout=3600)
                if r.returncode == 0 and src != ref:
                    r = run(cmd + ["tag", src, ref], capture_output=True, text=True, timeout=120)
                if r.returncode != 0:
                    raise RuntimeError((r.stderr or r.stdout)[-400:])
            self.txn.commit(op["op_id"], res)
            pulled = True
        lref = labelled_ref(ref, self.ctx.layout.root)
        lop = op["op_id"] + "L"
        if run(cmd + ["image", "inspect", lref], capture_output=True).returncode != 0:
            res = {"kind": "docker_labeled_image", "ref": lref, "base": ref,
                   "block_id": op.get("block_id"), "engine": dbk.engine_name(self.ctx),
                   "root": str(self.ctx.layout.root)}
            self.txn.intent(lop, res)
            df = dbk.labelled_dockerfile(ref, op.get("block_id"), self.ctx.layout.root)
            if pcmd:
                r = dbk.build_labelled(self.ctx, cmd, penv, ref, lref, op.get("block_id"), tag=lop)
            else:
                r = run(cmd + ["build", "-q", "-t", lref, "-"], input=df,
                        capture_output=True, text=True, timeout=600)
            if r.returncode != 0:
                raise RuntimeError("labelled image build failed: " + (r.stderr or r.stdout)[-300:])
            self.txn.commit(lop, res)
        self.overrides["__docker__:" + op["block_id"]] = lref
        return ("NEW" if pulled else "REUSE"), {"ref": ref, "labelled": lref}

    def op_blocked_dependency(self, op):
        return "BLOCKED", {"reason": f"needs {op['package']} (not installed) — install it with: {op['command']}, "
                                     f"then run Install again; nothing was changed for this component"}

    def op_image_not_available(self, op):
        return "BLOCKED", {"reason": "image not available: " + ", ".join(op.get("images") or []) +
                           " (not in the public download list and not found in your private image "
                           "sources); nothing was changed for this component", "code": "IMAGE_NOT_AVAILABLE"}

    def op_blocked_image(self, op):
        raise RuntimeError("image cannot be linked and copying was not allowed "
                           "(re-run with allow_copy / --allow-copy)")

    def op_install_app(self, op):
        """Copy the application (code + bundled PySide6) into <root>/App. Hardlinks when
        possible so the extracted bundle and the root share the bytes."""
        from .. import VERSION
        src, dst = Path(op["source"]), Path(op["target"])
        marker = dst / "VERSION"
        if marker.exists() and marker.read_text().strip() == VERSION:
            return "REUSE", {"version": VERSION}

        def link_or_copy(a, b):
            try:
                os.link(a, b)
            except OSError:
                shutil.copy2(a, b)
        tmp = dst.with_name(dst.name + ".vasya-partial")
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(src, tmp, copy_function=link_or_copy, symlinks=True)
        (tmp / "VERSION").write_text(VERSION)
        if dst.exists():
            old = dst.with_name(dst.name + ".old")
            shutil.rmtree(old, ignore_errors=True)
            os.replace(dst, old)
            os.replace(tmp, dst)
            shutil.rmtree(old, ignore_errors=True)
        else:
            os.replace(tmp, dst)
        return "NEW", {"version": VERSION}

    def op_desktop_files_in_root(self, op):
        desk.prepare_files(self.ctx.layout)
        return "OK", {"dir": op["target"]}

    def op_desktop_entry(self, op):
        dst = Path(op["target"])
        if dst.exists():
            return "REUSE", None
        res = {"kind": "desktop_file", "path": str(dst)}
        self.txn.intent(op["op_id"], res)
        p = desk.register(self.ctx.layout, self.ctx.platform)
        res["path"] = str(p)
        self.txn.commit(op["op_id"], res)
        with self.ctx.state.edit() as st:
            st["desktop"] = {"registered": str(p), "entry": str(self.ctx.layout.Desktop / desk.DESKTOP_NAME)}
        return "NEW", {"path": str(p)}
