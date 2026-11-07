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
        decoded = sc.transport.decode(json.loads((self.out / 'reading-map.json').read_bytes()))
        bodies = [e for e in decoded if e['kind']=='message' and e['unit_id']==u['id']]
        self.assertEqual([e['ref'] for e in bodies], ['m1','m2','m3','m4','m5'])
        self.assertEqual(bodies[1]['text'], bodies[3]['text'])
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
        entries=json.loads((self.out/'reading-map.json').read_bytes())['entries']
        self.assertEqual(entries[-1]['phase'],'')
        self.assertTrue(entries[-1]['label'].endswith('助'))

    def append_existing_turn(self):
        self.populate()
        self.doc['messages'].insert(4,message('c3','t1','用户决定暂停上线，先修复备份。'))
        self.write()
        return self.prepare()

    def test_same_turn_append_reuses_base_and_survives_reprepare(self):
        p = self.append_existing_turn()
        self.assertEqual(len(p['deltas']),1)
        uid=p['pending'][0]
        self.assertEqual(p['deltas'][uid]['base_count'],4)
        entries=sc.transport.decode(json.loads((self.out/'reading-map.json').read_bytes()))
        messages=[e for e in entries if e['kind']=='message']
        self.assertEqual([e['ref'] for e in messages],['m5'])
        self.assertTrue(any(e['kind']=='base_summary' for e in entries))
        self.assertEqual(self.prepare()['deltas'],p['deltas'])

    def test_delta_accept_retains_prior_points_and_historical_decision(self):
        p=self.append_existing_turn();uid=p['pending'][0];base=p['deltas'][uid]
        value={'unit_id':uid,'key':p['head']['units'][uid],'kind':'model_summary_delta','base_key':base['base_key'],
               'points':[{'text':'暂停发布，备份仍待修复。','refs':['m5']}],
               'supersedes':[{'point':1,'reason':'新要求暂停发布。','refs':['m5']}]}
        path=self.base/'delta.json';path.write_bytes(sc.canonical([value]))
        sc.accept(self.out/'plan.json',path)
        q=self.prepare();self.assertFalse(q['pending'])
        saved=sc.load_summary(self.cache,sc.get_unit(q,self.cache,uid))
        self.assertEqual(len(saved['points']),2)
        self.assertEqual(saved['points'][0]['text'],base['points'][0]['text'])
        self.assertEqual(saved['points'][0]['superseded']['refs'],['m5'])

    def test_delta_requires_new_evidence_and_matching_base(self):
        p=self.append_existing_turn();uid=p['pending'][0];base=p['deltas'][uid]
        good={'unit_id':uid,'key':p['head']['units'][uid],'kind':'model_summary_delta','base_key':base['base_key'],
              'points':[{'text':'新结论','refs':['m5']}]}
        for bad in [{**good,'base_key':'wrong'}, {**good,'points':[{'text':'旧结论','refs':['m1']}]},
                    {**good,'supersedes':[{'point':1,'reason':'无新证据','refs':['m1']}]},
                    {**good,'supersedes':[{'point':99,'reason':'不存在','refs':['m5']}]}]:
            path=self.base/'bad.json';path.write_bytes(sc.canonical([bad]))
            with self.assertRaises(ValueError):sc.accept(self.out/'plan.json',path)
        self.assertFalse((self.cache/'summaries'/(p['head']['units'][uid]+'.json')).exists())

    def test_edited_or_inserted_old_message_uses_full_turn(self):
        self.append_existing_turn()
        self.doc['messages'][1]['content']='这条旧消息变了。'
        self.write();p=self.prepare();self.assertFalse(p['deltas'])
        decoded=sc.transport.decode(json.loads((self.out/'reading-map.json').read_bytes()))
        self.assertEqual(len([e for e in decoded if e['kind']=='message']),5)

    def test_delta_profile_change_does_not_reuse_old_summary(self):
        self.append_existing_turn()
        p=self.prepare(profile='other-instructions')
        self.assertFalse(p['deltas']);self.assertEqual(len(p['pending']),2)

    def test_lossless_duplicate_bodies_keep_roles_occurrences_and_negation(self):
        body=('发布仍未完成，备份需修复。\n'*20)+'〔同文 B1〕'
        entries=[{'unit_id':'a','ref':'m1','role':'user','text':body},
                 {'unit_id':'b','ref':'m2','role':'assistant','text':body},
                 {'unit_id':'b','ref':'m3','role':'assistant','text':body.replace('未完成','已完成')}]
        pack=sc.transport.encode(entries)
        self.assertEqual(sc.transport.decode(pack),entries)
        self.assertTrue(pack['dictionary'])
        rendered=sc.transport.render(pack)
        self.assertLess(sum(map(len,rendered)),sum(len(e['text']) for e in entries))
        self.assertIn('已完成',rendered[-1])

    def test_repeated_paragraph_retains_changed_surrounding_text(self):
        common='旧方案仍待审核。'*30
        entries=[{'text':'第一次\n\n'+common+'\n\n待办甲'}, {'text':'第二次\n\n'+common+'\n\n待办乙'}]
        packed=sc.transport.encode(entries)
        self.assertEqual(sc.transport.decode(packed),entries)
        self.assertEqual(len(packed['dictionary']),1)

    def test_corrupt_delta_base_is_not_trusted(self):
        p=self.append_existing_turn();uid=p['pending'][0]
        file=self.cache/'units'/(p['deltas'][uid]['base_key']+'.json')
        value=json.loads(file.read_bytes());value['messages'][0]['text']='篡改'
        file.write_bytes(sc.canonical(value))
        with self.assertRaisesRegex(ValueError,'changed'):self.prepare()

    def test_short_aliases_bind_to_exact_plan_without_model_hashes(self):
        p=self.prepare();uid=p['pending'][0];alias=p['head']['aliases'][uid]
        value={'unit_id':alias,'kind':'model_summary','points':[{'text':'待发布。','refs':['m4']}]}
        path=self.base/'short.json';path.write_bytes(sc.canonical([value]))
        with self.assertRaisesRegex(ValueError,'plan-bound'):sc.accept(self.out/'plan.json',path)
        path.write_bytes(sc.canonical({'plan':p['head_sha256'],'summaries':[value]}))
        sc.accept(self.out/'plan.json',path)
        q=self.prepare();self.assertIn(uid,q['reused'])
        self.assertEqual(sc.resolve_unit(p,alias),uid)
        with self.assertRaises(ValueError):sc.resolve_unit(p,'U90000')

    def test_delta_short_alias_still_rejects_explicit_wrong_key(self):
        p=self.append_existing_turn();uid=p['pending'][0]
        value={'unit_id':p['head']['aliases'][uid],'kind':'model_summary_delta','key':'wrong',
               'points':[{'text':'暂停发布。','refs':['m5']}]}
        path=self.base/'short-delta.json';path.write_bytes(sc.canonical({'plan':p['head_sha256'],'summaries':[value]}))
        with self.assertRaises(ValueError):sc.accept(self.out/'plan.json',path)
        del value['key'];path.write_bytes(sc.canonical({'plan':p['head_sha256'],'summaries':[value]}))
        sc.accept(self.out/'plan.json',path)
        q=self.prepare();self.assertFalse(q['pending'])

    def test_old_alias_submission_rejected_after_plan_replaced(self):
        p=self.prepare()
        value={'plan':p['head_sha256'],'summaries':[{'unit_id':'U1','kind':'model_summary',
               'points':[{'text':'旧结论。','refs':['m1']}]}]}
        path=self.base/'old.json';path.write_bytes(sc.canonical(value))
        self.doc['messages'].insert(0,message('new','new-turn','新插入一轮','user','user'))
        self.write();self.prepare()
        with self.assertRaisesRegex(ValueError,'stale or different'):sc.accept(self.out/'plan.json',path)


if __name__ == '__main__': unittest.main()
