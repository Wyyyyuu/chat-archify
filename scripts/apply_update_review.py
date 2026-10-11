#!/usr/bin/env python3
"""Apply an explicitly approved whole-candidate review safely."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from project_tools import read_source, safe_json, validate_receipt


def apply_review(
    before_path: str | Path,
    candidate_path: str | Path,
    decision_path: str | Path,
    output_path: str | Path,
) -> dict:
    before = read_source(before_path)
    candidate = read_source(candidate_path)
    decision = json.loads(Path(decision_path).read_text(encoding="utf-8-sig"))
    validate_receipt(decision, before, candidate, require_approved=True)
    output = Path(output_path).resolve()
    if output in {before.path, candidate.path}:
        raise ValueError("output must be separate from before and candidate inputs")

    backup = None
    if output.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup_dir = output.parent / "history" / stamp
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / output.name
        shutil.copy2(output, backup)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        # A unique sibling avoids clobbering a pre-existing .tmp file from
        # another run while os.replace keeps the final output atomic.
        with tempfile.NamedTemporaryFile(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent, delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(candidate.raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, output)
        temp_path = None
    except Exception:
        try:
            if temp_path and temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass
        raise
    return {
        "status": "applied",
        "output": str(output),
        "backup": str(backup) if backup else None,
        "project_id": decision.get("project_id"),
        "baselineSHA": before.sha256,
        "candidateSHA": candidate.sha256,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", help="旧版本 HTML 或 explorer-data JSON")
    parser.add_argument("candidate", help="候选 HTML 或 explorer-data JSON")
    parser.add_argument("decision", help="review-receipt.json，必须为 approved")
    parser.add_argument("--output", required=True, help="应用后的 HTML 输出路径")
    args = parser.parse_args()
    result = apply_review(args.before, args.candidate, args.decision, args.output)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        # Error paths intentionally do not create an output or modify either
        # input.  Keep the CLI concise for scripts and human review.
        print(f"apply_update_review: {exc}")
        raise SystemExit(2)
