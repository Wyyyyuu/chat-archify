"""Local-first HTTP service for authorized Chat Archify update delivery.

Run this module through ``cli.py serve``.  The default listener is loopback;
public deployment requires an explicitly enabled TLS reverse proxy.  There is
no HTTP admin surface and no payment or checkout implementation here.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterable, Optional, Tuple
from urllib.parse import unquote, urlsplit

from core import (
    LicenseError,
    LicenseRecord,
    ReleaseIntegrityError,
    ServiceError,
    Store,
    iso_utc,
    parse_bearer_header,
)


class ConfigError(ServiceError):
    pass


def _host_parts(value: str) -> Tuple[str, Optional[int]]:
    if not isinstance(value, str) or not value or any(char in value for char in "\r\n\x00"):
        raise ConfigError("invalid_host")
    parsed = urlsplit("//" + value)
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or not parsed.hostname
    ):
        raise ConfigError("invalid_host")
    try:
        port = parsed.port
    except ValueError:
        raise ConfigError("invalid_host")
    host = parsed.hostname.casefold().rstrip(".")
    return host, port


def _origin_parts(value: str) -> Tuple[str, str, Optional[int]]:
    if not isinstance(value, str) or not value:
        raise ConfigError("invalid_public_origin")
    parsed = urlsplit(value)
    if parsed.username is not None or parsed.password is not None:
        raise ConfigError("invalid_public_origin")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment or not parsed.hostname:
        raise ConfigError("invalid_public_origin")
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"}:
        raise ConfigError("invalid_public_origin")
    try:
        port = parsed.port
    except ValueError:
        raise ConfigError("invalid_public_origin")
    return scheme, parsed.hostname.casefold().rstrip("."), port


def _effective_port(scheme: str, port: Optional[int]) -> int:
    return int(port or (443 if scheme == "https" else 80))


def _is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _origin_key(scheme: str, host: str, port: Optional[int]) -> Tuple[str, str, int]:
    return scheme.casefold(), host.casefold().rstrip("."), _effective_port(scheme, port)


@dataclass(frozen=True)
class ServerConfig:
    bind: str = "127.0.0.1"
    port: int = 8787
    trust_proxy_tls: bool = False
    poll_seconds: int = 0
    trusted_proxy_ips: Tuple[str, ...] = ("127.0.0.1", "::1")
    public_origin: Optional[str] = None
    allowed_hosts: Tuple[str, ...] = ()

    def validate(self) -> None:
        if not (0 <= int(self.port) <= 65535):
            raise ConfigError("invalid_port")
        if int(self.poll_seconds) < 0 or int(self.poll_seconds) > 86400:
            raise ConfigError("invalid_poll_interval")
        try:
            address = ipaddress.ip_address(self.bind)
        except ValueError:
            if self.bind.casefold() not in {"localhost"}:
                raise ConfigError("invalid_bind")
            address = ipaddress.ip_address("127.0.0.1")
        if not address.is_loopback and not self.trust_proxy_tls:
            raise ConfigError("non_loopback_requires_tls_proxy")
        for value in self.trusted_proxy_ips:
            try:
                ipaddress.ip_address(value)
            except ValueError:
                raise ConfigError("invalid_trusted_proxy")
        for value in self.allowed_hosts:
            _host_parts(value)
        if self.public_origin:
            scheme, host, _port = _origin_parts(self.public_origin)
            if scheme == "http" and not _is_loopback_host(host):
                raise ConfigError("public_origin_requires_https")
        if not address.is_loopback and self.trust_proxy_tls and not (
            self.public_origin or self.allowed_hosts
        ):
            raise ConfigError("public_origin_or_allowed_host_required")

    @classmethod
    def from_env(cls) -> "ServerConfig":
        bind = os.environ.get("PAID_UPDATES_BIND", "127.0.0.1").strip() or "127.0.0.1"
        port_text = os.environ.get("PAID_UPDATES_PORT", "8787")
        poll_text = os.environ.get("PAID_UPDATES_UPDATE_UI_POLL_SECONDS", "0")
        try:
            port = int(port_text)
            poll_seconds = int(poll_text)
        except ValueError:
            raise ConfigError("invalid_server_config")
        trust = os.environ.get("PAID_UPDATES_TRUST_PROXY_TLS", "0").casefold() in {
            "1",
            "true",
            "yes",
        }
        trusted_proxy_ips = tuple(
            item.strip()
            for item in os.environ.get("PAID_UPDATES_TRUSTED_PROXY_IPS", "127.0.0.1,::1").split(",")
            if item.strip()
        )
        allowed_hosts = tuple(
            item.strip()
            for item in os.environ.get("PAID_UPDATES_ALLOWED_HOSTS", "").split(",")
            if item.strip()
        )
        public_origin = os.environ.get("PAID_UPDATES_PUBLIC_ORIGIN", "").strip() or None
        config = cls(
            bind=bind,
            port=port,
            trust_proxy_tls=trust,
            poll_seconds=poll_seconds,
            trusted_proxy_ips=trusted_proxy_ips,
            public_origin=public_origin,
            allowed_hosts=allowed_hosts,
        )
        config.validate()
        return config


_RELEASE_ID_PATH = re.compile(r"^rel_[A-Za-z0-9_-]{12,80}$")


UPDATE_PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Chat Archify 更新中心</title>
  <style>
    :root { color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }
    body { margin: 0; background: #f7faff; color: #17324d; }
    main { width: min(720px, calc(100% - 32px)); margin: 7vh auto; }
    .card { background: #fff; border: 1px solid #d8e7f5; border-radius: 18px; box-shadow: 0 14px 36px #2f6f9a18; padding: clamp(22px, 5vw, 42px); }
    h1 { margin: 0 0 8px; color: #135ea8; font-size: clamp(1.5rem, 4vw, 2.1rem); }
    .muted { color: #55718a; line-height: 1.6; }
    label { display: block; font-weight: 650; margin-top: 24px; }
    input { box-sizing: border-box; display: block; width: 100%; margin-top: 8px; border: 1px solid #a9c6df; border-radius: 10px; padding: 12px 14px; color: #17324d; background: #fbfdff; }
    button { border: 0; border-radius: 10px; padding: 11px 16px; background: #1268b3; color: white; font-weight: 700; cursor: pointer; }
    button.secondary { background: #e7f1fb; color: #15578e; }
    button:disabled { opacity: .55; cursor: wait; }
    .actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }
    .status { margin-top: 22px; padding: 14px 16px; border-radius: 12px; background: #edf6ff; min-height: 1.3em; white-space: pre-wrap; }
    .status.error { background: #fff0f0; color: #9d2828; }
    .release { margin-top: 18px; padding-top: 18px; border-top: 1px solid #e5eef6; }
    .release h2 { margin: 0 0 8px; font-size: 1.1rem; }
    .meta { color: #55718a; font-size: .92rem; }
    .notes { margin: 12px 0 0; line-height: 1.55; white-space: pre-wrap; }
    .poll { display: flex; gap: 8px; align-items: center; margin-top: 17px; color: #55718a; font-size: .92rem; }
    .poll input { width: auto; margin: 0; }
    code { overflow-wrap: anywhere; }
  </style>
</head>
<body>
<main>
  <section class="card" aria-labelledby="title">
    <h1 id="title">Chat Archify 更新中心</h1>
    <p class="muted">输入授权文件中的许可证令牌。令牌只保存在当前页面内存中，不会写入 URL、localStorage 或 cookie。</p>
    <label for="license">许可证令牌</label>
    <input id="license" type="password" autocomplete="off" spellcheck="false" placeholder="Bearer token">
    <div class="actions">
      <button id="check" type="button">检查更新</button>
      <button id="download" class="secondary" type="button" disabled>下载授权 ZIP</button>
    </div>
    <label class="poll"><input id="poll" type="checkbox"><span id="poll-label">页面打开时定时检查</span></label>
    <div id="status" class="status" role="status" aria-live="polite">尚未检查。</div>
    <div id="release" class="release" hidden>
      <h2 id="version"></h2>
      <div id="meta" class="meta"></div>
      <div id="notes" class="notes"></div>
    </div>
  </section>
</main>
<script>
(() => {
  const pollSeconds = __POLL_SECONDS__;
  const tokenInput = document.getElementById('license');
  const checkButton = document.getElementById('check');
  const downloadButton = document.getElementById('download');
  const pollToggle = document.getElementById('poll');
  const pollLabel = document.getElementById('poll-label');
  const status = document.getElementById('status');
  const releaseBox = document.getElementById('release');
  const version = document.getElementById('version');
  const meta = document.getElementById('meta');
  const notes = document.getElementById('notes');
  let releaseId = null;
  let releaseMeta = null;
  let timer = null;

  function setStatus(message, error) {
    status.textContent = message;
    status.classList.toggle('error', Boolean(error));
  }
  function token() { return tokenInput.value.trim(); }
  async function check(silent) {
    const value = token();
    checkButton.disabled = true;
    try {
      const headers = { 'Accept': 'application/json' };
      if (value) headers['Authorization'] = 'Bearer ' + value;
      const response = await fetch('/api/v1/updates/check', {
        headers,
        cache: 'no-store'
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'check_failed');
      const license = data.license || {};
      setStatus(data.authorized ? ('许可证有效，状态：' + (license.status || 'active')) : '需要有效许可证才能下载。', false);
      const current = data.release;
      releaseId = current && current.id ? current.id : null;
      releaseMeta = current || null;
      downloadButton.disabled = !data.authorized || !releaseId;
      if (current) {
        releaseBox.hidden = false;
        version.textContent = '版本 ' + current.version;
        meta.textContent = current.bytes + ' bytes · SHA-256 ' + current.sha256;
        notes.textContent = current.notes || '暂无更新日志。';
      } else {
        releaseBox.hidden = true;
      }
    } catch (error) {
      downloadButton.disabled = true;
      if (!silent) setStatus('检查失败：' + (error.message || 'unknown_error'), true);
    } finally { checkButton.disabled = false; }
  }
  checkButton.addEventListener('click', () => check(false));
  downloadButton.addEventListener('click', () => {
    if (!releaseId || !token()) return;
    const link = document.createElement('a');
    link.href = '/api/v1/updates/releases/' + encodeURIComponent(releaseId) + '/download';
    link.setAttribute('download', '');
    // The token is placed only in the fetch header; navigation would expose no credential.
    fetch(link.href, { headers: { 'Authorization': 'Bearer ' + token() } })
      .then((response) => { if (!response.ok) throw new Error('download_failed'); return response.arrayBuffer(); })
      .then(async (bytes) => {
        if (!releaseMeta || bytes.byteLength !== Number(releaseMeta.bytes)) throw new Error('download_size_mismatch');
        const digest = await crypto.subtle.digest('SHA-256', bytes);
        const actual = Array.from(new Uint8Array(digest)).map((value) => value.toString(16).padStart(2, '0')).join('');
        if (actual !== releaseMeta.sha256) throw new Error('download_integrity_mismatch');
        return new Blob([bytes], { type: 'application/zip' });
      })
      .then((blob) => { const url = URL.createObjectURL(blob); link.href = url; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); })
      .catch((error) => setStatus('下载失败：' + (error.message || 'unknown_error'), true));
  });
  function stopPolling() { if (timer) { clearInterval(timer); timer = null; } }
  function startPolling() {
    stopPolling();
    if (!pollToggle.checked || !pollSeconds || document.hidden) return;
    timer = setInterval(() => { if (!document.hidden) check(true); }, pollSeconds * 1000);
  }
  pollToggle.disabled = !pollSeconds;
  pollLabel.textContent = pollSeconds ? ('页面打开时每 ' + pollSeconds + ' 秒检查一次') : '页面内定时检查（服务未启用）';
  pollToggle.title = pollSeconds ? '' : '服务默认只支持手动检查。';
  pollToggle.addEventListener('change', startPolling);
  document.addEventListener('visibilitychange', startPolling);
})();
</script>
</body>
</html>
"""


class UpdateHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: Tuple[str, int], store: Store, config: ServerConfig):
        config.validate()
        self.store = store
        self.config = config
        super().__init__(address, UpdateRequestHandler)


class UpdateRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ProUpdateService/1"

    def log_message(self, format: str, *args: Any) -> None:
        # Never interpolate the request target or headers: a mistaken bearer in
        # a URL must not become an access-log credential.
        return

    @property
    def update_server(self) -> UpdateHTTPServer:
        return self.server  # type: ignore[return-value]

    def _send_bytes(
        self,
        status: int,
        body: bytes,
        content_type: str,
        cache_control: str = "no-store",
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8")

    def _error(self, status: int, code: str) -> None:
        self._send_json(status, {"error": code})

    def _validated_request_host(self, scheme: str) -> Optional[Tuple[str, Optional[int]]]:
        try:
            host, port = _host_parts(self.headers.get("Host", ""))
        except ConfigError:
            self._error(HTTPStatus.BAD_REQUEST, "invalid_host")
            return None
        config = self.update_server.config
        if config.public_origin:
            _public_scheme, public_host, public_port = _origin_parts(config.public_origin)
            if host != public_host or _effective_port(scheme, port) != _effective_port(
                _public_scheme, public_port
            ):
                self._error(HTTPStatus.BAD_REQUEST, "invalid_host")
                return None
        elif config.allowed_hosts:
            matches = False
            candidate_port = _effective_port(scheme, port)
            for allowed in config.allowed_hosts:
                allowed_host, allowed_port = _host_parts(allowed)
                if host == allowed_host and (
                    allowed_port is None or candidate_port == _effective_port(scheme, allowed_port)
                ):
                    matches = True
                    break
            if not matches:
                self._error(HTTPStatus.BAD_REQUEST, "invalid_host")
                return None
        else:
            actual_port = int(self.update_server.server_address[1])
            if not _is_loopback_host(host) or _effective_port(scheme, port) != actual_port:
                self._error(HTTPStatus.BAD_REQUEST, "invalid_host")
                return None
        return host, port

    def _secure_transport(self) -> bool:
        config = self.update_server.config
        scheme = "https" if config.trust_proxy_tls else "http"
        if config.trust_proxy_tls:
            try:
                peer = ipaddress.ip_address(self.client_address[0])
                trusted = {ipaddress.ip_address(value) for value in config.trusted_proxy_ips}
            except ValueError:
                self._error(HTTPStatus.FORBIDDEN, "untrusted_proxy")
                return False
            if peer not in trusted:
                self._error(HTTPStatus.FORBIDDEN, "untrusted_proxy")
                return False
            forwarded = self.headers.get("X-Forwarded-Proto", "")
            protocol = forwarded.split(",", 1)[0].strip().casefold()
            if protocol != "https":
                self._error(HTTPStatus.BAD_REQUEST, "https_required")
                return False
        request_host = self._validated_request_host(scheme)
        if request_host is None:
            return False
        origin = self.headers.get("Origin")
        if origin:
            try:
                origin_parts = _origin_parts(origin)
            except ConfigError:
                self._error(HTTPStatus.FORBIDDEN, "cross_origin_disabled")
                return False
            if config.public_origin:
                expected = _origin_parts(config.public_origin)
            else:
                expected = (scheme, request_host[0], request_host[1])
            if _origin_key(*origin_parts) != _origin_key(*expected):
                self._error(HTTPStatus.FORBIDDEN, "cross_origin_disabled")
                return False
        return True

    def _authorization(self, required: bool) -> Optional[LicenseRecord]:
        header = self.headers.get("Authorization")
        if header is None and not required:
            return None
        try:
            token = parse_bearer_header(header)
        except LicenseError:
            self._error(HTTPStatus.UNAUTHORIZED, "invalid_license")
            return None
        lookup = self.update_server.store.lookup_token(token)
        if lookup.status != "active" or lookup.record is None or lookup.record.product != "pro":
            self._error(HTTPStatus.UNAUTHORIZED, "invalid_license")
            return None
        return lookup.record

    def _request_path(self) -> Optional[str]:
        parsed = urlsplit(self.path)
        if parsed.netloc or parsed.scheme or parsed.path.startswith("//"):
            self._error(HTTPStatus.BAD_REQUEST, "invalid_request_target")
            return None
        if any(char in parsed.path for char in "\x00\r\n"):
            self._error(HTTPStatus.BAD_REQUEST, "invalid_request_target")
            return None
        decoded = unquote(parsed.path)
        if "%" in decoded:
            # Reject double-encoded traversal instead of trying to normalize it.
            self._error(HTTPStatus.BAD_REQUEST, "invalid_request_target")
            return None
        return decoded

    def do_GET(self) -> None:
        if not self._secure_transport():
            return
        path = self._request_path()
        if path is None:
            return
        if path == "/health":
            self._send_json(HTTPStatus.OK, {"ok": True})
            return
        if path == "/updates":
            page = UPDATE_PAGE.replace("__POLL_SECONDS__", str(self.update_server.config.poll_seconds))
            self._send_bytes(HTTPStatus.OK, page.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/v1/updates/check":
            self._check_update()
            return
        prefix = "/api/v1/updates/releases/"
        suffix = "/download"
        if path.startswith(prefix) and path.endswith(suffix):
            release_id = path[len(prefix) : -len(suffix)]
            if "/" in release_id or not _RELEASE_ID_PATH.fullmatch(release_id):
                self._error(HTTPStatus.NOT_FOUND, "not_found")
                return
            self._download(release_id)
            return
        self._error(HTTPStatus.NOT_FOUND, "not_found")

    def do_POST(self) -> None:
        if not self._secure_transport():
            return
        self._error(HTTPStatus.METHOD_NOT_ALLOWED, "method_not_allowed")

    def _check_update(self) -> None:
        release = self.update_server.store.latest_release()
        header = self.headers.get("Authorization")
        license_record: Optional[LicenseRecord] = None
        if header is not None:
            license_record = self._authorization(required=False)
            # _authorization has already sent a generic 401 when a supplied
            # token is malformed, unknown, expired, or revoked.
            if license_record is None:
                return
        payload: Dict[str, Any] = {
            "schema": 1,
            "product": "pro",
            "release": self.update_server.store.release_payload(release),
            "authorized": license_record is not None,
            "license": None,
        }
        if license_record is not None:
            payload["license"] = {
                "status": "active",
                "expires_at": iso_utc(license_record.expires_at),
            }
        self._send_json(HTTPStatus.OK, payload)

    def _download(self, release_id: str) -> None:
        if self._authorization(required=True) is None:
            return
        release = self.update_server.store.release_by_id(release_id)
        if release is None:
            self._error(HTTPStatus.NOT_FOUND, "not_found")
            return
        try:
            snapshot, digest, size = self.update_server.store.snapshot_release(release)
        except ReleaseIntegrityError:
            self._error(HTTPStatus.SERVICE_UNAVAILABLE, "release_integrity_failure")
            return
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="chat-archify-update-{release.version}.zip"',
            )
            self.end_headers()
            while True:
                chunk = snapshot.read(1024 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            snapshot.close()


def make_server(store: Store, config: Optional[ServerConfig] = None) -> UpdateHTTPServer:
    selected = config or ServerConfig.from_env()
    selected.validate()
    return UpdateHTTPServer((selected.bind, selected.port), store, selected)


def serve(store: Store, config: Optional[ServerConfig] = None) -> None:
    httpd = make_server(store, config)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
