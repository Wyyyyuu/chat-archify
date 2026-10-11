"""Conservative, dependency-free credential filtering for bundled attachments.

The guard deliberately returns only a generic, user-safe reason.  It is a
small local helper so an installed package does not need the repository or any
network service to make the same decision.
"""
from __future__ import annotations

import base64
import json
import re
from typing import Iterable, Optional
from urllib.parse import unquote, urlsplit


CREDENTIAL_NOTE = "检测到可能的凭据，仅保留原始引用与位置。"

_CREDENTIAL_SUFFIXES = (
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".jks",
    ".keystore",
    ".ppk",
)
_CREDENTIAL_NAMES = {
    ".netrc",
    ".npmrc",
    ".pypirc",
    "auth",
    "auth.json",
    "credential",
    "credentials",
    "credentials.json",
    "credentials.yaml",
    "credentials.yml",
    "credentials.toml",
    "credentials.ini",
    "credentials.cfg",
    "secret",
    "secrets",
    "secret.json",
    "secrets.json",
    "token",
    "tokens",
}
_SSH_KEY_NAME = re.compile(
    r"id_(?:rsa|dsa|ecdsa|ed25519|ed448|xmss)(?:[._-].*)?$", re.I
)
_CREDENTIAL_NAME_VARIANT = re.compile(
    r"(?:credential|credentials|secret|secrets|token|tokens)"
    r"(?:[._-](?:backup|bak|old|prod|production|staging|local|dev|development|test|"
    r"json|yaml|yml|toml|ini|cfg|conf|txt|env))?"
    r"(?:\.(?:backup|bak|old|json|yaml|yml|toml|ini|cfg|conf|txt|env))?$",
    re.I,
)

_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:(?:[A-Z0-9]+ )?PRIVATE KEY|PGP PRIVATE KEY BLOCK)-----", re.I
)
_JWT = re.compile(
    r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\b"
)
_PROVIDER_TOKEN = re.compile(
    r"\b(?:"
    r"sk-(?:proj-)?[A-Za-z0-9_-]{16,}|"
    r"gh[pousr]_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"glpat-[A-Za-z0-9_-]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{15,}|"
    r"(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}|"
    r"AIza[0-9A-Za-z_-]{30,}|"
    r"hf_[A-Za-z0-9]{20,}|"
    r"npm_[A-Za-z0-9]{20,}|"
    r"(?:AKIA|ASIA)[0-9A-Z]{16}"
    r")\b"
)
_ASSIGNMENT = re.compile(
    r"(?im)[\"']?\b(?P<key>(?:"
    r"[a-z][a-z0-9_.-]*(?:api[_-]?key|access[_-]?key|secret|token|password|credential|private[_-]?key)|"
    r"api[_-]?key|access[_-]?key|secret|token|password|credential"
    r"))\b[\"']?\s*(?:=|:)\s*"
    r"(?P<value>\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;#}]+)"
)

_PLACEHOLDER_WORDS = re.compile(
    r"(?:^|[_\-.])(?:your|example|placeholder|changeme|change-me|replace|"
    r"insert|dummy|sample|redacted|fake|todo|none|null|undefined)(?:$|[_\-.])",
    re.I,
)
_PROVIDER_ASSIGNMENT_WORDS = (
    "openai",
    "aws",
    "github",
    "gitlab",
    "slack",
    "stripe",
    "google",
    "azure",
    "anthropic",
    "cohere",
    "huggingface",
    "npm",
    "docker",
)


def _path_parts(name: object) -> list[str]:
    value = str(name).replace("\\", "/")
    return [part.casefold() for part in value.split("/") if part]


def credential_filename_reason(name: object) -> Optional[str]:
    """Return a safe reason when *name* is conventionally credential-bearing."""

    parts = _path_parts(name)
    if not parts:
        return None
    base = parts[-1]
    # Treat every .env variant as sensitive, including environment-specific
    # and backup names.  A Markdown guide with placeholders is still allowed;
    # this rule is intentionally limited to environment-file names.
    if base.startswith(".env"):
        return CREDENTIAL_NOTE
    if base in _CREDENTIAL_NAMES or _CREDENTIAL_NAME_VARIANT.fullmatch(base):
        return CREDENTIAL_NOTE
    if _SSH_KEY_NAME.fullmatch(base):
        return CREDENTIAL_NOTE
    if base.endswith(_CREDENTIAL_SUFFIXES):
        return CREDENTIAL_NOTE
    return None


def _text_like(text: str) -> bool:
    if not text or "\x00" in text:
        return False
    controls = sum(
        1
        for char in text
        if ord(char) < 32 and char not in "\t\r\n\f"
    )
    return controls <= max(2, len(text) // 100)


def decode_text(data: bytes) -> Optional[str]:
    """Decode likely UTF-8/UTF-16 text without trusting a MIME guess."""

    if not isinstance(data, (bytes, bytearray, memoryview)):
        return None
    raw = bytes(data)
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        for encoding in ("utf-16", "utf-16-le", "utf-16-be"):
            try:
                text = raw.decode(encoding)
            except UnicodeDecodeError:
                continue
            if _text_like(text):
                return text
        return None
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = None
    if text is not None and _text_like(text):
        return text

    # BOM-less UTF-16 is common in exported Windows text.  Require a visible
    # NUL pattern first so ordinary binary data is not treated as prose.
    if len(raw) % 2 == 0 and raw and raw.count(b"\x00") >= max(2, len(raw) // 10):
        for encoding in ("utf-16-le", "utf-16-be"):
            try:
                candidate = raw.decode(encoding)
            except UnicodeDecodeError:
                continue
            if _text_like(candidate):
                return candidate
    return None


def _looks_placeholder(value: str) -> bool:
    clean = value.strip().strip("\"'` ").rstrip(",;")
    lower = clean.casefold()
    if not lower:
        return True
    if any(marker in lower for marker in ("${", "{{", "os.getenv", "os.environ", "process.env", "env.get(")):
        return True
    if lower in {"none", "null", "nil", "undefined", "false", "true"}:
        return True
    if lower in {"api_key", "api-key", "token", "secret", "password"}:
        return True
    if lower.endswith(("example", "examplekey")):
        return True
    if lower.startswith(("<", "[", "your-", "your_")) or lower.endswith((">", "]")):
        return True
    if _PLACEHOLDER_WORDS.search(lower):
        return True
    if len(set(lower)) == 1 and len(lower) >= 4:
        return True
    return False


def _secret_value(value: str, key: str) -> bool:
    clean = value.strip().strip("\"'` ").rstrip(",;")
    if _looks_placeholder(clean):
        return False
    if len(clean) < 16 or any(char.isspace() for char in clean):
        return False
    classes = sum(
        bool(re.search(pattern, clean))
        for pattern in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]")
    )
    if classes < 2:
        return False
    key_lower = key.casefold()
    if any(word in key_lower for word in _PROVIDER_ASSIGNMENT_WORDS):
        return True
    return len(clean) >= 20


def content_credential_reason(text: str) -> Optional[str]:
    """Return a safe reason for high-confidence credential content."""

    if not isinstance(text, str):
        return None
    if _PRIVATE_KEY.search(text):
        return CREDENTIAL_NOTE
    for match in re.finditer(r'(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqps?)://[^\s"\x27<>]+',text):
        try:
            password=urlsplit(match.group(0)).password
            if password and not _looks_placeholder(unquote(password)):
                return CREDENTIAL_NOTE
        except ValueError:
            pass
    if text.lstrip().startswith('{'):
        try:
            auths=json.loads(text).get('auths', {})
            for config in auths.values() if isinstance(auths,dict) else []:
                auth=config.get('auth') if isinstance(config,dict) else None
                if isinstance(auth,str):
                    decoded=base64.b64decode(auth,validate=True).decode('utf-8')
                    user, separator, password=decoded.partition(':')
                    if user and separator and password and not _looks_placeholder(password):
                        return CREDENTIAL_NOTE
        except (ValueError,TypeError,AttributeError,UnicodeDecodeError):
            pass
    for pattern in (_JWT, _PROVIDER_TOKEN):
        for match in pattern.finditer(text):
            if not _looks_placeholder(match.group(0)):
                return CREDENTIAL_NOTE
    for match in _ASSIGNMENT.finditer(text):
        if _secret_value(match.group("value"), match.group("key")):
            return CREDENTIAL_NOTE
    return None


def credential_reason(
    name: object,
    data: Optional[bytes] = None,
    additional_names: Iterable[object] = (),
) -> Optional[str]:
    """Inspect a filename and optional bytes, returning only a safe reason."""

    for candidate in (name, *additional_names):
        reason = credential_filename_reason(candidate)
        if reason:
            return reason
    if data is not None:
        reason = content_credential_reason(decode_text(data) or "")
        if reason:
            return reason
    return None
