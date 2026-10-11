#!/usr/bin/env python3
"""Build the bundled plain-text conversation without original application IDs."""
import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from build_interactive_demo import check_environment, run


def build(archify_dir, out_dir):
    root = Path(__file__).resolve().parents[1]
    archify_dir, out_dir = archify_dir.resolve(), out_dir.resolve()
    node = check_environment(archify_dir)
    source = out_dir / 'source'
    source.mkdir(parents=True, exist_ok=True)
    shutil.copytree(root / 'examples/reading-plan', source, dirs_exist_ok=True)
    spec, viewer = source / 'workflow-v2.json', source / 'archify-overview.html'
    with tempfile.TemporaryDirectory(prefix='plain-chat-build-', dir=str(out_dir)) as temp:
        env = os.environ.copy()
        env.update(TEMP=temp, TMP=temp)
        run('Plain conversation showcase', [node, archify_dir / 'bin/archify.mjs',
            'validate', 'workflow', spec, '--quality', 'showcase', '--json'], archify_dir, env)
        run('Plain conversation diagram', [node, archify_dir / 'bin/archify.mjs',
            'deliver', 'workflow', spec, viewer, '--quality', 'showcase', '--json'], archify_dir, env)
    run('Plain conversation all-route geometry', [sys.executable, root / 'scripts/check_routes.py', viewer], root)
    output = out_dir / 'plain-conversation.html'
    run('Plain conversation package', [sys.executable, root / 'scripts/package_interactive.py',
        source / 'manifest.json', output], root)
    payload = json.loads(re.search(r'id="explorer-data">(.*?)</script>',
        output.read_text(encoding='utf-8'), re.S)[1])
    entries = payload['conversations']
    assert len(entries) == 4 and len({e['turn_group_id'] for e in entries}) == 3
    assert all(not e['task_id'] and not e['turn_id'] and not e['message_id'] for e in entries)
    assert all(n['conversation_entry_ids'] for n in payload['chapters'][0]['record']['nodes'])
    assert all(not n['artifacts'] for n in payload['chapters'][0]['record']['nodes'])
    run('Plain conversation reading', [node, root / 'tests/interactive-navigation.cjs',
        output, '--all-data'], root)
    print(json.dumps({'output': str(output), 'messages': 4, 'local_turns': 3,
        'original_application_ids': 'absent; not fabricated'}, ensure_ascii=False))
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archify-dir', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    build(args.archify_dir, args.out_dir)
