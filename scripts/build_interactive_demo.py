#!/usr/bin/env python3
"""Build the fictional full-feature Chat Archify demo with an installed Archify."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


MIN_PYTHON=(3,9)
TESTED_ARCHIFY='2.17.0-dev.1'


def run(label,command,cwd,env=None):
    print(f'\n== {label} ==',flush=True)
    run_env=(env or os.environ).copy()
    run_env['PYTHONDONTWRITEBYTECODE']='1'
    run_env['PYTHONUTF8']='1'
    result=subprocess.run([str(part) for part in command],cwd=str(cwd),text=True,encoding='utf-8',capture_output=True,env=run_env)
    if result.stdout:print(result.stdout,end='' if result.stdout.endswith('\n') else '\n')
    if result.stderr:print(result.stderr,file=sys.stderr,end='' if result.stderr.endswith('\n') else '\n')
    if result.returncode:
        raise RuntimeError(f'{label} failed with exit code {result.returncode}; previous packaged output was not reported as current.')


def check_environment(archify_dir):
    if sys.version_info<MIN_PYTHON:
        raise RuntimeError(f'Python 3.9 or newer is required; found {sys.version.split()[0]}.')
    node=shutil.which('node')
    if not node:
        raise RuntimeError('Node.js 18 or newer is required to run Archify; install it separately and put node on PATH.')
    version=subprocess.run([node,'--version'],text=True,capture_output=True)
    if version.returncode:
        raise RuntimeError('Could not read the Node.js version: '+version.stderr.strip())
    digits=version.stdout.strip().lstrip('v').split('.')
    try:major=int(digits[0])
    except (ValueError,IndexError):raise RuntimeError('Could not parse Node.js version: '+version.stdout.strip())
    if major<18:raise RuntimeError(f'Node.js 18 or newer is required; found {version.stdout.strip()}.')
    if not archify_dir.is_dir() or not (archify_dir/'bin'/'archify.mjs').is_file():
        raise RuntimeError('--archify-dir must be the separately installed Archify skill directory containing bin/archify.mjs.')
    package_json=archify_dir/'package.json'
    installed='unknown'
    if package_json.is_file():
        try:installed=json.loads(package_json.read_text(encoding='utf-8')).get('version','unknown')
        except (OSError,json.JSONDecodeError):pass
    print(f'Python {sys.version.split()[0]} | Node.js {version.stdout.strip()} | Archify {installed}')
    if installed!=TESTED_ARCHIFY:
        print(f'Compatibility note: this integration was tested with Archify {TESTED_ARCHIFY}; recheck node interactions when using another version.',file=sys.stderr)
    return node


def build(archify_dir,out_dir):
    root=Path(__file__).resolve().parent.parent
    example=root/'examples'/'interactive-demo'
    test_dir=root/'tests'
    archify_dir=archify_dir.expanduser().resolve()
    out_dir=out_dir.expanduser().resolve()
    node=check_environment(archify_dir)
    inputs=out_dir/'source'
    inputs.mkdir(parents=True,exist_ok=True)
    shutil.copytree(example,inputs,dirs_exist_ok=True)
    spec=inputs/'workflow-v2.json'
    viewer=inputs/'archify-overview.html'
    manifest=inputs/'manifest.json'
    demo_manifest=json.loads(manifest.read_text(encoding='utf-8'))
    demo_manifest.setdefault('project_id','chat-archify-fictional-reading-plan')
    manifest.write_text(json.dumps(demo_manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    packaged=out_dir/'chat-archify-demo.html'

    with tempfile.TemporaryDirectory(prefix='chat-archify-tmp-',dir=str(out_dir)) as temp_dir:
        archify_env=os.environ.copy()
        archify_env['TEMP']=temp_dir
        archify_env['TMP']=temp_dir
        run('Archify showcase validation',[node,archify_dir/'bin'/'archify.mjs','validate','workflow',spec,'--quality','showcase','--json'],archify_dir,archify_env)
        run('Archify delivery',[node,archify_dir/'bin'/'archify.mjs','deliver','workflow',spec,viewer,'--quality','showcase','--json'],archify_dir,archify_env)
    run('All-route geometry check',[sys.executable,root/'scripts'/'check_routes.py',viewer],root)
    run('Attachment-viewer packaging',[sys.executable,root/'scripts'/'package_interactive.py',manifest,packaged],root)
    run('Portable package and history checks',[sys.executable,test_dir/'test_interactive_package.py','--html',packaged,'--source-dir',inputs,'--viewer',viewer],root)
    run('Pro multi-conversation and snapshot checks',[sys.executable,test_dir/'test_pro_capabilities.py','--source-dir',inputs],root)
    run('Workbench topology and navigation checks',[sys.executable,test_dir/'test_workbench.py'],root)
    run('Credential exclusions',[sys.executable,test_dir/'test_credential_guard.py'],root)
    run('Stable conversation indexing',[sys.executable,test_dir/'test_conversation_identity.py'],root)
    run('Automatic collection and pagination',[node,test_dir/'conversation-collection.cjs'],root)
    run('Collection checkpoint recovery',[node,test_dir/'collection-checkpoint.cjs'],root)
    run('Collection host bridge',[node,test_dir/'collection-host.cjs'],root)
    run('Incremental summary caching',[sys.executable,test_dir/'test_summary_cache.py'],root)
    run('Collection receipt and packaging gate',[sys.executable,test_dir/'test_collection_audit.py'],root)
    run('Local association recovery',[node,test_dir/'conversation-recovery.cjs'],root)
    run('Continuation and review helpers',[sys.executable,test_dir/'test_project_tools.py'],root)
    run('Continuation and review controls',[node,test_dir/'project-tools-smoke.cjs'],root)
    run('Portable navigation smoke test',[node,test_dir/'interactive-navigation.cjs',packaged],root)
    print(f'\nComplete interactive demo: {packaged}',flush=True)
    return packaged


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archify-dir',required=True,type=Path,help='Separately installed Archify skill directory, containing bin/archify.mjs')
    parser.add_argument('--out-dir',required=True,type=Path,help='Directory for copied fictional inputs, Archify viewer, and final HTML')
    args=parser.parse_args()
    try:build(args.archify_dir,args.out_dir)
    except (OSError,RuntimeError,ValueError) as error:
        print(f'Chat Archify demo was not completed: {error}',file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':sys.exit(main())
