from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import zipfile


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "update_client.py"
SPEC = importlib.util.spec_from_file_location("pro_update_client_under_test", SCRIPT)
assert SPEC and SPEC.loader
update_client = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(update_client)


TOKEN = "T" * 64
RELEASE_ID = "rel_" + "a" * 12


def _package_bytes():
    file_path = "chat-archify-pro/README.txt"
    file_bytes = b"offline Pro release\n"
    manifest = {
        "name": "chat-archify-pro",
        "version": "0.4.0",
        "files": {"README.txt": hashlib.sha256(file_bytes).hexdigest()},
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(file_path, file_bytes)
        archive.writestr(
            "chat-archify-pro/package-manifest.json",
            json.dumps(manifest, separators=(",", ":")).encode("utf-8"),
        )
    return output.getvalue()


ZIP_BYTES = _package_bytes()


class FakeUpdateHandler(BaseHTTPRequestHandler):
    mode = "ok"

    def log_message(self, format, *args):
        return

    def _json(self, status, body):
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/api/v1/updates/check":
            if self.mode == "redirect":
                self.send_response(302)
                self.send_header("Location", "https://attacker.example/download")
                self.end_headers()
                return
            expected = "Bearer " + TOKEN
            if self.headers.get("Authorization") != expected:
                self._json(401, {"error": "invalid_license"})
                return
            self._json(
                200,
                {
                    "schema": 1,
                    "product": "pro",
                    "authorized": True,
                    "license": {"status": "active", "expires_at": None},
                    "release": {
                        "id": RELEASE_ID,
                        "version": "0.4.0",
                        "notes": "update",
                        "sha256": hashlib.sha256(ZIP_BYTES).hexdigest(),
                        "bytes": len(ZIP_BYTES),
                    },
                },
            )
            return
        if self.path == "/api/v1/updates/releases/" + RELEASE_ID + "/download":
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(ZIP_BYTES)))
            self.end_headers()
            self.wfile.write(ZIP_BYTES)
            return
        self._json(404, {"error": "not_found"})


class UpdateClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.license_file = self.root / "license.json"
        self.license_file.write_text(json.dumps({"license": TOKEN}), encoding="utf-8")
        FakeUpdateHandler.mode = "ok"
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeUpdateHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)
        self.temp.cleanup()

    def test_download_verifies_hash_and_keeps_archive_only(self):
        destination = self.root / "update.zip"
        client = update_client.UpdateClient(self.base, self.license_file)
        release = client.download(destination)
        self.assertEqual(release["version"], "0.4.0")
        self.assertEqual(destination.read_bytes(), ZIP_BYTES)
        self.assertFalse((self.root / "update.zip.part").exists())

    def test_integrity_mismatch_removes_partial_file(self):
        original = FakeUpdateHandler.do_GET

        def wrong_download(handler):
            if handler.path == "/api/v1/updates/releases/" + RELEASE_ID + "/download":
                bad = b"tampered"
                handler.send_response(200)
                handler.send_header("Content-Length", str(len(bad)))
                handler.end_headers()
                handler.wfile.write(bad)
                return
            original(handler)

        FakeUpdateHandler.do_GET = wrong_download
        try:
            destination = self.root / "update.zip"
            client = update_client.UpdateClient(self.base, self.license_file)
            with self.assertRaises(update_client.UpdateClientError) as raised:
                client.download(destination)
            self.assertEqual(str(raised.exception), "download_integrity_mismatch")
            self.assertFalse(destination.exists())
            self.assertEqual(list(self.root.glob("*.part")), [])
        finally:
            FakeUpdateHandler.do_GET = original

    def test_external_plain_http_and_userinfo_are_rejected(self):
        with self.assertRaises(update_client.UpdateClientError):
            update_client.validate_service_url("http://updates.example")
        with self.assertRaises(update_client.UpdateClientError):
            update_client.validate_service_url("https://user:secret@updates.example")
        self.assertEqual(
            update_client.validate_service_url("http://localhost:8787/"),
            "http://localhost:8787",
        )

    def test_redirect_is_rejected_before_external_request(self):
        FakeUpdateHandler.mode = "redirect"
        client = update_client.UpdateClient(self.base, self.license_file)
        with self.assertRaises(update_client.UpdateClientError) as raised:
            client.check()
        self.assertEqual(str(raised.exception), "redirect_rejected")


if __name__ == "__main__":
    unittest.main()
