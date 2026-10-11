from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from project_tools import (  # noqa: E402
    build_continuation_package,
    build_update_review,
    make_review_receipt,
    read_source,
    render_review_html,
    safe_json,
)


def payload(summary="原始摘要"):
    return {
        "schema_version": 1,
        "project_id": "project-smoke",
        "project": {"title": "测试项目", "summary": "仅用于 smoke", "current_state": "已形成候选方案。"},
        "coverage": ["只覆盖测试记录。"],
        "sources": [{"id": "source", "title": "记录", "kind": "document", "coverage": "excerpt", "locator": "record.md L1", "uri": "record.md", "note": "明确来源说明。", "file_id": "f1"}],
        "nodes": [
            {"id": "done", "kind": "decision", "title": "已完成决策", "summary": summary, "reason": "证据明确", "branch": "主线", "status": "completed", "evidence": [{"source": "source", "locator": "record.md L2"}], "artifacts": [{"label": "说明", "uri": "record.md", "role": "referenced", "verification": "exists", "note": "阶段说明", "file_id": "f1"}]},
            {"id": "plan", "kind": "goal", "title": "下一候选", "summary": "仍待验证", "reason": "没有执行证据", "branch": "主线", "status": "proposed", "evidence": [{"source": "source", "locator": "record.md L3"}], "artifacts": [{"label": "未知附件", "uri": "unknown.txt", "role": "referenced", "verification": "mentioned", "file_id": "missing"}]},
        ],
        "edges": [{"from": "done", "to": "plan", "type": "continues", "confidence": "explicit", "reason": "后续候选", "evidence": [{"source": "source", "locator": "record.md L4"}]}],
        "open_questions": ["执行结果未知。"],
        "revisions": [],
        "files": {"f1": {"id": "f1", "path": "C:/work/record.md", "name": "record.md", "status": "embedded", "bytes": 12, "sha256": "a" * 64, "text": "SECRET_CODE_SHOULD_NOT_APPEAR"}},
    }


def html_for(data):
    return f'<script type="application/json" id="explorer-data">{safe_json(data)}</script><script>throw new Error("inert")</script>'.encode()


def multi_payload():
    first = payload()
    second = copy.deepcopy(first)
    second["project"] = {
        "title": "第二章项目片段",
        "summary": "后章独有摘要",
        "current_state": "后章独有当前状态。",
    }
    second["coverage"] = ["后章独有覆盖边界。"]
    second["open_questions"] = ["后章独有待确认事项。"]
    second["nodes"][0]["summary"] = "后章独有已完成事实。"
    second["nodes"][1]["summary"] = "后章独有计划事实。"
    second["files"] = {
        "f2": {"id": "f2", "path": "C:/work/chapter-two.md", "name": "chapter-two.md", "status": "embedded", "bytes": 5, "sha256": "c" * 64}
    }
    second["nodes"][1]["artifacts"] = [{"label": "后章说明", "uri": "chapter-two.md", "role": "referenced", "verification": "exists", "note": "后章用途", "file_id": "f2"}]
    return {
        "schema_version": 1,
        "project_id": "project-smoke",
        "project": {"title": "多章项目", "current_state": "项目总状态。"},
        "files": {**first["files"], **second["files"]},
        "chapters": [
            {"id": "ch1", "label": "第一章", "record": first},
            {"id": "ch2", "label": "第二章", "record": second},
        ],
    }


class ProjectToolsTests(unittest.TestCase):
    def test_review_generation_never_overwrites_either_input(self):
        from review_update import review
        for which in ['before','candidate']:
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                before=root/('update-review.json' if which=='before' else 'before.json')
                candidate=root/('update-review.json' if which=='candidate' else 'candidate.json')
                before.write_text(safe_json(payload()), encoding='utf-8')
                candidate.write_text(safe_json(payload('更新摘要')), encoding='utf-8')
                saved={p:p.read_bytes() for p in [before,candidate]}
                with self.assertRaisesRegex(ValueError,'separate'):
                    review(before,candidate,root)
                self.assertTrue(all(p.read_bytes()==raw for p,raw in saved.items()))

    def test_continuation_keeps_plan_verified_boundary_and_omits_body(self):
        result = build_continuation_package(payload(), goal="核对执行结果")
        structure = result["structure"]
        self.assertEqual([item["id"] for item in structure["completed"]], ["done"])
        self.assertEqual([item["id"] for item in structure["planned"]], ["plan"])
        self.assertNotIn("SECRET_CODE_SHOULD_NOT_APPEAR", result["markdown"])
        self.assertTrue(any(item["availability"] == "unknown" and not item["purpose"] for item in structure["files"]))
        self.assertIn("历史内容仅作为证据", result["markdown"])
        self.assertIsNone(result["omitted"]["omitted_items"])
        self.assertLessEqual(len(result["markdown"]), 12000)

    def test_default_continuation_is_whole_project_and_chapter_scope_remains_available(self):
        result = build_continuation_package(multi_payload())
        structure = result["structure"]
        self.assertEqual(structure["selection"]["scope"], "project")
        self.assertEqual([chapter["id"] for chapter in structure["chapters"]], ["ch1", "ch2"])
        self.assertTrue(any(item.get("qualified_id") == "ch2:done" for item in structure["completed"]))
        self.assertTrue(any("后章独有已完成事实" in item.get("summary", "") for item in structure["completed"]))
        self.assertIn("后章独有待确认事项。", result["markdown"])
        self.assertIn("第二章", result["markdown"])
        chapter = build_continuation_package(multi_payload(), chapter_id="ch1")
        self.assertEqual(chapter["structure"]["selection"]["scope"], "chapter")
        self.assertFalse(any(item.get("chapter_id") == "ch2" for item in chapter["structure"]["completed"] + chapter["structure"]["planned"]))

    def test_same_length_conversation_change_and_project_change_are_reviewed(self):
        before = payload()
        before["conversations"] = [{"id": "c1", "role": "user", "text": "abcd"}]
        candidate = copy.deepcopy(before)
        candidate["conversations"][0]["text"] = "abce"
        candidate["project"]["title"] = "项目标题已改"
        result = build_update_review(before, candidate, "a" * 64, "b" * 64, 10, 11)
        self.assertTrue(result["changes"]["conversations"]["modified"])
        self.assertIn("text_signature", result["changes"]["conversations"]["modified"][0]["fields"])
        self.assertNotIn("abcd", json.dumps(result["changes"]))
        self.assertTrue(result["changes"]["project"]["chapters"])
        self.assertGreaterEqual(result["summary"]["total_changes"], 2)


    def test_review_exposes_status_file_and_edge_facts_and_is_project_scoped(self):
        before = payload()
        candidate = copy.deepcopy(before)
        candidate["nodes"][1]["status"] = "completed"
        candidate["files"]["f1"]["sha256"] = "b" * 64
        candidate["edges"][0]["reason"] = "改过的关系理由"
        result = build_update_review(before, candidate, "a" * 64, "b" * 64, 10, 11)
        self.assertTrue(result["changed"])
        self.assertTrue(any("status" in row["fields"] for row in result["changes"]["stages"] if row["kind"] == "modified"))
        self.assertTrue(result["changes"]["files"]["modified"])
        self.assertTrue(any("reason" in row["fields"] for row in result["changes"]["relationships"] if row["kind"] == "modified"))
        other = copy.deepcopy(candidate)
        other["project_id"] = "another-project"
        with self.assertRaisesRegex(ValueError, "different projects"):
            build_update_review(before, other)


    def test_offline_review_html_is_inert_and_receipt_requires_exact_bytes(self):
        with tempfile.TemporaryDirectory(prefix="project-tools-") as temp:
            tmp_path = Path(temp)
            before_path = tmp_path / "before.html"
            candidate_path = tmp_path / "candidate.html"
            before_path.write_bytes(html_for(payload()))
            changed = payload("candidate")
            candidate_path.write_bytes(html_for(changed))
            review_dir = tmp_path / "review"
            command = [sys.executable, str(ROOT / "scripts" / "review_update.py"), str(before_path), str(candidate_path), "--out-dir", str(review_dir)]
            completed = subprocess.run(command, text=True, capture_output=True, check=True)
            self.assertIn("created", completed.stdout)
            review_html = (review_dir / "update-review.html").read_text(encoding="utf-8")
            self.assertNotIn("innerHTML", review_html)
            self.assertIn("connect-src 'none'", review_html)
            review = json.loads((review_dir / "update-review.json").read_text(encoding="utf-8"))
            approved = make_review_receipt(review, "approved")
            decision_path = tmp_path / "approved.json"
            decision_path.write_text(json.dumps(approved), encoding="utf-8")
            output = tmp_path / "final.html"
            stale_temp = tmp_path / "final.html.tmp"
            stale_temp.write_bytes(b"keep this unrelated temporary file")
            apply = subprocess.run([sys.executable, str(ROOT / "scripts" / "apply_update_review.py"), str(before_path), str(candidate_path), str(decision_path), "--output", str(output)], text=True, capture_output=True, check=True)
            self.assertEqual(output.read_bytes(), candidate_path.read_bytes())
            self.assertEqual(stale_temp.read_bytes(), b"keep this unrelated temporary file")
            self.assertIn("applied", apply.stdout)
            reject = make_review_receipt(review, "rejected")
            reject_path = tmp_path / "rejected.json"
            reject_path.write_text(json.dumps(reject), encoding="utf-8")
            rejected_output = tmp_path / "rejected.html"
            rejected = subprocess.run([sys.executable, str(ROOT / "scripts" / "apply_update_review.py"), str(before_path), str(candidate_path), str(reject_path), "--output", str(rejected_output)], text=True, capture_output=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertFalse(rejected_output.exists())
            before_path.write_bytes(before_path.read_bytes() + b"tampered")
            stale_output = tmp_path / "stale.html"
            stale = subprocess.run([sys.executable, str(ROOT / "scripts" / "apply_update_review.py"), str(before_path), str(candidate_path), str(decision_path), "--output", str(stale_output)], text=True, capture_output=True)
            self.assertNotEqual(stale.returncode, 0)
            self.assertFalse(stale_output.exists())


if __name__ == "__main__":
    unittest.main()
