"""Export and verify resumable public-message collections with a fail-closed receipt.

The receipt checks local pagination/export consistency, not provider authenticity.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from credential_guard import content_credential_reason

ROOT = Path(__file__).resolve().parent


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def derive(state):
    node = shutil.which('node')
    if not node:
        raise ValueError('Collection verification requires Node.js; cannot claim completeness without it')
    code = "const fs=require('fs'),core=require(process.argv[1]);const s=JSON.parse(fs.readFileSync(0,'utf8'));process.stdout.write(JSON.stringify({audit:core.audit(s),exports:core.exportsForThreads(s)}));"
    run = subprocess.run([node, '-e', code, str(ROOT / 'collect_conversations.cjs')],
                         input=json.dumps(state, ensure_ascii=False), capture_output=True,
                         encoding='utf-8', timeout=60)
    if run.returncode:
        raise ValueError('Invalid collector state; pagination cannot be verified')
    value = json.loads(run.stdout)
    # Check original strings before JSON escaping; never print offending values.
    def inspect(item):
        if isinstance(item, str) and content_credential_reason(item):
            raise ValueError('Credential-like content remains in collector state; export refused')
        if isinstance(item, dict):
            for key, child in item.items():
                inspect(key)
                inspect(child)
        elif isinstance(item, list):
            for child in item:
                inspect(child)
    inspect(state)
    inspect(value)
    return value


def write_export(state_path, output_dir):
    state_path, output_dir = Path(state_path).resolve(), Path(output_dir).resolve()
    state_raw = state_path.read_bytes()
    state = json.loads(state_raw)
    derived = derive(state)
    output_dir.mkdir(parents=True, exist_ok=True)
    # Copy only validated, already filtered state. Never mutate the resumed input.
    frozen = output_dir / 'collection-state.json'
    frozen.write_bytes(state_raw)
    sources = []
    for thread_id, export in derived['exports'].items():
        if not export['messages']:
            sources.append({'thread_id': thread_id, 'path': None, 'messages': 0,
                            'sha256': None, 'read_status': export['source']['read_status']})
            continue
        filename = 'sources/conversation-' + digest(thread_id.encode())[:20] + '.json'
        target = output_dir / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = canonical(export)
        target.write_bytes(raw)
        sources.append({'thread_id': thread_id, 'path': filename, 'messages': len(export['messages']),
                        'sha256': digest(raw), 'read_status': export['source']['read_status']})
    receipt = {'schema_version': 1, 'state_path': frozen.name, 'state_sha256': digest(state_raw),
               'scope': state['scope'], 'audit': derived['audit'], 'sources': sources,
               'assurance': 'Local pagination and export consistency; not independent provider authentication'}
    path = output_dir / 'collection-receipt.json'
    path.write_bytes(canonical(receipt))
    lines = ['# 对话采集检查', '', f"结果：{derived['audit']['status']}", '',
             '此回执检查分页链与本地导出的一致性，不证明工具未返回的历史不存在。', '',
             '| 对话 | 读取状态 | 已导出消息 |', '| --- | --- | ---: |']
    for item in sources:
        title = derived['exports'][item['thread_id']]['source']['title'].replace('|', '\\|').replace('\n', ' ')
        lines.append(f"| {title or item['thread_id']} | {item['read_status']} | {item['messages']} |")
    lines.extend(['', '## 尚未覆盖或过滤的内容', ''])
    gaps = derived['audit'].get('gaps', [])
    if not gaps:
        lines.append('没有检测到分页、正文或过滤缺口。')
    for gap in gaps:
        lines.append('- ' + ' · '.join(str(gap.get(key, '')) for key in ['thread_id', 'reason', 'turn_id', 'message_id'] if gap.get(key)))
    (output_dir / 'source-audit.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path, receipt


def local_receipt_path(base, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError('Receipt files must use relative local paths')
    path = (base / relative).resolve()
    if not path.is_relative_to(base.resolve()):
        raise ValueError('Receipt files must stay within the collection directory')
    return path


def validate_receipt(path):
    path = Path(path).resolve()
    receipt = json.loads(path.read_bytes())
    if receipt.get('schema_version') != 1:
        raise ValueError('Unsupported collection receipt')
    raw = local_receipt_path(path.parent, receipt.get('state_path')).read_bytes()
    if digest(raw) != receipt.get('state_sha256'):
        raise ValueError('Collection state changed after export')
    state = json.loads(raw)
    derived = derive(state)
    if receipt.get('audit') != derived['audit'] or receipt.get('scope') != state['scope']:
        raise ValueError('Collection result differs from the verified pagination state')
    integrity_errors = {'invalid_page_chain','invalid_item_receipt','unaccounted_message','missing_saved_message',
                        'missing_excluded_record','unaccounted_excluded_record','unaccounted_candidate',
                        'invalid_excluded_candidate','missing_explicit_thread','unaccounted_included_thread',
                        'missing_or_invalid_stream'}
    if any(gap.get('reason') in integrity_errors for gap in derived['audit'].get('gaps', [])):
        raise ValueError('Collection state has inconsistent pagination or saved-message records')
    sources = receipt.get('sources')
    if not isinstance(sources, list) or len(sources) != len(derived['exports']):
        raise ValueError('Collection source inventory differs from the state')
    seen = set()
    for source in sources:
        thread_id = source.get('thread_id')
        if thread_id in seen or thread_id not in derived['exports']:
            raise ValueError('Duplicate or unknown source in collection receipt')
        seen.add(thread_id)
        expected = derived['exports'][thread_id]
        if source.get('messages') != len(expected['messages']) or source.get('read_status') != expected['source']['read_status']:
            raise ValueError('Collection message counts changed')
        if not expected['messages']:
            if source.get('path') is not None or source.get('sha256') is not None:
                raise ValueError('Empty collection cannot invent a transcript')
            continue
        raw = local_receipt_path(path.parent, source.get('path')).read_bytes()
        if digest(raw) != source.get('sha256') or json.loads(raw) != expected:
            raise ValueError('Conversation export differs from the verified collection')
    if seen != set(derived['exports']):
        raise ValueError('A collected conversation is absent from the receipt')
    return receipt


def validate_package_collection(manifest, base, chapters, files):
    policy, reference = manifest.get('collection_policy'), manifest.get('collection_audit')
    if policy is None and reference is None:
        return {'status': 'not_audited', 'note': 'Legacy or manually supplied sources; automatic collection completeness not checked'}
    if policy not in {'required', 'allow_partial'} or not isinstance(reference, str) or not reference:
        raise ValueError('collection_policy requires a collection_audit receipt and required/allow_partial policy')
    path = (base / reference).resolve()
    receipt = validate_receipt(path)
    audit = receipt['audit']
    if audit['status'] == 'in_progress':
        raise ValueError('Conversation collection still has pending pages; resume it before packaging')
    if audit['status'] != 'complete' and policy != 'allow_partial':
        raise ValueError('Conversation collection is incomplete; resolve gaps or explicitly use allow_partial')
    declared = {source.get('file_id') for chapter in chapters for source in chapter['record']['sources']
                if source.get('kind') == 'conversation'}
    for source in receipt['sources']:
        if source['path'] is None:
            continue
        target = str(local_receipt_path(path.parent, source['path']))
        matches = [file for file in files.values() if file.get('path') == target]
        if len(matches) != 1 or matches[0]['id'] not in declared:
            raise ValueError('A collected conversation is missing from the packaged conversation sources')
        file = matches[0]
        if file.get('status') != 'embedded' or file.get('sha256') != source['sha256']:
            raise ValueError('A collected conversation was excluded or changed during packaging')
    return {'status': audit['status'], 'policy': policy, 'audit': audit,
            'receipt_sha256': digest(path.read_bytes()), 'assurance': receipt['assurance']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    export = sub.add_parser('export')
    export.add_argument('state', type=Path)
    export.add_argument('--out-dir', type=Path, required=True)
    check = sub.add_parser('check')
    check.add_argument('receipt', type=Path)
    args = parser.parse_args()
    if args.command == 'export':
        path, result = write_export(args.state, args.out_dir)
    else:
        path, result = args.receipt, validate_receipt(args.receipt)
    summary = {key: value for key, value in result['audit'].items() if key not in {'gaps','warnings'}}
    summary['gaps'] = len(result['audit'].get('gaps', []))
    summary['warnings'] = len(result['audit'].get('warnings', []))
    print(json.dumps({'receipt': str(path), 'audit': summary}, ensure_ascii=False))
