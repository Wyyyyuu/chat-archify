from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import unittest
import zipfile
from pathlib import Path


SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

import cli  # noqa: E402
import core  # noqa: E402
import server  # noqa: E402


CLIENT_CANDIDATES = [
    SERVICE_DIR.parent / "scripts" / "update_client.py",
    SERVICE_DIR.parent / "editions" / "source" / "pro-base" / "scripts" / "update_client.py",
]
CLIENT_SCRIPT = next((path for path in CLIENT_CANDIDATES if path.is_file()), CLIENT_CANDIDATES[0])
CLIENT_SPEC = importlib.util.spec_from_file_location("service_smoke_update_client", CLIENT_SCRIPT)
assert CLIENT_SPEC and CLIENT_SPEC.loader
client_module = importlib.util.module_from_spec(CLIENT_SPEC)
CLIENT_SPEC.loader.exec_module(client_module)


class ServiceSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.db = root / "data" / "service.sqlite3"
        self.releases = root / "releases"
        self.licenses = root / "licenses"
        self.licenses.mkdir(parents=True)
        self.store = core.Store(self.db, self.releases)
        self.config = server.ServerConfig(bind="127.0.0.1", port=0, poll_seconds=60)
        self.httpd = server.make_server(self.store, self.config)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.httpd.server_address[:2]
        self.base = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)
        self.temp.cleanup()

    def _get(self, path: str, token: str | None = None, base: str | None = None, extra_headers=None):
        headers = {"Accept": "application/json"}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        if extra_headers:
            headers.update(extra_headers)
        request = urllib.request.Request((base or self.base) + path, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    def _release_zip(self, version: str = "0.4.0") -> Path:
        source = Path(self.temp.name) / "source.zip"
        file_path = "chat-archify-pro/README.txt"
        file_bytes = b"offline Pro release\n"
        manifest = {
            "name": "chat-archify-pro",
            "version": version,
            "files": {"README.txt": hashlib.sha256(file_bytes).hexdigest()},
        }
        with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(file_path, file_bytes)
            archive.writestr(
                "chat-archify-pro/package-manifest.json",
                json.dumps(manifest, separators=(",", ":")).encode("utf-8"),
            )
        return source

    def test_issue_check_download_hash_and_revoke(self) -> None:
        license_file = self.licenses / "operator.license.json"
        record, token = self.store.issue_license(license_file, now=int(time.time()))
        release = self.store.register_release(
            "0.4.0",
            self._release_zip(),
            notes="修复更新检查。",
            published_at=int(time.time()),
        )

        status, _, body = self._get("/api/v1/updates/check")
        self.assertEqual(status, 200)
        public = json.loads(body)
        self.assertFalse(public["authorized"])
        self.assertEqual(public["release"]["version"], "0.4.0")
        self.assertEqual(public["release"]["bytes"], release.bytes)
        self.assertEqual(public["release"]["sha256"], release.sha256)
        self.assertNotIn(str(self.releases), body.decode("utf-8"))
        self.assertNotIn(token, body.decode("utf-8"))

        status, _, body = self._get("/api/v1/updates/check", token)
        self.assertEqual(status, 200)
        authorized = json.loads(body)
        self.assertTrue(authorized["authorized"])
        self.assertEqual(authorized["license"]["status"], "active")
        self.assertEqual(authorized["license"]["expires_at"], core.iso_utc(record.expires_at))

        status, headers, body = self._get(
            f"/api/v1/updates/releases/{release.release_id}/download", token
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/zip")
        self.assertEqual(int(headers["Content-Length"]), len(body))
        self.assertEqual(hashlib.sha256(body).hexdigest(), release.sha256)
        self.assertEqual(len(body), release.bytes)

        self.assertTrue(self.store.revoke_license(license_id=record.license_id, now=1_700_000_010))
        self.assertTrue(self.store.revoke_license(license_id=record.license_id, now=1_700_000_020))
        status, _, _ = self._get("/api/v1/updates/check", token)
        self.assertEqual(status, 401)
        status, _, _ = self._get(
            f"/api/v1/updates/releases/{release.release_id}/download", token
        )
        self.assertEqual(status, 401)

    def test_tamper_and_arbitrary_release_path_are_rejected(self) -> None:
        license_file = self.licenses / "operator.license.json"
        _, token = self.store.issue_license(license_file, now=int(time.time()))
        source = self._release_zip("1.0.0")
        release = self.store.register_release("1.0.0", source)
        destination = self.releases / release.relative_path
        destination.write_bytes(b"not-the-registered-zip")
        status, _, body = self._get(
            f"/api/v1/updates/releases/{release.release_id}/download", token
        )
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)["error"], "release_integrity_failure")
        destination.unlink()
        status, _, body = self._get(f"/api/v1/updates/releases/{release.release_id}/download", token)
        self.assertEqual(status, 503, 'missing private release returns a structured error')
        self.assertEqual(json.loads(body)['error'], 'release_integrity_failure')

        unknown = "rel_" + "b" * 12
        status, _, _ = self._get(f"/api/v1/updates/releases/{unknown}/download", token)
        self.assertEqual(status, 404)
        status, _, _ = self._get(
            "/api/v1/updates/releases/%2e%2e/download", token
        )
        self.assertEqual(status, 404)

    def test_real_builder_map_registers_and_client_checks_downloads(self) -> None:
        license_file = self.licenses / "operator.license.json"
        _, token = self.store.issue_license(license_file, now=int(time.time()))
        release = self.store.register_release("0.4.0", self._release_zip("0.4.0"))
        client = client_module.UpdateClient(self.base, license_file)
        checked = client.check()
        self.assertEqual(checked["release"]["version"], "0.4.0")
        self.assertEqual(checked["release"]["sha256"], release.sha256)
        destination = Path(self.temp.name) / "client-update.zip"
        downloaded = client.download(destination)
        self.assertEqual(downloaded["version"], "0.4.0")
        self.assertEqual(hashlib.sha256(destination.read_bytes()).hexdigest(), release.sha256)
        self.assertEqual(destination.stat().st_size, release.bytes)
        self.assertNotIn(token, destination.read_bytes().decode("latin-1", errors="ignore"))

    def test_release_manifest_identity_and_archive_paths_are_required(self) -> None:
        mismatch = Path(self.temp.name) / "mismatch.zip"
        with zipfile.ZipFile(mismatch, "w") as archive:
            payload = b"file"
            archive.writestr("chat-archify-pro/README.txt", payload)
            archive.writestr(
                "chat-archify-pro/package-manifest.json",
                json.dumps(
                    {
                        "name": "wrong-name",
                        "version": "0.4.0",
                        "files": [
                            {
                                "path": "chat-archify-pro/README.txt",
                                "sha256": hashlib.sha256(payload).hexdigest(),
                                "bytes": len(payload),
                            }
                        ],
                    }
                ),
            )
        with self.assertRaisesRegex(core.ReleaseError, "package_identity_mismatch"):
            self.store.register_release("0.4.0", mismatch)

        unsafe = Path(self.temp.name) / "unsafe.zip"
        with zipfile.ZipFile(unsafe, "w") as archive:
            archive.writestr("chat-archify-pro/../outside.txt", b"unsafe")
        with self.assertRaisesRegex(core.ReleaseError, "unsafe_archive_path"):
            self.store.register_release("0.4.1", unsafe)

    def test_same_origin_allowed_and_untrusted_proxy_rejected(self) -> None:
        status, _, _ = self._get("/health", extra_headers={"Origin": self.base})
        self.assertEqual(status, 200)

        config = server.ServerConfig(
            bind="127.0.0.1",
            port=0,
            trust_proxy_tls=True,
            trusted_proxy_ips=("192.0.2.1",),
            public_origin="https://updates.example",
        )
        proxy_server = server.make_server(self.store, config)
        proxy_thread = threading.Thread(target=proxy_server.serve_forever, daemon=True)
        proxy_thread.start()
        proxy_base = f"http://127.0.0.1:{proxy_server.server_address[1]}"
        try:
            status, _, _ = self._get(
                "/health",
                base=proxy_base,
                extra_headers={"Host": "updates.example", "X-Forwarded-Proto": "https"},
            )
            self.assertEqual(status, 403)
        finally:
            proxy_server.shutdown()
            proxy_server.server_close()
            proxy_thread.join(timeout=3)

        trusted = server.ServerConfig(
            bind="127.0.0.1",
            port=0,
            trust_proxy_tls=True,
            trusted_proxy_ips=("127.0.0.1",),
            public_origin="https://updates.example",
        )
        trusted_server = server.make_server(self.store, trusted)
        trusted_thread = threading.Thread(target=trusted_server.serve_forever, daemon=True)
        trusted_thread.start()
        trusted_base = f"http://127.0.0.1:{trusted_server.server_address[1]}"
        try:
            status, _, _ = self._get(
                "/health",
                base=trusted_base,
                extra_headers={
                    "Host": "updates.example",
                    "Origin": "https://updates.example",
                    "X-Forwarded-Proto": "https",
                },
            )
            self.assertEqual(status, 200)
            status, _, _ = self._get(
                "/health",
                base=trusted_base,
                extra_headers={
                    "Host": "updates.example",
                    "Origin": "https://evil.example",
                    "X-Forwarded-Proto": "https",
                },
            )
            self.assertEqual(status, 403)
        finally:
            trusted_server.shutdown()
            trusted_server.server_close()
            trusted_thread.join(timeout=3)

    def test_issue_cli_does_not_print_secret(self) -> None:
        output_file = self.licenses / "cli.license.json"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = cli.main(
                [
                    "--db",
                    str(self.db),
                    "--release-dir",
                    str(self.releases),
                    "issue",
                    "--out",
                    str(output_file),
                ]
            )
        self.assertEqual(result, 0)
        document = json.loads(output_file.read_text(encoding="utf-8"))
        self.assertNotIn(document["token"], stdout.getvalue())
        self.assertIn(document["license_id"], stdout.getvalue())
        self.assertEqual(len(document["token"]), 64)


if __name__ == "__main__":
    unittest.main()
