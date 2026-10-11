#!/usr/bin/env python3
"""Focused credential-filter regressions for the standalone Pro package."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "interactive-demo"
sys.path.insert(0, str(ROOT / "scripts"))
from credential_guard import CREDENTIAL_NOTE, credential_reason
from package_interactive import package


def read_payload(path: Path) -> dict:
    page = path.read_text(encoding="utf-8")
    match = re.search(r'<script type="application/json" id="explorer-data">([\s\S]*?)</script>', page)
    if not match:
        raise AssertionError("packaged HTML has no explorer-data payload")
    return json.loads(match.group(1))


def write_viewer(path: Path) -> None:
    path.write_text(
        """<svg>
<path data-edge-from="combined-plan" data-edge-to="review-later" data-edge-key="0" d="M 534 246 L 590.4 246" />
<path data-edge-from="daily-option" data-edge-to="combined-plan" data-edge-key="1" d="M 260 246 L 374 246" />
<path data-edge-from="question" data-edge-to="daily-option" data-edge-key="2" d="M 140 120 L 214 120 L 214 220" />
<path data-edge-from="question" data-edge-to="weekend-option" data-edge-key="3" d="M 48 120 L 32 120 L 32 426 L 214 426 L 214 398" />
<path data-edge-from="weekend-option" data-edge-to="combined-plan" data-edge-key="4" d="M 260 372 L 454 372 L 454 280" />
<g data-node-id="question"><rect x="48" y="94" width="92" height="52" /></g>
<g data-node-id="daily-option"><rect x="168" y="220" width="92" height="52" /></g>
<g data-node-id="combined-plan"><rect x="374" y="212" width="160" height="68" /></g>
<g data-node-id="review-later"><rect x="590.4" y="220" width="92" height="52" /></g>
<g data-node-id="weekend-option"><rect x="168" y="346" width="92" height="52" /></g>
</svg>""",
        encoding="utf-8",
    )


class CredentialGuardUnitTests(unittest.TestCase):
    def test_common_credential_names_are_excluded(self):
        for name in (".env.production", "config/credentials.json", ".ssh/id_rsa", "backup/private.pem"):
            reason = credential_reason(name)
            self.assertEqual(reason, CREDENTIAL_NOTE)

    def test_pgp_private_key_header_is_excluded(self):
        self.assertEqual(credential_reason('export.asc', b'-----BEGIN PGP PRIVATE KEY BLOCK-----\nsynthetic'), CREDENTIAL_NOTE)

    def test_database_and_docker_auth_values_are_detected(self):
        secret='AbCdE12345-secret-value'
        self.assertEqual(credential_reason('config.txt', ('DATABASE_URL=postgresql://user:'+secret+'@localhost/db').encode()),CREDENTIAL_NOTE)
        auth=base64.b64encode(('user:'+secret).encode()).decode()
        raw=json.dumps({'auths':{'registry.example':{'auth':auth}}}).encode()
        self.assertEqual(credential_reason('config.json',raw),CREDENTIAL_NOTE)
        self.assertIsNone(credential_reason('config.txt',b'DATABASE_URL=postgresql://user:YOUR_PASSWORD@localhost/db'))

    def test_provider_tokens_and_utf16_are_detected_without_leaking_values(self):
        secret = "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"
        samples = (
            f"OPENAI_API_KEY={secret}",
            "AWS_ACCESS_KEY_ID=AKIA1234567890ABCDEF\nAWS_SECRET_ACCESS_KEY=AbCdEf0123456789/AbCdEf0123456789",
            "A GitHub token: ghp_123456789012345678901234567890123456",
        )
        for text in samples:
            reason = credential_reason("config.txt", text.encode("utf-8"))
            self.assertEqual(reason, CREDENTIAL_NOTE)
            self.assertNotIn(text, reason or "")
        utf16_reason = credential_reason("export.txt", samples[0].encode("utf-16"))
        self.assertEqual(utf16_reason, CREDENTIAL_NOTE)
        self.assertNotIn(secret, utf16_reason or "")

    def test_document_placeholders_are_allowed(self):
        text = """# Configuration example
OPENAI_API_KEY=YOUR_API_KEY
GITHUB_TOKEN=${GITHUB_TOKEN}
client = os.getenv("OPENAI_API_KEY")
"""
        self.assertIsNone(credential_reason("setup.md", text.encode("utf-8")))


class ProPackagingCredentialTests(unittest.TestCase):
    def test_packaging_excludes_secrets_and_allows_safe_placeholder_document(self):
        with tempfile.TemporaryDirectory(prefix="chat-archify-pro-credentials-") as directory:
            root = Path(directory)
            source = root / "source"
            shutil.copytree(EXAMPLE, source)
            write_viewer(source / "archify-overview.html")
            record_path = source / "evolution.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            artifacts = [
                {"label": "OpenAI settings", "uri": "config.txt", "role": "referenced", "verification": "exists"},
                {"label": "GitHub notes", "uri": "token-notes.md", "role": "referenced", "verification": "exists"},
                {"label": "Safe setup guide", "uri": "safe-notes.md", "role": "referenced", "verification": "exists"},
            ]
            record["nodes"][0]["artifacts"].extend(artifacts)
            record_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            openai_secret = "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"
            github_secret = "ghp_123456789012345678901234567890123456"
            (source / "config.txt").write_text(
                f"OPENAI_API_KEY={openai_secret}\n"
                "AWS_ACCESS_KEY_ID=AKIA1234567890ABCDEF\n"
                "AWS_SECRET_ACCESS_KEY=AbCdEf0123456789/AbCdEf0123456789\n",
                encoding="utf-8",
            )
            (source / "token-notes.md").write_text(f"# Example token\n{github_secret}\n", encoding="utf-8")
            safe_text = (
                "# Setup\nOPENAI_API_KEY=YOUR_API_KEY\n"
                "GITHUB_TOKEN=${GITHUB_TOKEN}\n"
                "client = os.getenv(\"OPENAI_API_KEY\")\n"
            )
            safe_path = source / "safe-notes.md"
            safe_path.write_text(safe_text, encoding="utf-8")
            safe_bytes = safe_path.read_bytes()
            output = root / "pro.html"
            package(source / "manifest.json", output)
            payload = read_payload(output)
            files = {item["name"]: item for item in payload["files"].values()}
            for name, secret in (("config.txt", openai_secret), ("token-notes.md", github_secret)):
                self.assertEqual(files[name]["status"], "excluded")
                self.assertNotIn("data", files[name])
                self.assertNotIn(secret, output.read_text(encoding="utf-8"))
                self.assertNotIn(base64.b64encode(secret.encode()).decode(), output.read_text(encoding="utf-8"))
            safe = files["safe-notes.md"]
            self.assertEqual(safe["status"], "embedded")
            self.assertEqual(base64.b64decode(safe["data"], validate=True), safe_bytes)

    def test_snapshot_reuse_rechecks_preserved_bytes(self):
        with tempfile.TemporaryDirectory(prefix="chat-archify-pro-snapshot-credentials-") as directory:
            root = Path(directory)
            source = root / "source"
            shutil.copytree(EXAMPLE, source)
            write_viewer(source / "archify-overview.html")
            record_path = source / "evolution.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["nodes"][0]["artifacts"].append(
                {"label": "Safe guide", "uri": "safe-notes.md", "role": "referenced", "verification": "exists"}
            )
            record_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            (source / "safe-notes.md").write_text("OPENAI_API_KEY=YOUR_API_KEY\n", encoding="utf-8")
            original = root / "original.html"
            package(source / "manifest.json", original)
            poisoned = read_payload(original)
            item = next(file for file in poisoned["files"].values() if file["name"] == "safe-notes.md")
            secret = b"OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz0123456789\n"
            item.update(
                data=base64.b64encode(secret).decode("ascii"),
                bytes=len(secret),
                sha256=hashlib.sha256(secret).hexdigest(),
                text=secret.decode("utf-8"),
                status="embedded",
            )
            page = original.read_text(encoding="utf-8")
            serialized = json.dumps(poisoned, ensure_ascii=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
            page = re.sub(
                r'(<script type="application/json" id="explorer-data">)[\s\S]*?(</script>)',
                lambda match: match.group(1) + serialized + match.group(2),
                page,
                count=1,
            )
            poisoned_snapshot = root / "poisoned.html"
            poisoned_snapshot.write_text(page, encoding="utf-8")
            sanitized = root / "sanitized.html"
            package(source / "manifest.json", sanitized, snapshot_from=poisoned_snapshot)
            result = read_payload(sanitized)
            result_item = next(file for file in result["files"].values() if file["name"] == "safe-notes.md")
            self.assertEqual(result_item["status"], "excluded")
            self.assertNotIn("data", result_item)
            self.assertNotIn(secret.decode("utf-8"), sanitized.read_text(encoding="utf-8"))

    def test_snapshot_text_cache_is_rebuilt_from_checked_bytes(self):
        with tempfile.TemporaryDirectory(prefix='chat-archify-text-cache-') as directory:
            root=Path(directory)
            source=root/'source'
            shutil.copytree(EXAMPLE, source)
            write_viewer(source/'archify-overview.html')
            original=root/'original.html'
            package(source/'manifest.json',original)
            data=read_payload(original)
            file=next(item for item in data['files'].values() if item['name']=='reading-plan.md')
            original_text=file['text']
            poisoned='sk-proj-abcdefghijklmnopqrstuvwxyz0123456789'
            file['text']=poisoned
            raw=json.dumps(data,ensure_ascii=False).replace('<','\\u003c')
            page=re.sub(r'(<script type="application/json" id="explorer-data">)[\s\S]*?(</script>)',lambda m:m[1]+raw+m[2],original.read_text(encoding='utf-8'),count=1)
            snapshot=root/'cache-changed.html'
            snapshot.write_text(page,encoding='utf-8')
            output=root/'rebuilt.html'
            package(source/'manifest.json',output,snapshot_from=snapshot)
            result=next(item for item in read_payload(output)['files'].values() if item['name']=='reading-plan.md')
            self.assertEqual(result['text'], original_text)
            self.assertNotIn(poisoned, output.read_text(encoding='utf-8'))


if __name__ == "__main__":
    unittest.main(verbosity=2)
