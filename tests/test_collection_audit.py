"""Collection receipts must not turn omissions or tampering into completeness."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from collection_audit import write_export, validate_receipt, validate_package_collection


def collected_state():
    script = """const c=require(process.argv[1]);(async()=>{
const s=c.createState({projectIds:['project-a']});
await c.collect({state:s,maxCalls:10,save:async()=>{},
listThreads:async a=>({threads:a.archived?[]:[{id:'task-a',title:'Example',projectId:'project-a'}],nextCursor:null}),
readThread:async a=>({thread:{id:'task-a',title:'Example'},page:{order:'newest_first',hasMore:!a.cursor,nextCursor:a.cursor?null:'older'},turns:[{id:a.cursor?'turn-old':'turn-new',startedAt:1700000000,items:[{type:'userMessage',id:a.cursor?'msg_old':'msg_new',content:[{type:'text',text:a.cursor?'Earlier question':'Later question'}]}]}]})});
process.stdout.write(JSON.stringify(s));})();"""
    run = subprocess.run(['node', '-e', script, str(ROOT / 'scripts/collect_conversations.cjs')], capture_output=True, encoding='utf-8', check=True)
    return json.loads(run.stdout)


class CollectionAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = collected_state()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.state = copy.deepcopy(self.baseline)

    def export(self):
        source = self.base / 'input.json'
        source.write_text(json.dumps(self.state), encoding='utf-8')
        return write_export(source, self.base / 'archive')

    def packaged(self, receipt):
        files, sources = {}, []
        for i, item in enumerate(receipt['sources']):
            if item['path'] is None: continue
            key = 'file_' + str(i)
            files[key] = {'id': key, 'path': str((self.base/'archive'/item['path']).resolve()), 'sha256':item['sha256'],'status':'embedded'}
            sources.append({'kind':'conversation','file_id':key})
        return [{'record':{'sources':sources}}], files

    def test_complete_receipt_and_packaged_sources(self):
        path, value = self.export()
        self.assertEqual(validate_receipt(path)['audit']['status'], 'complete')
        chapter, files = self.packaged(value)
        actual = validate_package_collection({'collection_policy':'required','collection_audit':str(path)}, self.base, chapter, files)
        self.assertEqual(actual['status'], 'complete')
        messages = json.loads((path.parent/value['sources'][0]['path']).read_bytes())['messages']
        self.assertEqual([m['turn_id'] for m in messages], ['turn-old','turn-new'])

    def test_changed_state_or_claimed_audit_rejected(self):
        path, value = self.export()
        value['audit']['counts']['messages'] += 1
        path.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'differs'): validate_receipt(path)
        path, value = self.export()
        (path.parent/'collection-state.json').write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'changed'): validate_receipt(path)

    def test_modified_or_missing_export_rejected(self):
        path, value = self.export()
        target=path.parent/value['sources'][0]['path']
        target.write_text('{"messages":[]}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'differs'): validate_receipt(path)
        target.unlink()
        with self.assertRaises(FileNotFoundError): validate_receipt(path)

    def test_missing_packaged_conversation_rejected(self):
        path, value = self.export()
        chapter, files = self.packaged(value)
        chapter[0]['record']['sources']=[]
        with self.assertRaisesRegex(ValueError, 'missing'): validate_package_collection({'collection_policy':'required','collection_audit':str(path)}, self.base, chapter, files)

    def test_pending_collection_even_partial_policy_is_rejected(self):
        self.state['threads']['task-a']['status']='pending'
        path,value=self.export()
        chapter,files=self.packaged(value)
        with self.assertRaisesRegex(ValueError,'pending'): validate_package_collection({'collection_policy':'allow_partial','collection_audit':str(path)}, self.base, chapter, files)

    def test_blocked_collection_requires_explicit_partial_policy(self):
        self.state['threads']['task-a']['status']='blocked'
        path,value=self.export()
        chapter,files=self.packaged(value)
        manifest={'collection_policy':'required','collection_audit':str(path)}
        with self.assertRaisesRegex(ValueError,'incomplete'): validate_package_collection(manifest,self.base,chapter,files)
        manifest['collection_policy']='allow_partial'
        self.assertEqual(validate_package_collection(manifest,self.base,chapter,files)['status'],'partial')

    def test_legacy_not_audited_and_required_needs_receipt(self):
        self.assertEqual(validate_package_collection({},self.base,[],{})['status'],'not_audited')
        with self.assertRaises(ValueError): validate_package_collection({'collection_policy':'required'},self.base,[],{})

    def test_deleting_saved_message_cannot_claim_complete(self):
        self.state['threads']['task-a']['messages'].pop()
        path,value=self.export()
        self.assertEqual(value['audit']['status'],'partial')
        self.assertIn('missing_saved_message',{g['reason'] for g in value['audit']['gaps']})
        chapter, files = self.packaged(value)
        with self.assertRaisesRegex(ValueError,'inconsistent'):
            validate_package_collection({'collection_policy':'allow_partial','collection_audit':str(path)},self.base,chapter,files)

    def test_raw_multiline_credential_is_rejected_before_export(self):
        self.state['threads']['task-a']['messages'][0]['content']='Header\n-----BEGIN PRIVATE KEY-----\nsynthetic'
        with self.assertRaisesRegex(ValueError,'Credential'): self.export()


if __name__=='__main__': unittest.main(verbosity=2)
