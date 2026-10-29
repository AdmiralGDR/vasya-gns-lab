# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression test for gns3server-2.2.61-vasya-docker-socket.patch.
Run against a PATCHED gns3server on sys.path: python -m unittest regress_vasya_docker_socket
(tests/test_gns3server_docker_patch.py runs each test in a subprocess against a scratch patched copy)."""
import os, unittest
from unittest import mock

class TestVasyaDockerSocket(unittest.TestCase):
    def _url(self, env):
        with mock.patch.dict(os.environ, env, clear=False):
            for k in ("VASYA_DOCKER_SOCKET",):
                if k not in env: os.environ.pop(k, None)
            from gns3server.compute.docker import Docker
            return Docker()._server_url
    def test_default_unset(self):
        self.assertEqual(self._url({}), "/var/run/docker.sock")
    def test_empty_falls_back(self):
        self.assertEqual(self._url({"VASYA_DOCKER_SOCKET": ""}), "/var/run/docker.sock")
    def test_override(self):
        self.assertEqual(self._url({"VASYA_DOCKER_SOCKET": "/tmp/x/podman.sock"}), "/tmp/x/podman.sock")
    def test_patch_marker_present(self):
        import gns3server.compute.docker as d, inspect
        self.assertIn('os.environ.get("VASYA_DOCKER_SOCKET")', inspect.getsource(d.Docker.__init__))

    def test_fix_uid_default_is_host_uid(self):
        import gns3server.compute.docker.docker_vm as dv, inspect
        src = inspect.getsource(dv.DockerVM._fix_permissions)
        self.assertIn('os.environ.get("VASYA_DOCKER_FIX_UID") or os.getuid()', src)
        os.environ.pop("VASYA_DOCKER_FIX_UID", None)
        self.assertEqual(os.environ.get("VASYA_DOCKER_FIX_UID") or os.getuid(), os.getuid())

    def test_attach_ws_404_falls_back_to_hijack(self):
        import asyncio, tempfile, aiohttp
        from gns3server.compute.docker import Docker
        async def handler(reader, writer):
            head = await reader.readuntil(b"\r\n\r\n")
            if head.startswith(b"GET"):
                writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n"); await writer.drain(); writer.close(); return
            assert b"/v1.24/containers/abc/attach?stream=1" in head, head
            writer.write(b"HTTP/1.1 101 UPGRADED\r\nConnection: Upgrade\r\nUpgrade: tcp\r\n\r\n"); await writer.drain()
            data = await reader.read(100); writer.write(b"echo:" + data); await writer.drain(); writer.close()
        async def run(sock):
            srv = await asyncio.start_unix_server(handler, sock)
            d = Docker(); d._server_url = sock; d._api_version = "1.24"
            d._session = aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=sock))
            try:
                ws = await d.websocket_query("containers/abc/attach/ws?stream=1&stdin=1&stdout=1&stderr=1")
                await ws.send_bytes(b"hi")
                m = await ws.receive(); self.assertEqual(m.type, aiohttp.WSMsgType.BINARY); self.assertEqual(m.data, b"echo:hi")
                m = await ws.receive(); self.assertEqual(m.type, aiohttp.WSMsgType.CLOSE)
                await ws.close()
            finally:
                await d._session.close(); srv.close()
        with tempfile.TemporaryDirectory() as t:
            asyncio.run(run(os.path.join(t, "s.sock")))

if __name__ == "__main__":
    unittest.main(verbosity=2)
