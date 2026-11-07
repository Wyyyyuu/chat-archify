#!/usr/bin/env python3
"""Combine checked Archify viewers, evolution records and local attachments offline."""
import argparse
import base64
import copy
import hashlib
import html
import json
import mimetypes
import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit
from html.parser import HTMLParser
from render import validate
from check_routes import audit_file
from conversation_index import build_conversation_aliases, build_conversation_index
from workbench_data import vertical_layout, validate_groups, navigation_data, initial_target
from credential_guard import credential_reason, decode_text
from collection_audit import validate_package_collection


def encode(data):
    return base64.b64encode(data).decode('ascii')


def local_path(uri, base):
    if re.match(r'^[A-Za-z]:[\\/]', uri):
        return Path(uri).resolve()
    parsed=urlsplit(uri)
    if parsed.scheme=='file':
        raw=unquote(parsed.path)
        if re.match(r'^/[A-Za-z]:/',raw):raw=raw[1:]
        return Path(raw).resolve()
    if parsed.scheme or uri.startswith('#'):return None
    return (base/uri).resolve()


class ViewerTopologyParser(HTMLParser):
    """Read public SVG data attributes without depending on Archify node IDs."""
    def __init__(self):
        super().__init__()
        self.nodes={}
        self.edges=[]

    def handle_starttag(self,tag,attributes):
        attrs=dict(attributes)
        if tag=='g' and attrs.get('data-node-id'):
            node_id=attrs['data-node-id']
            if node_id in self.nodes:
                raise ValueError(f'Duplicate Archify node ID: {node_id}')
            self.nodes[node_id]=attrs.get('data-node-label','')
        if tag=='path' and 'data-edge-from' in attrs:
            self.edges.append((attrs.get('data-edge-from',''),attrs.get('data-edge-to','')))


def validate_viewer_relationships(record,viewer_bytes,chapter_id):
    """Require matching node IDs and directed edge multiplicities.

    Interactive node selection is bridged by data-node-id, so the record and
    viewer must use the same IDs. Edges are compared by endpoint pairs rather
    than renderer-specific edge IDs.
    """
    parser=ViewerTopologyParser()
    parser.feed(viewer_bytes.decode('utf-8'))
    record_nodes=record.get('nodes',[])
    if not record_nodes:
        raise ValueError(f'Chapter {chapter_id}: record has no nodes')
    if not parser.nodes:
        raise ValueError(f'Chapter {chapter_id}: viewer has no Archify nodes')
    record_ids={node['id'] for node in record_nodes}
    viewer_ids=set(parser.nodes)
    if viewer_ids!=record_ids:
        raise ValueError(f'Chapter {chapter_id}: viewer/record node IDs differ; missing={sorted(record_ids-viewer_ids)}, extra={sorted(viewer_ids-record_ids)}')
    viewer_edges=Counter()
    for source,target in parser.edges:
        if source not in record_ids or target not in record_ids:
            raise ValueError(f'Chapter {chapter_id}: viewer edge has an unknown endpoint ({source} -> {target})')
        viewer_edges[(source,target)]+=1
    record_edges=Counter((edge['from'],edge['to']) for edge in record.get('edges',[]))
    if viewer_edges!=record_edges:
        missing=record_edges-viewer_edges
        extra=viewer_edges-record_edges
        raise ValueError(f'Chapter {chapter_id}: viewer/record directed edge mismatch; missing={dict(missing)}, extra={dict(extra)}')
    return {'node_ids':len(record_ids),'edge_count':sum(record_edges.values())}


def _read_explorer_payload(path):
    """Read a packaged explorer-data payload for identity migration."""
    source = Path(path).read_text(encoding='utf-8')
    payload_match = re.search(r'<script type="application/json" id="explorer-data">(.*?)</script>', source, re.S)
    if not payload_match:
        raise ValueError('Migration source does not contain explorer-data')
    try:
        payload = json.loads(payload_match[1])
    except json.JSONDecodeError as error:
        raise ValueError('Migration source contains invalid explorer-data JSON') from error
    if not isinstance(payload, dict):
        raise ValueError('Migration source payload is not an object')
    return payload


def _validate_migration_project(manifest_project_id, payload, label):
    previous_project_id = payload.get('project_id')
    if not isinstance(manifest_project_id, str) or not manifest_project_id:
        raise ValueError(f'{label} requires a manifest project_id')
    if previous_project_id != manifest_project_id:
        raise ValueError(f'{label} must have the same project_id as the manifest')


def package(manifest_path, output, snapshot_from=None, identity_from=None, refresh_conversations=()):
    manifest_path,output=Path(manifest_path).resolve(),Path(output).resolve()
    manifest=json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    project_id=manifest.get('project_id')
    if 'project_id' in manifest and (not isinstance(project_id,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}',project_id)):
        raise ValueError('project_id must be a stable nonempty ASCII identifier of at most 128 characters')
    base=manifest_path.parent
    refresh_paths={str(Path(path).resolve()) for path in refresh_conversations}
    refreshed_paths=set()
    if refresh_paths and not snapshot_from:
        raise ValueError('--refresh-conversation requires --snapshot-from')
    chapters=manifest['chapters']
    assert chapters and len({c['id'] for c in chapters})==len(chapters)
    pool={}; reports=[]; aliases={}; snapshots={}
    identity_payload = _read_explorer_payload(identity_from) if identity_from else None
    snapshot_payload = _read_explorer_payload(snapshot_from) if snapshot_from else None
    migration_payload = identity_payload or (snapshot_payload if isinstance(project_id, str) and project_id and snapshot_payload and snapshot_payload.get('project_id') else None)
    if identity_payload and snapshot_payload and identity_payload.get('project_id') != snapshot_payload.get('project_id'):
        raise ValueError('identity and snapshot migration sources must have the same project_id')
    if identity_payload or (migration_payload and snapshot_payload):
        _validate_migration_project(project_id, migration_payload, '--identity-from/--snapshot-from')
    if snapshot_from:
        previous=snapshot_payload
        snapshots={f['path']:f for f in previous['files'].values()}
        previous_chapters={c['id']:c for c in previous['chapters']}
        # A moved output directory must not refresh a relative resource from disk.
        # Resolve the prior chapter's exact URI in its new base and retain its ID,
        # original path, timestamps and bytes. Unknown URIs still fail closed.
        for ch in chapters:
            old=previous_chapters.get(ch['id'])
            if not old:continue
            record_base=(base/ch['record']).resolve().parent
            for item in old['record']['sources']+[a for n in old['record']['nodes'] for a in n['artifacts']]:
                uri=item.get('uri','');file=previous['files'].get(item.get('file_id'))
                if not file or not uri or Path(uri).is_absolute() or re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',uri):continue
                path=local_path(uri,record_base)
                if path is not None:
                    if str(path) in snapshots and snapshots[str(path)].get('sha256')!=file.get('sha256'):
                        raise ValueError('Ambiguous relocated snapshot URI')
                    snapshots[str(path)]=file
    for ch in chapters:
        record=(base/ch['record']).resolve()
        aliases[str(record.parent/'evolution.html')]=ch['id']
        for alias in ch.get('aliases',[]):aliases[str((base/alias).resolve())]=ch['id']

    def attach(item, record_base):
        uri=item.get('uri','')
        if not uri:return
        path=local_path(uri,record_base)
        if path is None:return
        # One physical source may also appear as an artifact in an earlier chapter.
        # Honor its explicit refresh consistently, then require a conversation
        # source reference before writing any output (checked below).
        refresh=str(path) in refresh_paths
        if refresh:
            if not path.is_file():
                raise ValueError('Requested conversation export is not a readable file')
            if item.get('kind')=='conversation':refreshed_paths.add(str(path))
        if str(path) in aliases:
            item['chapter_id']=aliases[str(path)]
            return
        key=snapshots[str(path)]['id'] if str(path) in snapshots else 'file_'+hashlib.sha256(str(path).encode()).hexdigest()[:20]
        item['file_id']=key
        if key in pool:return
        file={'id':key,'path':str(path),'name':path.name,'status':'missing'}
        pool[key]=file
        if str(path) in snapshots and not refresh:
            preserved=copy.deepcopy(snapshots[str(path)])
            preserved.pop('text',None)
            if preserved['status']=='embedded':
                raw_snapshot=base64.b64decode(preserved['data'],validate=True)
                assert hashlib.sha256(raw_snapshot).hexdigest()==preserved['sha256']
                assert len(raw_snapshot)==preserved['bytes']
                reason=credential_reason(path.name,raw_snapshot,(preserved.get('name'),))
                if reason:
                    file.update(status='excluded',note=reason)
                    return
                if not str(preserved.get('mime','')).startswith('image/'):
                    text=decode_text(raw_snapshot)
                    if text is not None:preserved['text']=text
            else:
                preserved.pop('data',None)
            preserved['id']=key
            pool[key]=preserved
            return
        if snapshot_from and not refresh:
            raise ValueError(f'No prior snapshot for {path}; explicitly refresh sources to add files')
        if not path.exists():return
        reason=credential_reason(path.name)
        if reason:
            file.update(status='excluded',note=reason);return
        if path.is_dir():
            paths=sorted(str(p.relative_to(path)).replace('\\','/') for p in path.rglob('*') if p.is_file())
            raw=('目录索引（不包含目录内文件内容）\n原始位置：'+str(path)+'\n\n'+'\n'.join(paths)+'\n').encode('utf-8')
            file.update(name=path.name+'-目录索引.txt',mime='text/plain',is_directory=True)
        else:
            raw=path.read_bytes()
            file['mime']=mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        if len(raw)>25*1024*1024:
            file.update(status='excluded',note='单文件超过25 MB，保留原始位置。');return
        reason=credential_reason(path.name,raw)
        if reason:
            file.update(status='excluded',note=reason);return
        if not file['mime'].startswith('image/'):
            text=decode_text(raw)
            if text is not None:
                file['text']=text
        file.update(status='embedded',data=encode(raw),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())

    packed=[]
    for ch in chapters:
        record=(base/ch['record']).resolve(); viewer=(base/ch['viewer']).resolve()
        raw=json.loads(record.read_text(encoding='utf-8-sig'))
        data=validate(copy.deepcopy(raw),record.parent,output.parent)
        authored_groups=ch.get('change_groups',{})
        if not isinstance(authored_groups,dict) or set(authored_groups)-{n['id'] for n in data['nodes']}:
            raise ValueError('Chapter change_groups contains an unknown node')
        for n in data['nodes']:
            if n['id'] in authored_groups:n['change_groups']=copy.deepcopy(authored_groups[n['id']])
            validate_groups(n)
        presentation=ch.get('presentation',{})
        if not isinstance(presentation,dict) or set(presentation)-{n['id'] for n in data['nodes']}:
            raise ValueError('Chapter presentation contains an unknown node')
        for n in data['nodes']:
            display=presentation.get(n['id'],{})
            if not isinstance(display,dict) or set(display)-{'title','summary','reason'} or any(not isinstance(v,str) for v in display.values()):
                raise ValueError('Presentation allows only text title, summary and reason')
            if 'title' in display and not display['title'].strip():raise ValueError('Presentation title cannot be empty')
            for k,v in display.items():n['display_'+k]=v
        viewer_bytes=viewer.read_bytes()
        geometry=audit_file(viewer)
        assert geometry['conflicting_pair_count']==geometry['node_crossing_count']==0, geometry
        topology=validate_viewer_relationships(data,viewer_bytes,ch['id'])
        for item in data['sources']+[a for n in data['nodes'] for a in n['artifacts']]:attach(item,record.parent)
        for n in data['nodes']:
            n['search_text']=' '.join(str(x) for x in [n['title'],n['summary'],n.get('reason',''),n['branch'],*[a['label'] for a in n['artifacts']]]).lower()
        digest=hashlib.sha256(viewer_bytes).hexdigest()
        overview_id=manifest.get('navigation',{}).get('source_chapter')
        graph_layout=vertical_layout(viewer_bytes,data,prefer_branches=ch['id']!=overview_id)
        packed.append({'id':ch['id'],'label':ch['label'],'record':data,'viewer':encode(viewer_bytes),'viewer_sha256':digest,'layout':graph_layout})
        reports.append({'chapter':ch['id'],'nodes':len(data['nodes']),'edges':len(data['edges']),'viewer_sha256':digest,'record_viewer_topology':topology,'all_pair_route_audit':geometry,'workbench_route_audit':graph_layout['audit']})
    if refreshed_paths != refresh_paths:
        raise ValueError('--refresh-conversation must name conversation sources in the manifest records')
    conversations=build_conversation_index(packed,pool)
    payload={'title':manifest['title'],'chapters':packed,'files':pool,'conversations':conversations,'created_at':datetime.now().isoformat(timespec='seconds')}
    payload['collection_audit']=validate_package_collection(manifest,base,packed,pool)
    if project_id is not None:payload['project_id']=project_id
    if migration_payload:
        group_aliases,entry_aliases=build_conversation_aliases(migration_payload,conversations)
        payload['conversation_group_aliases']=group_aliases
        payload['conversation_entry_aliases']=entry_aliases
    payload['navigation']=navigation_data(manifest,packed)
    payload['start']=initial_target(manifest,packed)
    source=Path(__file__).resolve().parent.parent
    template=(source/'assets/interactive.html').read_text(encoding='utf-8')
    script='\n;\n'.join((source/name).read_text(encoding='utf-8') for name in ['assets/vendor/marked.umd.js','assets/markdown.js','assets/conversations.js','assets/project-tools.js','assets/interactive.js'])
    assert not re.search(r'</script',script,re.I), 'Inline script contains a closing script tag'
    serialized=json.dumps(payload,ensure_ascii=False).replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e')
    replacements={'@@TITLE@@':html.escape(manifest['title']),'@@PAYLOAD@@':serialized,'@@SCRIPT@@':script}
    page=re.sub(r'@@(?:TITLE|PAYLOAD|SCRIPT)@@',lambda m:replacements[m[0]],template)
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists():
        backup=output.parent/'history'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        backup.mkdir(parents=True);shutil.copy2(output,backup/output.name)
    output.write_text(page,encoding='utf-8')
    report={'output':str(output),'bytes':output.stat().st_size,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'chapters':reports,'files':[{'id':f['id'],'path':f['path'],'status':f['status'],'bytes':f.get('bytes'), 'sha256':f.get('sha256')} for f in pool.values()]}
    (output.parent/'package-receipt.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'output':str(output),'chapters':len(packed),'attachments':len(pool),'embedded':sum(f['status']=='embedded' for f in pool.values()),'size_mb':round(output.stat().st_size/1024**2,2)},ensure_ascii=False))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest');parser.add_argument('output')
    parser.add_argument('--snapshot-from',help='Reuse exact attachments from an existing interactive HTML and migrate associations')
    parser.add_argument('--identity-from',help='Migrate stable conversation identities from an existing interactive HTML')
    parser.add_argument('--refresh-conversation',action='append',default=[],help='With --snapshot-from, refresh this conversation export only; may be repeated. Other snapshots stay archived.')
    args=parser.parse_args();package(args.manifest,args.output,args.snapshot_from,args.identity_from,args.refresh_conversation)
