#!/usr/bin/env python3
"""Create an offline, data-only review of two Chat Archify payloads."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from project_tools import (
    build_update_review,
    make_review_receipt,
    read_source,
    render_review_html,
    safe_json,
)


def review(before_path: str | Path, candidate_path: str | Path, out_dir: str | Path) -> dict:
    before = read_source(before_path)
    candidate = read_source(candidate_path)
    result = build_update_review(
        before.payload,
        candidate.payload,
        baseline_sha=before.sha256,
        candidate_sha=candidate.sha256,
        baseline_bytes=len(before.raw),
        candidate_bytes=len(candidate.raw),
    )
    output = Path(out_dir).resolve()
    destinations = [(output / name).resolve() for name in ('update-review.json','review-receipt.json','update-review.html')]
    if any(path in {before.path,candidate.path} for path in destinations):
        raise ValueError('review outputs must be separate from before and candidate inputs')
    output.mkdir(parents=True, exist_ok=True)
    # The JSON is the machine-readable review.  The receipt is intentionally
    # pending; a reviewer must explicitly choose approved/rejected before the
    # apply command can touch an output file.
    (output / "update-review.json").write_text(safe_json(result) + "\n", encoding="utf-8")
    pending = make_review_receipt(result, "pending", "尚未作出整体批准或拒绝决定。")
    (output / "review-receipt.json").write_text(safe_json(pending) + "\n", encoding="utf-8")
    (output / "update-review.html").write_text(render_review_html(result), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", help="旧版本 HTML 或 explorer-data JSON")
    parser.add_argument("candidate", help="候选 HTML 或 explorer-data JSON")
    parser.add_argument("--out-dir", default="review", help="离线审查产物目录")
    args = parser.parse_args()
    result = review(args.before, args.candidate, args.out_dir)
    print(
        json.dumps(
            {
                "status": "created",
                "out_dir": str(Path(args.out_dir).resolve()),
                "project_id": result.get("project_id"),
                "baselineSHA": result["baseline"]["sha256"],
                "candidateSHA": result["candidate"]["sha256"],
                "change_count": result["summary"]["change_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
