import copy
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import summary_cache as sc


def message(mid, turn, text, role='assistant', phase='commentary'):
    return {'message_id': mid, 'turn_id': turn, 'content': text, 'role': role, 'phase': phase}


class SummaryCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.source = self.base / 'source.json'
        self.cache = self.base / 'cache'
        self.out = self.base / 'out'
        self.doc = {'source': {'thread_id': 'thread-a', 'title': 'Example'}, 'messages': [
            message('u1', 't1', '实现保存。', 'user', 'user'),
            message('c1', 't1', '正在整理相关内容。'),
            message('c2', 't1', '本地测试失败，决定改用云端保存。'),
            message('a1', 't1', '已提交保存方案，尚未部署。', phase='final_answer'),
            message('u2', 't2', '增加导出。', 'user', 'user'),
            message('a2', 't2', '导出功能已完成。', phase='final_answer')]}
        self.write()

    def write(self):
        self.source.write_bytes(sc.canonical(self.doc))

    def prepare(self, **kwargs):
        return sc.prepare(None, [self.source], self.cache, self.out, **kwargs)

    def summaries(self, plan):
        values = []
        for uid in plan['pending']:
            u = sc.get_unit(plan, self.cache, uid)
            values.append({'unit_id': uid, 'key': u['key'], 'kind': 'model_summary',
                           'points': [{'text': '测试摘要，只用于验证缓存协议。', 'refs': [u['messages'][0]['ref']]}],
                           'reviewed_omitted_refs': [m['ref'] for m in u['omitted']]})
        path = self.base / 'summaries.json'
        path.write_bytes(sc.canonical(values))
        return path

    def populate(self):
        p = self.prepare()
        sc.accept(self.out / 'plan.json', self.summaries(p))
        return p

    def test_original_byte_preservation_and_risk_messages(self):
        before = self.source.read_bytes()
        p = self.prepare()
        self.assertEqual((self.cache / p['head']['originals'][0]['archive']).read_bytes(), before)
        self.assertEqual(self.source.read_bytes(), before)
        u = sc.get_unit(p, self.cache, p['pending'][0])
        self.assertEqual(u['omitted'], [])
        self.assertIn('c2', [m['original_ref'] for m in u['selected']])

    def test_unchanged_run_has_no_model_input(self):
        self.populate()
        p = self.prepare()
        self.assertEqual(len(p['reused']), 2)
        self.assertFalse(p['pending'])
        self.assertEqual((self.out / 'reading-pack.md').read_bytes(), b'')

    def test_append_only_new_turn_and_old_context(self):
        self.populate()
        self.doc['messages'].append(message('u3', 't3', '撤回保存方案。', 'user', 'user'))
        self.write(); p = self.prepare()
        self.assertEqual(len(p['pending']), 1)
        self.assertEqual(len(p['context']), 2)
        self.assertEqual(len(p['reused']), 2)

    def test_edit_invalidates_only_affected_turn(self):
        self.populate()
        self.doc['messages'][0]['content'] = '改用文件保存。'
        self.write(); p = self.prepare()
        self.assertEqual((len(p['pending']), len(p['reused'])), (1, 1))

    def test_old_turn_insert_preserves_native_id_cache(self):
        self.populate()
        self.doc['messages'].insert(0, message('older', 'older-turn', '之前的需求。', 'user', 'user'))
        self.write(); p = self.prepare()
        self.assertEqual((len(p['pending']), len(p['reused'])), (1, 2))

    def test_removed_units_reported_not_deleted(self):
        p = self.populate()
        self.doc['messages'] = self.doc['messages'][:4]
        self.write(); q = self.prepare()
        self.assertEqual(len(q['removed']), 1)
        self.assertIn('reconciliation_required', q)
        self.assertEqual(len(list((self.cache / 'summaries').glob('*.json'))), 2)

    def test_profile_and_policy_invalidate(self):
        self.populate()
        self.assertEqual(len(self.prepare(profile='new-model-or-instruction')['pending']), 2)

    def test_prompt_and_selection_rule_changes_invalidate(self):
        self.populate()
        with patch.object(sc, 'PROMPT', sc.PROMPT + '新的摘要约束。'):
            self.assertEqual(len(self.prepare()['pending']), 2)
        with patch.object(sc, 'POLICY', 'new-selection-version'):
            self.assertEqual(len(self.prepare()['pending']), 2)

    def test_stale_submission_rejected(self):
        p = self.prepare(); summaries = self.summaries(p)
        self.doc['messages'][0]['content'] = '需求已改变。'; self.write()
        with self.assertRaisesRegex(ValueError, 'changed'): sc.accept(self.out / 'plan.json', summaries)

    def test_invalid_reference_rejects_whole_batch(self):
        p = self.prepare(); path = self.summaries(p)
        values = json.loads(path.read_bytes()); values[-1]['points'][0]['refs'] = ['invented']
        path.write_bytes(sc.canonical(values))
        with self.assertRaisesRegex(ValueError, 'unknown'): sc.accept(self.out / 'plan.json', path)
        self.assertFalse((self.cache / 'summaries').exists())

    def test_cache_tampering_rejected(self):
        self.populate()
        path = next((self.cache / 'summaries').glob('*.json'))
        v = json.loads(path.read_bytes()); v['summary']['points'][0]['text'] = 'tampered'
        path.write_bytes(sc.canonical(v))
        with self.assertRaisesRegex(ValueError, 'checksum'): self.prepare()

    def test_partial_and_unknown_phases_not_dropped(self):
        self.doc['messages'][1]['partial'] = True
        self.doc['messages'][-1]['phase'] = ''
        self.write(); p = self.prepare()
        self.assertEqual(p['counts']['omitted_messages'], 0)

    def test_no_final_preserves_all(self):
        for m in self.doc['messages']: m['phase'] = 'user' if m['role'] == 'user' else 'commentary'
        self.write(); p = self.prepare()
        self.assertEqual(p['counts']['omitted_messages'], 0)

    def test_causes_metrics_and_visibility_rules_survive(self):
        for text in ['原因是箭头与背景同色。', '压缩后为738 KB。', '内容分为公开结果和个人结果。',
                     '最低对比度为7.73:1。', '服务端核验身份。']:
            m={'ref':'m1','text':text,'role':'assistant','phase':'commentary','partial':False,'pinned':False}
            final={**m,'ref':'m2','phase':'final_answer','text':'已完成。'}
            self.assertIn(m,sc.select_messages([m,final])[0])

    def test_novel_resource_preserved(self):
        m={'ref':'m1','text':'产出 docs/decision.md。','role':'assistant','phase':'commentary','partial':False,'pinned':False}
        final={**m,'ref':'m2','phase':'final_answer','text':'已完成。'}
        self.assertIn(m,sc.select_messages([m,final])[0])

    def test_non_keyword_decisions_failures_and_open_work_survive(self):
        # Synthetic regressions for omissions found in the project focus review.
        for text in ['启动受残留 socket 影响，数据卷还在。',
                     '只交付文档，业务实现留待下一阶段。',
                     '开发工具的依赖声明只兼容上一主版本，现已锁定兼容版本。',
                     '甲和甲的大写形式允许共存，相同拼写不行。',
                     '计时归零继续等待，后续提交仍然有效。',
                     'This is only a local preview; deployment is still outstanding.',
                     '正在整理相关内容。']:
            self.doc['messages'][1]['content'] = text
            self.write(); p = self.prepare()
            u = sc.get_unit(p, self.cache, p['pending'][0])
            self.assertIn(text, [m['text'] for m in u['selected']])

    def test_only_identical_commentary_deduped_with_ordered_reference(self):
        original = copy.deepcopy(self.doc['messages'][1])
        original['message_id'] = 'c3'
        self.doc['messages'].insert(3, original)
        self.write(); p = self.prepare()
        u = sc.get_unit(p, self.cache, p['pending'][0])
        self.assertEqual([m['original_ref'] for m in u['omitted']], ['c3'])
        reading = (self.out / 'reading-pack.md').read_text(encoding='utf-8')
        self.assertIn('[m4 assistant] 与 m2 正文完全相同', reading)
        self.assertLess(reading.index('[m3 assistant]'), reading.index('[m4 assistant]'))
        self.assertEqual(len(u['messages']), 5)

    def test_similar_text_and_repeated_questions_are_not_deduped(self):
        self.doc['messages'].insert(2, message('c3','t1','正在整理相关内容。 '))
        self.doc['messages'].insert(3, message('u3','t1','实现保存。','user','user'))
        self.write(); self.assertEqual(self.prepare()['counts']['omitted_messages'], 0)

    def test_partial_and_pinned_duplicate_stays_visible(self):
        m={'ref':'m1','text':'相同内容','role':'assistant','phase':'commentary','partial':False,'pinned':False}
        final={**m,'ref':'m4','phase':'final_answer','text':'完成'}
        for flag in ['partial','pinned']:
            selected, omitted = sc.select_messages([m,{**m,'ref':'m2',flag:True},final])
            self.assertFalse(omitted)

    def test_pins_preserved_and_unknown_pin_rejected(self):
        pin = {'thread_id': 'thread-a', 'turn_id': 't1', 'content_sha256': sc.sha(self.doc['messages'][1]['content'].encode())}
        p = self.prepare(pins=[pin]); self.assertEqual(p['counts']['omitted_messages'], 0)
        pin['content_sha256'] = 'missing'
        with self.assertRaisesRegex(ValueError, 'Pinned'): self.prepare(pins=[pin])

    def test_credentials_and_hidden_messages_rejected(self):
        self.doc['messages'][0]['content'] = 'password="real-credential-value-123"'
        self.write()
        with self.assertRaisesRegex(ValueError, 'Credential'): self.prepare()
        self.doc['messages'][0]['content'] = 'safe'; self.doc['messages'][0]['reasoning'] = 'hidden'
        self.write()
        with self.assertRaisesRegex(ValueError, 'public message fields'): self.prepare()

    def test_duplicate_identity_and_cross_source_cache_rejected(self):
        self.doc['messages'].append(copy.deepcopy(self.doc['messages'][0])); self.write()
        with self.assertRaisesRegex(ValueError, 'Duplicate'): self.prepare()
        self.doc['messages'].pop(); self.doc['source']['thread_id'] = 'unrelated'; self.write()
        with self.assertRaisesRegex(ValueError, 'Cached object'): self.prepare()

    def test_public_plain_conversation_without_native_ids(self):
        self.doc = {'source': {'conversation_id': 'plain'}, 'messages': [
            {'role': 'user', 'content': '制定阅读计划'}, {'role': 'assistant', 'content': '每天阅读一章'}]}
        self.write(); p = self.prepare()
        self.assertEqual(p['counts']['turns'], 1)
        u = sc.get_unit(p, self.cache, p['pending'][0])
        self.assertEqual(u['messages'][0]['original_ref'], 'local-message-1')
        self.assertFalse(u['omitted'])


if __name__ == '__main__': unittest.main()
