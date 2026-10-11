"""Focused smoke checks for stable conversation identity and migration."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from conversation_index import build_conversation_aliases, build_conversation_index, excerpts


def chapter(file_id="conversation-file", source_id="chat", conversation_id=""):
    source = {"id": source_id, "title": "Conversation", "kind": "conversation", "coverage": "excerpt", "locator": "", "file_id": file_id}
    if conversation_id:
        source["conversation_id"] = conversation_id
    return {"id": "overview", "record": {"sources": [source], "nodes": []}}


class ConversationIdentitySmoke(unittest.TestCase):
    def test_move_and_append_preserve_existing_ids(self):
        original = "User: first\n\nAssistant: answer\n"
        before = build_conversation_index([chapter()], {"conversation-file": {"id": "old-file", "text": original}})
        after = build_conversation_index([chapter(file_id="moved-file")], {"moved-file": {"id": "new-file", "text": original + "\nUser: appended\n"}})
        self.assertEqual([item["id"] for item in before], [item["id"] for item in after[:2]])
        self.assertEqual([item["turn_group_id"] for item in before], [item["turn_group_id"] for item in after[:2]])

    def test_plain_numbered_source_fixture_keeps_four_messages_and_three_groups(self):
        text = (ROOT / "examples" / "reading-plan" / "conversation.md").read_text(encoding="utf-8")
        rows = build_conversation_index([chapter(conversation_id="fictional-reading-plan-plain")], {"conversation-file": {"id": "f", "text": text}})
        self.assertEqual(len(rows), 4)
        self.assertEqual(len({row["turn_group_id"] for row in rows}), 3)

    def test_numbered_roles_form_three_local_groups_and_fenced_labels_do_not_split(self):
        text = "1. User: first\n\n2. Assistant: answer\n\n3. User: second\n\n4. User: third\n"
        rows = excerpts(text)
        self.assertEqual(len(rows), 4)
        self.assertEqual(len({row["_group_token"] for row in rows}), 3)
        fenced = "User: outer\n```\nAssistant: fake\n```\nAssistant: answer\n"
        rows = excerpts(fenced)
        self.assertEqual(len(rows), 2)
        self.assertIn("Assistant: fake", rows[0]["text"])
        self.assertEqual(rows[1]["role"], "助手")

    def test_messages_json_and_duplicates_remain_separate(self):
        text = json.dumps({"conversation_id": "chat-wide", "messages": [{"role": "user", "content": "same"}, {"role": "user", "content": "same"}]}, ensure_ascii=False)
        rows = excerpts(text)
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]["message_index"], rows[1]["message_index"])
        indexed = build_conversation_index([chapter()], {"conversation-file": {"id": "f", "text": text}})
        self.assertEqual(len(indexed), 2)
        self.assertNotEqual(indexed[0]["id"], indexed[1]["id"])

    def test_line_range_links_real_entries_but_keeps_source_candidates(self):
        record = chapter()
        record["record"]["nodes"] = [{"id": "node", "title": "Node", "evidence": [{"source": "chat", "locator": "conversation.md L1-L2"}]}]
        text = "User: first\n\nAssistant: answer\n\nUser: other\n"
        entries = build_conversation_index([record], {"conversation-file": {"id": "f", "text": text}})
        node = record["record"]["nodes"][0]
        self.assertEqual(len(node["conversation_entry_ids"]), 1)
        self.assertEqual(len(node["conversation_source_entry_ids"]), len(entries))

    def test_adjacent_inline_messages_do_not_share_a_line_range(self):
        record = chapter()
        record['record']['nodes'] = [{'id':'node','title':'Node','evidence':[{'source':'chat','locator':'L2-L2'}]}]
        entries = build_conversation_index([record], {'conversation-file':{'id':'f','text':'User: question\nAssistant: answer\nUser: next\n'}})
        self.assertEqual([(e['line_start'], e['line_end']) for e in entries], [(1,1),(2,2),(3,3)])
        linked = record['record']['nodes'][0]['conversation_entry_ids']
        self.assertEqual(linked, [entries[1]['id']])

    def test_json_uses_message_positions_instead_of_guessed_body_lines(self):
        record = chapter()
        record['record']['nodes'] = [{'id':'node','title':'Node','evidence':[{'source':'chat','locator':'第 2 条消息'}]}, {'id':'line-node','title':'Line','evidence':[{'source':'chat','locator':'L1-L2'}]}]
        text = json.dumps({'note':'相同正文','messages':[{'role':'user','content':'相同正文'},{'role':'assistant','content':'中文\n换行'}]}, ensure_ascii=True, indent=2)
        entries = build_conversation_index([record], {'conversation-file':{'id':'f','text':text}})
        self.assertTrue(all(e['line_range']=='' and e['line']==0 for e in entries))
        self.assertEqual(record['record']['nodes'][0]['conversation_entry_ids'], [entries[1]['id']])
        self.assertEqual(record['record']['nodes'][1]['conversation_entry_ids'], [])

    def test_original_message_ids_do_not_split_a_locally_paired_turn(self):
        text=json.dumps({'messages':[{'id':'msg1','role':'user','content':'question'},{'id':'msg2','role':'assistant','content':'answer'}]})
        rows=build_conversation_index([chapter()], {'conversation-file':{'id':'f','text':text}})
        self.assertEqual(rows[0]['turn_group_id'], rows[1]['turn_group_id'])
        self.assertTrue(all(e['group_identity_kind']=='local' and not e['turn_id'] for e in rows))
        self.assertEqual([e['message_id'] for e in rows], ['msg1','msg2'])

    def test_specific_turn_and_line_constraints_are_not_broadened_by_task(self):
        from conversation_index import _entry_locator_match
        rows=[{'task_id':'task-a','turn_id':'turn-1','message_id':'msg1','line_start':1,'line_end':1}, {'task_id':'task-a','turn_id':'turn-1','message_id':'msg2','line_start':2,'line_end':2}, {'task_id':'task-a','turn_id':'turn-2','message_id':'msg3','line_start':3,'line_end':3}]
        locator='Task ID: task-a; Turn ID: turn-1'
        self.assertEqual([_entry_locator_match(e,locator,rows) for e in rows], [True,True,False])
        self.assertEqual([_entry_locator_match(e,locator+'; L2-L2',rows) for e in rows], [False,True,False])
        self.assertEqual([_entry_locator_match(e,'task-a turn-1 msg2',rows) for e in rows], [False,True,False])

    def test_appending_a_repeated_question_keeps_known_identity_aliases(self):
        before=build_conversation_index([chapter()], {'conversation-file':{'id':'f','text':'User: continue\nAssistant: one\n'}})
        after=build_conversation_index([chapter()], {'conversation-file':{'id':'f','text':'User: continue\nAssistant: one\nUser: continue\nAssistant: two\n'}})
        groups, aliases=build_conversation_aliases({'conversations':before},after)
        self.assertEqual(aliases, {entry['id']:entry['id'] for entry in before})
        self.assertEqual(groups[before[0]['turn_group_id']], before[0]['turn_group_id'])

    def test_same_original_messages_shared_across_chapters_are_not_duplicated(self):
        first=chapter(); second=chapter(source_id='other-view'); second['id']='detail'
        text=json.dumps({'messages':[{'task_id':'task-a','turn_id':'turn-a','message_id':'m1','role':'user','content':'question'}, {'task_id':'task-a','turn_id':'turn-a','message_id':'m2','role':'assistant','content':'answer'}]})
        rows=build_conversation_index([first,second], {'conversation-file':{'id':'f','text':text}})
        self.assertEqual(len(rows),2)
        self.assertEqual(first['record']['sources'][0]['conversation_entry_ids'],second['record']['sources'][0]['conversation_entry_ids'])

    def test_export_headers_do_not_become_body_or_hide_assistant_role(self):
        text='## 2026-01-01T10:00 · 助手交付陈述\n任务：公开示例标题\n任务 ID: task-a\n轮次 ID: turn-a\n消息 ID: msg-a\n\n回答正文\n```\nTask ID: code-example\n```\n'
        rows=excerpts(text)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['role'],'助手')
        self.assertEqual(rows[0]['task_id'],'task-a')
        self.assertNotIn('公开示例标题',rows[0]['text'])
        self.assertIn('Task ID: code-example',rows[0]['text'])

    def test_aliases_prioritize_original_ids_and_require_exact_local_content(self):
        previous = {"conversations": [{"id": "old-entry", "source_identity": "conversation:one", "task_id": "task", "turn_id": "turn", "message_id": "message", "role": "用户", "text": "changed later", "turn_group_id": "old-group"}]}
        current = [{"id": "new-entry", "source_identity": "conversation:one", "task_id": "task", "turn_id": "turn", "message_id": "message", "role": "用户", "text": "new body", "turn_group_id": "new-group"}]
        groups, entries = build_conversation_aliases(previous, current)
        self.assertEqual(entries, {"old-entry": "new-entry"})
        self.assertEqual(groups, {"old-group": "new-group"})
        previous = {"conversations": [{"id": "local-old", "source_title": "Conversation", "role": "用户", "text": "same", "turn_group_id": "old-local"}]}
        current = [{"id": "local-new", "source_identity": "source:chat", "role": "用户", "text": "edited", "turn_group_id": "new-local"}]
        groups, entries = build_conversation_aliases(previous, current)
        self.assertEqual(groups, {})
        self.assertEqual(entries, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
