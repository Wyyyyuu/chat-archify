"""Command-line administration and local serving for ``paid-updates``.

Examples are intentionally executable as a file (the directory contains a
hyphen and is not a Python package):

    python paid-updates/cli.py issue --out operator/licenses/alice.json
    python paid-updates/cli.py revoke --id lic_...
    python paid-updates/cli.py release-add --version 0.4.0 --zip release.zip
    python paid-updates/cli.py serve
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import List, Optional

from core import DEFAULT_LICENSE_DAYS, ServiceError, Store, iso_utc, load_license_token
from server import ConfigError, ServerConfig, serve


def _default_db() -> str:
    return os.environ.get("PAID_UPDATES_DB_PATH", "data/paid-updates.sqlite3")


def _default_release_dir() -> str:
    return os.environ.get("PAID_UPDATES_RELEASE_DIR", "releases")


def _store(args: argparse.Namespace) -> Store:
    return Store(args.db, args.release_dir)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local Chat Archify update license/release service")
    parser.add_argument("--db", default=_default_db(), help="SQLite path (default: env or data/paid-updates.sqlite3)")
    parser.add_argument("--release-dir", default=_default_release_dir(), help="server-owned ZIP directory")
    sub = parser.add_subparsers(dest="command", required=True)

    issue = sub.add_parser("issue", help="issue a one-time manual license")
    issue.add_argument("--out", required=True, help="new restricted JSON license file")
    issue.add_argument("--days", type=int, default=DEFAULT_LICENSE_DAYS, help="validity in days (default: 365)")
    issue.add_argument("--perpetual", action="store_true", help="issue a license without an expiry")

    revoke = sub.add_parser("revoke", help="revoke a license idempotently")
    revoke_group = revoke.add_mutually_exclusive_group(required=True)
    revoke_group.add_argument("--id", dest="license_id", help="license id printed when it was issued")
    revoke_group.add_argument("--license-file", help="read the bearer from a local license JSON file")

    release = sub.add_parser("release-add", help="register and copy an administrator-owned Pro ZIP")
    release.add_argument("--version", required=True, help="SemVer release version")
    release.add_argument("--zip", required=True, dest="source_zip", help="administrator-owned ZIP input")
    release.add_argument("--notes-file", help="UTF-8 update notes; empty when omitted")

    serve_parser = sub.add_parser("serve", help="run the local HTTP update service")
    serve_parser.add_argument("--bind", help="override PAID_UPDATES_BIND")
    serve_parser.add_argument("--port", type=int, help="override PAID_UPDATES_PORT")
    serve_parser.add_argument("--poll-seconds", type=int, help="override page-local polling interval")
    serve_parser.add_argument(
        "--trust-proxy-tls",
        action="store_true",
        help="explicitly allow non-loopback use behind an HTTPS reverse proxy",
    )
    return parser


def _run(args: argparse.Namespace) -> int:
    if args.command == "issue":
        store = _store(args)
        record, _secret = store.issue_license(
            args.out,
            days=args.days,
            perpetual=args.perpetual,
        )
        # Deliberately do not print _secret.  The only copy is in --out.
        expiry = iso_utc(record.expires_at) or "perpetual"
        print(f"issued {record.license_id}; expires {expiry}; file {Path(args.out).expanduser()}")
        return 0

    if args.command == "revoke":
        store = _store(args)
        if args.license_file:
            token = load_license_token(args.license_file)
            found = store.revoke_license(token=token)
        else:
            found = store.revoke_license(license_id=args.license_id)
        print("revoked" if found else "already absent")
        return 0

    if args.command == "release-add":
        store = _store(args)
        notes = ""
        if args.notes_file:
            notes = Path(args.notes_file).read_text(encoding="utf-8")
        release = store.register_release(args.version, args.source_zip, notes=notes)
        print(
            f"registered {release.version} ({release.release_id}); "
            f"bytes {release.bytes}; sha256 {release.sha256}"
        )
        return 0

    if args.command == "serve":
        config = ServerConfig.from_env()
        overrides = {}
        if args.bind is not None:
            overrides["bind"] = args.bind
        if args.port is not None:
            overrides["port"] = args.port
        if args.poll_seconds is not None:
            overrides["poll_seconds"] = args.poll_seconds
        if args.trust_proxy_tls:
            overrides["trust_proxy_tls"] = True
        if overrides:
            config = replace(config, **overrides)
            config.validate()
        serve(_store(args), config)
        return 0

    raise ConfigError("unknown_command")


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return _run(args)
    except (ServiceError, OSError, ValueError) as error:
        # Keep expected operator errors concise and never print a token or a
        # traceback that could include one from a malformed file.
        print(f"error: {str(error) or 'operation_failed'}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
