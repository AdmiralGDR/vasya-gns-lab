# SPDX-License-Identifier: GPL-3.0-or-later
"""Minimal GNS3 2.2 REST (v2) client — stdlib only so it runs offline everywhere."""
import base64, json, socket, urllib.error, urllib.request


class GNS3Error(RuntimeError):
    def __init__(self, status, body):
        super().__init__(f"HTTP {status}: {body[:600]}")
        self.status = status
        self.body = body


class GNS3Client:
    def __init__(self, base, user=None, password=None, timeout=15.0):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.auth = None
        if user:
            tok = base64.b64encode(f"{user}:{password or ''}".encode()).decode()
            self.auth = f"Basic {tok}"

    def request(self, method, path, body=None, timeout=None, raw=False):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if self.auth:
            req.add_header("Authorization", self.auth)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                payload = r.read()
                if raw:
                    return payload
                txt = payload.decode("utf-8", "replace")
                if not txt:
                    return {}
                try:
                    return json.loads(txt)
                except json.JSONDecodeError:
                    return {"raw": txt}
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace") if e.fp else str(e.reason)
            raise GNS3Error(e.code, body) from None

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.request("POST", path, body if body is not None else {}, **kw)

    def put(self, path, body=None, **kw):
        return self.request("PUT", path, body or {}, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)

    # --- high level ----------------------------------------------------
    def version(self, timeout=1.0):
        try:
            v = self.get("/v2/version", timeout=timeout)
            return v.get("version") if isinstance(v, dict) else None
        except (GNS3Error, OSError, socket.timeout, ValueError):
            return None

    def templates(self):
        return self.get("/v2/templates") or []

    def find_template(self, name, ttype=None):
        for t in self.templates():
            if t.get("name") == name and (ttype is None or t.get("template_type") == ttype):
                return t
        return None

    def create_template(self, body):
        return self.post("/v2/templates", body)

    def delete_template(self, tid):
        try:
            self.delete(f"/v2/templates/{tid}")
            return True
        except GNS3Error as e:
            if e.status == 404:
                return False
            raise

    def projects(self):
        return self.get("/v2/projects") or []

    def create_project(self, name, path=None):
        body = {"name": name}
        if path:
            body["path"] = str(path)
        return self.post("/v2/projects", body)

    def open_project(self, pid):
        return self.post(f"/v2/projects/{pid}/open")

    def close_project(self, pid):
        return self.post(f"/v2/projects/{pid}/close")

    def delete_project(self, pid):
        path = None
        try:
            path = (self.get(f"/v2/projects/{pid}") or {}).get("path")
        except GNS3Error:
            pass
        try:
            self.delete(f"/v2/projects/{pid}")
            return True
        except GNS3Error as e:
            if e.status == 404:
                return False
            if not (path and "Permission denied" in e.body):
                raise
        # files written by a root container: repair ownership via a VASYA image, retry
        from ..runtime.docker_perms import fix_tree, remove_tree
        fix_tree(path)
        try:
            self.delete(f"/v2/projects/{pid}")
        except GNS3Error as e:
            if e.status != 404 and not remove_tree(path):
                raise
        return True

    def node_from_template(self, pid, tid, x=0, y=0, name=None):
        body = {"x": x, "y": y, "compute_id": "local"}
        if name:
            body["name"] = name
        return self.post(f"/v2/projects/{pid}/templates/{tid}", body)

    def nodes(self, pid):
        return self.get(f"/v2/projects/{pid}/nodes")

    def node_action(self, pid, nid, action, timeout=120):
        return self.post(f"/v2/projects/{pid}/nodes/{nid}/{action}", timeout=timeout)

    def update_node(self, pid, nid, body):
        return self.put(f"/v2/projects/{pid}/nodes/{nid}", body)

    def link(self, pid, a, ap, b, bp, a_adapter=0, b_adapter=0):
        return self.post(f"/v2/projects/{pid}/links", {"nodes": [
            {"node_id": a, "adapter_number": a_adapter, "port_number": ap},
            {"node_id": b, "adapter_number": b_adapter, "port_number": bp}]})

    def start_capture(self, pid, lid, name="vasya-capture.pcap"):
        return self.post(f"/v2/projects/{pid}/links/{lid}/start_capture",
                         {"capture_file_name": name, "data_link_type": "DLT_EN10MB"})

    def stop_capture(self, pid, lid):
        return self.post(f"/v2/projects/{pid}/links/{lid}/stop_capture")

    def pcap(self, pid, lid, timeout=10):
        return self.request("GET", f"/v2/projects/{pid}/links/{lid}/pcap", raw=True,
                            timeout=timeout)

    def compute_capabilities(self):
        try:
            return self.get("/v2/computes/local")
        except Exception:
            return {}
