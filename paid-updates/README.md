> **Legacy / 历史兼容代码：** Chat Archify is now fully public; no purchase, license key or this service is needed for usage or public updates. 当前完整版本已公开，此服务不是使用依赖，也未启用收费。

# Chat Archify legacy update service

This is a small, standard-library-only update service for the Chat Archify skill. It
supports manual, one-time license issuance and authorized ZIP delivery. It
does **not** implement checkout, subscriptions, Stripe, webhooks, email, or
automatic installation. Existing offline HTML and skill files remain usable
forever without this service.

## Quick start

Run commands from the Chat Archify repository root. In the combined maintenance
workspace, replace `scripts/update_client.py` with
`editions/source/chat-archify/scripts/update_client.py`, and `tests/test_update_client.py`
with `editions/source/chat-archify/tests/test_update_client.py`.
The directory name is intentionally
`paid-updates`; it is a collection of executable scripts, not a Python package.

```text
python paid-updates/cli.py --db paid-updates/data/paid-updates.sqlite3 \
  --release-dir paid-updates/releases issue \
  --out paid-updates/data/operator.license.json

python paid-updates/cli.py --db paid-updates/data/paid-updates.sqlite3 \
  --release-dir paid-updates/releases release-add \
  --version 0.4.0 --zip path/to/chat-archify.zip \
  --notes-file path/to/notes.txt

python paid-updates/cli.py --db paid-updates/data/paid-updates.sqlite3 \
  --release-dir paid-updates/releases serve

python scripts/update_client.py --service http://127.0.0.1:8787 \
  --license-file paid-updates/data/operator.license.json check
python scripts/update_client.py --service http://127.0.0.1:8787 \
  --license-file paid-updates/data/operator.license.json download \
  --dest paid-updates/data/chat-archify-update.zip
```

`issue` defaults to 365 days. Use `--days N` for another fixed duration or
`--perpetual` for an explicitly perpetual license. The generated token is
written only to the requested JSON file and is never printed. `revoke` accepts
the printed license ID or the local license file and is idempotent:

The JSON uses a `token` field for the bearer secret; keep that file protected.

```text
python paid-updates/cli.py --db paid-updates/data/paid-updates.sqlite3 \
  --release-dir paid-updates/releases revoke --id lic_...
```

The first release registration computes the actual SHA-256 and byte count.
Before copying a ZIP, it validates the archive without extracting it. Every
release must contain `chat-archify/package-manifest.json` with matching
`name`, CLI `--version`, and a complete `files` list. Each listed file must
have its actual `sha256` and `bytes`; unsafe paths, duplicate entries,
encrypted members, symlinks, missing files, and extra unlisted files are
rejected. The real builder manifest uses relative paths and hash strings. The
minimal manifest shape is:

```json
{
  "name": "chat-archify",
  "version": "0.4.0",
  "files": {
    "SKILL.md": "64-lowercase-hex-sha256",
    "scripts/update_client.py": "64-lowercase-hex-sha256"
  }
}
```

The map paths are relative to `chat-archify/`; the validator maps them to
the ZIP members, reads actual bytes while hashing, and requires the complete
regular-member set exactly once. The richer list form with `path`, `sha256`,
and `bytes` is also accepted. The package manifest itself is excluded from
the file map. The HTTP service stores only a SHA-256 hash of each bearer token.
The service has no admin HTTP endpoint. A download request selects a registered release ID,
never an arbitrary filesystem path; the service snapshots and hashes the
same file stream it sends, and rejects a missing, changed, or mismatched ZIP.

## HTTP surface

* `GET /health` returns a minimal liveness response.
* `GET /updates` serves the local update center.
* `GET /api/v1/updates/check` returns public `version`, `notes`, `sha256`, and
  `bytes` metadata. A valid `Authorization: Bearer …` additionally returns
  active license status and expiry.
* `GET /api/v1/updates/releases/{release_id}/download` requires an active
  bearer and returns the registered ZIP.

The browser page keeps its token in memory only. Its optional page-local
polling checkbox is disabled by default; set
`PAID_UPDATES_UPDATE_UI_POLL_SECONDS=60` to offer a 60-second check while the
page is visible. Hiding or closing the page stops polling. No task, mail, SSE,
or long-running background notification is created.

The service binds to `127.0.0.1:8787` by default. Public deployment must use a
TLS reverse proxy, explicitly set `PAID_UPDATES_TRUST_PROXY_TLS=1`, configure
`PAID_UPDATES_TRUSTED_PROXY_IPS` with the proxy peer address, and configure a
fixed `PAID_UPDATES_PUBLIC_ORIGIN` (or an explicit `PAID_UPDATES_ALLOWED_HOSTS`);
direct non-loopback HTTP is refused. An untrusted peer cannot pass by forging
`X-Forwarded-Proto`. Same-origin `Origin` is accepted only after Host/origin
allowlist validation; cross-origin browser access is disabled. Keep the
backend unreachable by firewall. The client accepts HTTPS everywhere, and
permits plain HTTP only for localhost, `127.0.0.1`, or `::1`. The client
rejects redirects entirely, so a bearer can never be forwarded to another
origin.

## Files and secrets

Keep the SQLite file, release directory, and license JSON outside the Chat Archify
skill or public HTML. The generated license JSON is a bearer credential: back
it up securely, protect its parent directory with the current Windows user
ACL (POSIX mode `0600` is applied where supported), and do not paste it into
URLs, logs, issues, or source. The service never logs request targets or
authorization headers.

The client writes a temporary `.part` file, checks both SHA-256 and bytes, and
then validates the package manifest and leaves the ZIP at the requested
destination. The browser download button performs the same SHA-256/bytes check
before creating a browser download. Neither path extracts, installs, imports,
or executes the downloaded archive.

## Future payment adapter (not implemented)

The current flow is manual issue/revoke only. A future one-time payment
provider may add a separate adapter, but the service invariants must remain:

* server configuration chooses the product, price ID, currency, and fixed
  success/cancel paths; no client-supplied price or return URL;
* webhook verification uses the exact raw request bytes and its provider
  signature, with a bounded timestamp tolerance;
* event IDs are deduplicated transactionally, and duplicate or out-of-order
  events cannot roll an entitlement backward;
* provider secrets are server environment variables and never logs.

No payment success is inferred from a browser redirect. No payment provider
credentials are needed to run this service today.

## Local validation / 本地验证

From the Chat Archify repository root, run:

在Chat Archify 仓库根目录运行；在合并维护目录中，将客户端测试路径改为
`editions/source/chat-archify/tests/test_update_client.py`：

```sh
python -m unittest -v paid-updates/tests/test_service.py tests/test_update_client.py
```

The ten tests use temporary license data and local HTTP servers only. They cover
issuance, revocation, manifest validation, authorized download, integrity failures,
origin restrictions and redirect rejection; they do not deploy or connect checkout.

10 项测试只使用临时授权数据与本地 HTTP 服务，验证授权发放／撤销、清单检查、
受权下载、完整性失败、来源限制与重定向拒绝，不部署或接入结账。

## 简体中文说明

这是一个仅使用 Python 标准库的 Chat Archify 历史更新服务：支持管理员手动签发/撤销
Bearer 授权，以及按登记版本下载受权 ZIP。本轮不接入 checkout、订阅、
Stripe、webhook、邮件或自动安装；已有离线 HTML 与 skill 永久可用。

服务默认监听 `127.0.0.1:8787`。生产环境只能放在 TLS 反向代理后，并显式
设置 `PAID_UPDATES_TRUST_PROXY_TLS=1`、受信代理 IP 与固定
`PAID_UPDATES_PUBLIC_ORIGIN`（或允许 Host 列表）；仅凭伪造
`X-Forwarded-Proto` 不能通过，后端仍需防火墙隔离。不会提供 HTTP 管理接口，也不允许跨源
浏览器访问。`issue` 默认有效 365 天，可用 `--days` 或 `--perpetual`；secret
只写入受限授权文件，SQLite 只保存 hash。浏览器页面内检查开关默认关闭，
需要 `PAID_UPDATES_UPDATE_UI_POLL_SECONDS=60` 才提供页面可见期间的定时提示；
不创建后台任务、不发邮件。

客户端必须显式执行 `check` 或 `download`。下载先校验 SHA-256 与 bytes，
再校验包内 `chat-archify/package-manifest.json` 的版本与文件 hash/bytes；
不会自动解压、安装、导入或执行。
