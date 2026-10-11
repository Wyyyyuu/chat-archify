#!/usr/bin/env python3
"""Verify multi-conversation/chapter packaging and explicit snapshot reuse."""
import argparse
import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from package_interactive import package
from test_interactive_package import read_payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-dir', type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='chat-archify-pro-') as temp:
        work = Path(temp)
        shutil.copytree(args.source_dir, work / 'source')
        source = work / 'source'
        record = json.loads((source / 'evolution.json').read_text(encoding='utf-8'))
        first = next(s for s in record['sources'] if s['kind'] == 'conversation')
        second = copy.deepcopy(first)
        second.update(id='second-chat', title='第二个虚构对话', uri='second-conversation.md')
        second['locator'] = second['locator'].replace('11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222')
        transcript = (source / 'conversation.md').read_text(encoding='utf-8').replace('11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222')
        (source / second['uri']).write_text(transcript, encoding='utf-8')
        record['sources'].append(second)
        evidence = copy.deepcopy(record['nodes'][0]['evidence'][0])
        evidence['source'] = second['id']
        record['nodes'][0]['evidence'].append(evidence)
        record['revisions'].append('测试：新增第二个虚构对话来源。')
        (source / 'multi-record.json').write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
        manifest = {'title': 'Pro 多对话与多章节回归', 'project_id':'pro-capabilities-identity', 'chapters': [
            {'id': 'overview', 'label': '总览', 'record': 'multi-record.json', 'viewer': 'archify-overview.html'},
            {'id': 'detail', 'label': '同一事实的专题视图', 'record': 'multi-record.json', 'viewer': 'archify-overview.html'}]}
        manifest_path = source / 'multi-manifest.json'
        for invalid_id in [None,42,{},'', 'has spaces']:
            invalid_manifest={**manifest,'project_id':invalid_id}
            manifest_path.write_text(json.dumps(invalid_manifest,ensure_ascii=False),encoding='utf-8')
            try:package(manifest_path,work/'invalid.html')
            except ValueError as error:assert 'project_id' in str(error)
            else:raise AssertionError('Invalid project identity must be rejected before packaging')
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
        original = work / 'original.html'
        package(manifest_path, original)
        payload = read_payload(original)
        assert payload['project_id']==manifest['project_id']
        assert len(payload['chapters']) == 2
        assert {x['task_id'] for x in payload['conversations']} == {'11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222'}
        assert all(len(c['record']['nodes']) == 5 and len(c['record']['edges']) == 5 for c in payload['chapters'])
        assert all(f['status'] == 'embedded' for f in payload['files'].values())
        before = {f['path']: f['sha256'] for f in payload['files'].values()}
        changed = source / 'resources' / 'reading-plan.md'
        changed.write_text('# New current bytes\nSnapshot reuse must retain the old version.\n', encoding='utf-8')
        preserved = work / 'preserved.html'
        manifest['title']='重命名后的 Pro 项目'
        manifest_path.write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
        package(manifest_path, preserved, snapshot_from=original)
        assert read_payload(preserved)['project_id']==payload['project_id'], 'Renaming an updated page preserves the association identity'
        assert {f['path']: f['sha256'] for f in read_payload(preserved)['files'].values()} == before
        relocated=work/'relocated'
        shutil.copytree(source,relocated)
        moved=work/'moved.html'
        package(relocated/'multi-manifest.json',moved,snapshot_from=original)
        assert read_payload(moved)['files']==payload['files'], 'Moved records retain the archived IDs, paths and bytes'
        assert read_payload(moved)['project_id']==payload['project_id'], 'Moving records preserves the association identity'
        refreshed = work / 'refreshed.html'
        package(manifest_path, refreshed)
        after = {f['path']: f['sha256'] for f in read_payload(refreshed)['files'].values()}
        assert after[str(changed.resolve())] != before[str(changed.resolve())]
        print(json.dumps({'status': 'passed', 'checks': ['two chapters retain all nodes and edges', 'two conversation tasks indexed', 'all four artifacts embedded', 'snapshot reuse preserves previous file hashes', 'relocated records preserve archived IDs and bytes', 'explicit regeneration reads current bytes']}))


if __name__ == '__main__':
    main()
