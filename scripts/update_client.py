"""Manual Pro update checker/downloader with only Python's standard library.

The client checks and downloads an archive after an explicit command.  It does
not install, extract, import, or execute downloaded code.

Usage::

    python editions/source/pro-base/scripts/update_client.py --service http://127.0.0.1:8787 \
        --license-file operator/license.json check
    python scripts/update_client.py --service https://updates.example \
        --license-file operator/license.json download --dest pro-update.zip
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit


TOKEN_MIN_LENGTH = 40
TOKEN_MAX_LENGTH = 512
RELEASE_ID_RE = re.compile(r"^rel_[A-Za-z0-9_-]{12,80}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
MAX_JSON_BYTES = 1024 * 1024
CHUNK_BYTES = 1024 * 1024
PACKAGE_NAME = "chat-archify-pro"
PACKAGE_MANIFEST_PATH = PACKAGE_NAME + "/package-manifest.json"


class UpdateClientError(Exception):
    """Safe user-facing client error; it never contains the bearer token."""


def validate_service_url(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise UpdateClientError("invalid_service_url")
    parsed = urlsplit(value)
    if parsed.username is not None or parsed.password is not None:
        raise UpdateClientError("service_url_userinfo_not_allowed")
    if parsed.query or parsed.fragment or not parsed.hostname:
        raise UpdateClientError("invalid_service_url")
    try:
        parsed.port
    except ValueError:
        raise UpdateClientError("invalid_service_url")
    scheme = parsed.scheme.casefold()
    if scheme not in {"https", "http"}:
        raise UpdateClientError("service_url_must_use_https_or_local_http")
    host = parsed.hostname.casefold().rstrip(".")
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if scheme == "http" and host not in local_hosts:
        raise UpdateClientError("plain_http_requires_localhost")
    path_parts = [part for part in parsed.path.split("/") if part]
    if any(part in {".", ".."} for part in path_parts):
        raise UpdateClientError("invalid_service_url_path")
    return value.rstrip("/")


def _validate_token(token: Any) -> str:
    if (
        not isinstance(token, str)
        or len(token) < TOKEN_MIN_LENGTH
        or len(token) > TOKEN_MAX_LENGTH
        or any(char.isspace() or ord(char) < 32 for char in token)
    ):
        raise UpdateClientError("invalid_license_file")
    return token


def load_license_token(path: os.PathLike[str] | str) -> str:
    try:
        with Path(path).expanduser().open("r", encoding="utf-8") as source:
            document = json.load(source)
        token = document.get("license") or document.get("token")
    except (OSError, ValueError, AttributeError, TypeError):
        raise UpdateClientError("invalid_license_file")
    return _validate_token(token)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):  # type: ignore[override]
        # A service response must never move a request carrying Authorization
        # to another origin.  The service has fixed paths, so rejecting all
        # redirects keeps this invariant simple and observable.
        raise UpdateClientError("redirect_rejected")


def _safe_error_code(error: Exception) -> str:
    if isinstance(error, urllib.error.HTTPError):
        return f"http_{error.code}"
    if isinstance(error, urllib.error.URLError):
        return "network_error"
    if isinstance(error, UpdateClientError):
        return str(error) or "request_failed"
    return "request_failed"


def _safe_archive_name(name: str, allow_directory: bool = False) -> str:
    if not isinstance(name, str) or not name or "\\" in name or name.startswith("/"):
        raise UpdateClientError("unsafe_archive_path")
    if re.match(r"^[A-Za-z]:", name):
        raise UpdateClientError("unsafe_archive_path")
    directory = name.endswith("/")
    clean = name[:-1] if directory else name
    parts = clean.split("/")
    if not clean or any(part in ("", ".", "..") for part in parts):
        raise UpdateClientError("unsafe_archive_path")
    if directory and not allow_directory:
        raise UpdateClientError("unsafe_archive_path")
    return clean + ("/" if directory else "")


def _validate_package_manifest(path: Path, expected_version: str) -> None:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
            by_name = {}
            files = []
            for info in infos:
                name = _safe_archive_name(info.filename, allow_directory=True)
                if name in by_name:
                    raise UpdateClientError("package_manifest_mismatch")
                mode = (info.external_attr >> 16) & 0o170000
                if mode and stat.S_ISLNK(mode):
                    raise UpdateClientError("unsafe_archive_path")
                if info.flag_bits & 0x1 or not name.startswith(PACKAGE_NAME + "/"):
                    raise UpdateClientError("package_manifest_mismatch")
                by_name[name] = info
                if not info.is_dir():
                    files.append(name)
            if files.count(PACKAGE_MANIFEST_PATH) != 1:
                raise UpdateClientError("package_manifest_mismatch")
            try:
                manifest = json.loads(archive.read(by_name[PACKAGE_MANIFEST_PATH]).decode("utf-8"))
            except (UnicodeDecodeError, ValueError, KeyError):
                raise UpdateClientError("package_manifest_mismatch")
            if (
                not isinstance(manifest, dict)
                or manifest.get("name") != PACKAGE_NAME
                or manifest.get("version") != expected_version
            ):
                raise UpdateClientError("package_manifest_mismatch")
            raw_entries = manifest.get("files")
            entries = []
            if isinstance(raw_entries, dict):
                for raw_path, raw_meta in raw_entries.items():
                    if isinstance(raw_meta, str):
                        raw_meta = {"sha256": raw_meta}
                    entries.append({"path": raw_path, "meta": raw_meta, "map_shape": True})
            elif isinstance(raw_entries, list):
                for raw_entry in raw_entries:
                    if not isinstance(raw_entry, dict):
                        raise UpdateClientError("package_manifest_mismatch")
                    entries.append({"path": raw_entry.get("path"), "meta": raw_entry, "map_shape": False})
            else:
                raise UpdateClientError("package_manifest_mismatch")
            expected = {}
            prefix = PACKAGE_NAME + "/"
            for entry in entries:
                raw_path = entry.get("path")
                meta = entry.get("meta")
                if not isinstance(raw_path, str) or not isinstance(meta, dict):
                    raise UpdateClientError("package_manifest_mismatch")
                path_name = _safe_archive_name(raw_path)
                if not path_name.startswith(prefix):
                    path_name = _safe_archive_name(prefix + path_name)
                if path_name == PACKAGE_MANIFEST_PATH or path_name in expected:
                    raise UpdateClientError("package_manifest_mismatch")
                digest = meta.get("sha256")
                size = meta.get("bytes", meta.get("size"))
                if (
                    not isinstance(digest, str)
                    or not SHA256_RE.fullmatch(digest)
                ):
                    raise UpdateClientError("package_manifest_mismatch")
                if entry.get("map_shape"):
                    if size is not None:
                        raise UpdateClientError("package_manifest_mismatch")
                elif isinstance(size, bool) or not isinstance(size, int) or size < 0:
                    raise UpdateClientError("package_manifest_mismatch")
                expected[path_name] = (digest, size)
            actual = set(files) - {PACKAGE_MANIFEST_PATH}
            if set(expected) != actual:
                raise UpdateClientError("package_manifest_mismatch")
            for path_name, (expected_hash, expected_size) in expected.items():
                digest = hashlib.sha256()
                size = 0
                with archive.open(by_name[path_name], "r") as stream:
                    for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
                        digest.update(chunk)
                        size += len(chunk)
                if digest.hexdigest() != expected_hash or (
                    expected_size is not None and size != expected_size
                ):
                    raise UpdateClientError("package_manifest_mismatch")
    except UpdateClientError:
        raise
    except (OSError, KeyError, RuntimeError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile):
        raise UpdateClientError("package_manifest_mismatch")


class UpdateClient:
    def __init__(self, service: str, license_file: os.PathLike[str] | str, timeout: float = 20.0):
        self.service = validate_service_url(service)
        self.token = load_license_token(license_file)
        if timeout <= 0:
            raise UpdateClientError("invalid_timeout")
        self.timeout = float(timeout)
        self.opener = urllib.request.build_opener(_NoRedirectHandler())

    def _url(self, suffix: str) -> str:
        if not suffix.startswith("/") or ".." in suffix:
            raise UpdateClientError("invalid_service_path")
        return self.service + suffix

    def _json_request(self, url: str) -> Dict[str, Any]:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer " + self.token,
            },
            method="GET",
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_JSON_BYTES + 1)
                if len(raw) > MAX_JSON_BYTES:
                    raise UpdateClientError("response_too_large")
        except Exception as error:
            if isinstance(error, UpdateClientError):
                raise
            raise UpdateClientError(_safe_error_code(error))
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise UpdateClientError("invalid_service_response")
        if not isinstance(payload, dict):
            raise UpdateClientError("invalid_service_response")
        return payload

    @staticmethod
    def _validated_release(payload: Dict[str, Any]) -> Dict[str, Any]:
        release = payload.get("release")
        if release is None:
            raise UpdateClientError("no_release_available")
        if not isinstance(release, dict):
            raise UpdateClientError("invalid_service_response")
        release_id = release.get("id")
        version = release.get("version")
        sha256 = release.get("sha256")
        size = release.get("bytes")
        if (
            not isinstance(release_id, str)
            or not RELEASE_ID_RE.fullmatch(release_id)
            or not isinstance(version, str)
            or not SEMVER_RE.fullmatch(version)
            or not isinstance(sha256, str)
            or not SHA256_RE.fullmatch(sha256)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
        ):
            raise UpdateClientError("invalid_service_response")
        return release

    def check(self) -> Dict[str, Any]:
        payload = self._json_request(self._url("/api/v1/updates/check"))
        if payload.get("product") != "pro" or payload.get("authorized") is not True:
            raise UpdateClientError("license_not_authorized")
        release = self._validated_release(payload)
        return {
            "schema": payload.get("schema"),
            "product": payload.get("product"),
            "authorized": True,
            "license": payload.get("license"),
            "release": release,
        }

    def download(self, destination: os.PathLike[str] | str, force: bool = False) -> Dict[str, Any]:
        payload = self.check()
        release = self._validated_release(payload)
        destination_path = Path(destination).expanduser()
        if not destination_path.parent.exists():
            raise UpdateClientError("destination_parent_missing")
        if destination_path.exists() and not force:
            raise UpdateClientError("destination_exists")
        url = self._url(
            "/api/v1/updates/releases/" + str(release["id"]) + "/download"
        )
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/zip",
                "Authorization": "Bearer " + self.token,
            },
            method="GET",
        )
        temporary_name: Optional[str] = None
        count = 0
        digest = hashlib.sha256()
        expected_bytes = int(release["bytes"])
        expected_hash = str(release["sha256"])
        try:
            fd, temporary_name = tempfile.mkstemp(
                prefix="." + destination_path.name + ".",
                suffix=".part",
                dir=str(destination_path.parent),
            )
            os.chmod(temporary_name, 0o600)
            with os.fdopen(fd, "wb") as output:
                try:
                    response = self.opener.open(request, timeout=self.timeout)
                except Exception as error:
                    raise UpdateClientError(_safe_error_code(error))
                with response:
                    while True:
                        chunk = response.read(CHUNK_BYTES)
                        if not chunk:
                            break
                        count += len(chunk)
                        if count > expected_bytes:
                            raise UpdateClientError("download_size_mismatch")
                        digest.update(chunk)
                        output.write(chunk)
                if count != expected_bytes or digest.hexdigest() != expected_hash:
                    raise UpdateClientError("download_integrity_mismatch")
                output.flush()
                os.fsync(output.fileno())
                _validate_package_manifest(Path(temporary_name), str(release["version"]))
            if destination_path.exists() and not force:
                raise UpdateClientError("destination_exists")
            os.replace(temporary_name, destination_path)
            temporary_name = None
        finally:
            if temporary_name:
                try:
                    os.unlink(temporary_name)
                except OSError:
                    pass
        return release


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manual Pro update check/download client")
    parser.add_argument("--service", required=True, help="HTTPS service URL or localhost HTTP URL")
    parser.add_argument("--license-file", required=True, help="local JSON license file")
    parser.add_argument("--timeout", type=float, default=20.0)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="check the authorized release manifest")
    download = sub.add_parser("download", help="download and verify a ZIP; never install it")
    download.add_argument("--dest", required=True, help="destination ZIP path")
    download.add_argument("--force", action="store_true", help="replace an existing destination")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        client = UpdateClient(args.service, args.license_file, timeout=args.timeout)
        if args.command == "check":
            print(json.dumps(client.check(), ensure_ascii=False, indent=2))
            return 0
        release = client.download(args.dest, force=args.force)
        print(
            f"downloaded {release['version']} to {Path(args.dest).expanduser()} "
            f"({release['bytes']} bytes; sha256 {release['sha256']})"
        )
        return 0
    except (UpdateClientError, OSError, ValueError) as error:
        print(f"error: {str(error) or 'operation_failed'}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
