#!/usr/bin/env python3
"""Render a reviewed evolution.json into offline HTML, SVG, and Markdown."""
import argparse
import copy
import html
import json
import os
import re
import sys
import unicodedata
import shutil
from datetime import datetime
from collections import defaultdict, deque
from pathlib import Path, PureWindowsPath
from urllib.parse import quote, urlsplit

STATUS = {'proposed': '提议', 'in_progress': '进行中', 'completed': '已完成', 'verified': '已验证', 'failed': '失败', 'paused': '暂停', 'superseded': '被替代', 'unknown': '待确认'}
KIND = {'goal': '目标', 'milestone': '里程碑', 'module': '模块', 'experiment': '尝试', 'decision': '决策', 'issue': '问题'}
EDGE = {'continues': '延续', 'branches': '分叉', 'adds': '增加', 'pivots': '转向', 'merges': '合并', 'depends_on': '依赖', 'chronological': '仅先后'}
COLOR = {'proposed': '#635397', 'in_progress': '#235eab', 'completed': '#187363', 'verified': '#187363', 'failed': '#a34537', 'paused': '#926721', 'superseded': '#666879', 'unknown': '#666879'}
ID = re.compile(r'^[A-Za-z][A-Za-z0-9_-]{0,63}$')


def need(ok, message):
    if not ok:
        raise ValueError(message)


def fields(obj, names, context):
    need(isinstance(obj, dict), f'{context}: 必须是对象')
    for name in names:
        need(isinstance(obj.get(name), str) and obj[name].strip(), f'{context}.{name}: 必须是非空字符串')


def optional_strings(obj, names, context):
    for name in names:
        need(name not in obj or isinstance(obj[name], str), f'{context}.{name}: 必须是字符串')


def href_for(uri, base, out):
    """Resolve local targets without accessing them; reject executable/network URIs."""
    need(isinstance(uri, str), 'URI 必须是字符串')
    if not uri:
        return ''
    need(uri == uri.strip() and not any(ord(c) < 32 for c in uri), 'URI 含控制字符或首尾空白')
    need(not uri.startswith(('//', '\\\\')), '不支持网络共享路径')
    if re.match(r'^[A-Za-z]:[\\/]', uri):
        return PureWindowsPath(uri).as_uri()
    parts = urlsplit(uri)
    if parts.scheme:
        need(parts.scheme in {'https', 'http', 'file', 'codex'}, f'禁止的 URI 协议: {parts.scheme}')
        if parts.scheme in {'https', 'http'}:
            need(bool(parts.netloc) and not parts.username and not parts.password, 'HTTP URL 需要主机且不能含登录凭据')
        if parts.scheme == 'file':
            need(not parts.netloc or parts.netloc.lower() == 'localhost', '不支持远程 file URI')
            need(not parts.path.startswith('//'), '不支持网络共享 file URI')
        return uri
    if uri.startswith('#'):
        return uri
    path = Path(uri)
    if path.is_absolute():
        return path.as_uri()
    target = (base / path).resolve()
    try:
        return quote(Path(os.path.relpath(target, out)).as_posix(), safe='/')
    except ValueError:
        return target.as_uri()


def validate(data, base, out):
    need(isinstance(data, dict) and data.get('schema_version') == 1, 'schema_version 必须为 1')
    fields(data.get('project'), ['title', 'summary'], 'project')
    for key in ['updated_at', 'current_state']:
        need(isinstance(data['project'].get(key), str), f'project.{key}: 必须是字符串')
    for key in ['coverage', 'open_questions', 'revisions']:
        need(isinstance(data.get(key), list) and all(isinstance(v, str) and v.strip() for v in data[key]), f'{key}: 必须是字符串数组')
    need(bool(data['coverage']), 'coverage 不得为空')
    for key in ['sources', 'nodes', 'edges']:
        need(isinstance(data.get(key), list), f'{key}: 必须是数组')
    need(data['sources'] and data['nodes'], 'sources 和 nodes 不得为空')
    indexes = {}
    for group in ['sources', 'nodes']:
        ids = set()
        for item in data[group]:
            fields(item, ['id', 'title'], group)
            need(ID.fullmatch(item['id']) and item['id'] not in ids, f'{group}: 无效或重复 ID {item["id"]}')
            ids.add(item['id'])
        indexes[group] = ids
    for src in data['sources']:
        fields(src, ['kind', 'coverage', 'locator'], src['id'])
        need(src['coverage'] in {'full', 'excerpt', 'summary', 'unavailable'}, f'{src["id"]}: 未知 coverage')
        optional_strings(src, ['uri', 'note'], src['id'])
        src['href'] = href_for(src.get('uri', ''), base, out)

    def evidence(obj, label):
        refs = obj.get('evidence')
        need(isinstance(refs, list) and refs, f'{label}: 缺少 evidence')
        for ref in refs:
            fields(ref, ['source', 'locator'], label)
            optional_strings(ref, ['note'], label)
            need(ref['source'] in indexes['sources'], f'{label}: 未知来源 {ref["source"]}')

    for node in data['nodes']:
        nid = node['id']
        fields(node, ['kind', 'summary', 'branch', 'status'], nid)
        optional_strings(node, ['reason', 'date'], nid)
        need(node['kind'] in KIND and node['status'] in STATUS, f'{nid}: 未知 kind/status')
        evidence(node, nid)
        node.setdefault('artifacts', [])
        need(isinstance(node['artifacts'], list), f'{nid}.artifacts: 必须是数组')
        for art in node['artifacts']:
            fields(art, ['label', 'uri', 'role', 'verification'], nid)
            optional_strings(art, ['version', 'note'], nid)
            need(art['role'] in {'produced', 'modified', 'referenced'}, f'{nid}: 未知产物 role')
            need(art['verification'] in {'exists', 'missing', 'mentioned', 'unchecked'}, f'{nid}: 未知产物 verification')
            art['href'] = href_for(art['uri'], base, out)
    seen_edges = set()
    for edge in data['edges']:
        fields(edge, ['from', 'to', 'type', 'confidence', 'reason'], 'edge')
        need(edge['from'] in indexes['nodes'] and edge['to'] in indexes['nodes'], 'edge: 悬空节点引用')
        need(edge['type'] in EDGE and edge['confidence'] in {'explicit', 'inferred'}, 'edge: 未知 type/confidence')
        key = (edge['from'], edge['to'], edge['type'])
        need(key not in seen_edges, 'edge: 重复关系')
        seen_edges.add(key)
        evidence(edge, str(key))
    return data


def layout(data):
    nodes = data['nodes']
    counts = {n['id']: 0 for n in nodes}
    children, parents = defaultdict(list), defaultdict(list)
    for e in data['edges']:
        counts[e['to']] += 1
        children[e['from']].append(e['to'])
        parents[e['to']].append(e['from'])
    queue = deque(n['id'] for n in nodes if counts[n['id']] == 0)
    ranks = {n['id']: 0 for n in nodes}
    visited = []
    while queue:
        current = queue.popleft()
        visited.append(current)
        for target in children[current]:
            ranks[target] = max(ranks[target], ranks[current] + 1)
            counts[target] -= 1
            if counts[target] == 0:
                queue.append(target)
    need(len(visited) == len(nodes), '事件图含循环。为重启/修改创建新事件，不要连接回旧事件。')
    layers = defaultdict(list)
    for n in nodes:
        layers[ranks[n['id']]].append(n['id'])
    order = {n['id']: i for i, n in enumerate(nodes)}
    pos = {}
    width = max(760, max(len(v) for v in layers.values()) * 328 + 64)
    for rank in sorted(layers):
        layer = layers[rank]
        layer.sort(key=lambda nid: (sum(pos[p][0] for p in parents[nid]) / len(parents[nid])) if parents[nid] else order[nid] * 328)
        left = (width - (len(layer) * 328 - 40)) / 2
        for i, nid in enumerate(layer):
            pos[nid] = (left + i * 328, 120 + rank * 242)
    long_count = sum(ranks[e['to']] > ranks[e['from']] + 1 for e in data['edges'])
    return pos, ranks, width + long_count * 20, 120 + len(layers) * 242


def lines(text, limit=26, max_lines=2):
    result, row, size = [], '', 0
    for char in text.replace('\n', ' '):
        step = 2 if unicodedata.east_asian_width(char) in 'WF' else 1
        if size + step > limit:
            result.append(row)
            row, size = '', 0
        row += char
        size += step
    if row:
        result.append(row)
    if len(result) > max_lines:
        result = result[:max_lines]
        result[-1] = result[-1][:-1] + '…'
    return result or ['']


def svg_graph(data, positions, ranks, width, height):
    esc = html.escape
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="group" aria-labelledby="graph-title graph-desc">',
         f'<title id="graph-title">{esc(data["project"]["title"])} · 对话脉络图</title>',
         '<desc id="graph-desc">从上向下阅读。实线为明确关系；虚线为推测或仅时间先后。节点可点击进入详情和产物链接。</desc>',
         '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8Z" fill="#81928f"/></marker></defs>',
         '<style>text{font-family:system-ui,"Microsoft YaHei",sans-serif}a{text-decoration:none}.box{fill:#fff;stroke:#ccd5d1;stroke-width:1.4}.node:hover .box,.node:focus .box,.node.selected .box{stroke:#187363;stroke-width:3}.node:focus{outline:none}.dim{opacity:.22}.edge.active path{stroke:#187363;stroke-width:2.4}</style>',
         f'<rect width="{width}" height="{height}" fill="#f5f7f3"/>',
         f'<text x="32" y="39" font-size="20" font-weight="650" fill="#18372f">{esc(lines(data["project"]["title"], 60, 1)[0])}</text>',
         '<text x="32" y="66" font-size="12" fill="#52685f">实线：明确关系　 ·　 虚线：推测 / 仅先后　 ·　 点击框查看详情与产物</text>']
    rail = 0
    for index, edge in enumerate(data['edges']):
        x1, y1 = positions[edge['from']]
        x2, y2 = positions[edge['to']]
        x1, x2, y1 = x1 + 144, x2 + 144, y1 + 160
        middle = (y1 + y2) / 2
        if ranks[edge['to']] > ranks[edge['from']] + 1:
            route = width - 24 - rail * 20
            rail += 1
            path = f'M{x1},{y1} V{y1+22} H{route} V{y2-22} H{x2} V{y2}'
            lx, ly = route - 8, middle
            anchor = 'end'
        else:
            path = f'M{x1},{y1} C{x1},{middle} {x2},{middle} {x2},{y2}'
            lx, ly = (x1+x2)/2, middle
            anchor = 'middle'
        dashed = edge['confidence'] == 'inferred' or edge['type'] == 'chronological'
        label = EDGE[edge['type']] + (' · 推测' if edge['confidence'] == 'inferred' else '')
        dash_attr = ' stroke-dasharray="6 5"' if dashed else ''
        s.append(f'<g class="edge" data-edge="{index}"><title>{esc(label+": "+edge["reason"])}</title><path d="{path}" fill="none" stroke="#81928f" stroke-width="1.6"{dash_attr} marker-end="url(#arrow)"/><text x="{lx}" y="{ly-6}" text-anchor="{anchor}" fill="#52685f" font-size="11" paint-order="stroke" stroke="#f5f7f3" stroke-width="5" stroke-linejoin="round">{esc(label)}</text></g>')
    for n in data['nodes']:
        x, y = positions[n['id']]
        color = COLOR[n['status']]
        s.append(f'<a class="node" id="node-{n["id"]}" data-node="{n["id"]}" href="evolution.html#node={n["id"]}" tabindex="0" aria-label="{esc(n["title"]+"，"+STATUS[n["status"]])}"><title>{esc(n["title"]+" — "+n["summary"])}</title><rect class="box" x="{x}" y="{y}" width="288" height="160" rx="12"/><rect x="{x}" y="{y+18}" width="4" height="30" rx="2" fill="{color}"/><text x="{x+20}" y="{y+28}" font-size="11" fill="#52685f">{esc(KIND[n["kind"]]+" · "+lines(n["branch"],22,1)[0])}</text><text x="{x+268}" y="{y+28}" text-anchor="end" font-size="11" font-weight="600" fill="{color}">{STATUS[n["status"]]}</text>')
        for i, line in enumerate(lines(n['title'], 28, 2)):
            s.append(f'<text x="{x+20}" y="{y+59+i*24}" font-size="17" font-weight="650" fill="#193b31">{esc(line)}</text>')
        summary = lines(n['summary'], 36, 1)[0]
        s.append(f'<text x="{x+20}" y="{y+112}" font-size="12" fill="#52685f">{esc(summary)}</text><line x1="{x+20}" y1="{y+126}" x2="{x+268}" y2="{y+126}" stroke="#e6ebe5"/><text x="{x+20}" y="{y+146}" font-size="11" fill="#52685f">{esc(n.get("date", "") or "时间未注明")}</text><text x="{x+268}" y="{y+146}" text-anchor="end" font-size="11" fill="#187363">{len(n["artifacts"])} 产物 · {len(n["evidence"])} 证据</text></a>')
    s.append('</svg>')
    return '\n'.join(s)


def markdown(data):
    def txt(value):
        return str(value).replace('<', '&lt;').replace('>', '&gt;').replace('[', '\\[').replace(']', '\\]')
    def link(label, href):
        return f'[{txt(label)}](<{href.replace(">", "%3E")}>)' if href else txt(label)
    p = data['project']
    out = [f'# {txt(p["title"])}', '', txt(p['summary']), '', f'更新时间：{txt(p["updated_at"])}', '', f'当前状态：{txt(p["current_state"] or "尚不确定")}', '', '## 材料覆盖', '']
    out += ['- ' + txt(t) for t in data['coverage']]
    for n in data['nodes']:
        out += ['', f'## {txt(n["title"])} · {STATUS[n["status"]]}', '', f'ID: {n["id"]} · {txt(n["branch"])} · {txt(n.get("date", ""))}', '', txt(n['summary'])]
        if n.get('reason'):
            out += ['', '原因 / 取舍：' + txt(n['reason'])]
        out += ['', '来源：', ''] + [f'- {r["source"]} · {txt(r["locator"])}：{txt(r.get("note", ""))}' for r in n['evidence']]
        if n['artifacts']:
            out += ['', '产物：', ''] + [f'- {link(a["label"], a["href"])} — {a["role"]} / {a["verification"]}；{txt(a.get("version", ""))} {txt(a.get("note", ""))}' for a in n['artifacts']]
    out += ['', '## 关系', '']
    for e in data['edges']:
        refs = '; '.join(f'{r["source"]} / {r["locator"]} / {r.get("note", "")}' for r in e['evidence'])
        out.append(f'- {e["from"]} → {e["to"]}：{EDGE[e["type"]]} ({e["confidence"]})。{txt(e["reason"])} 依据：{txt(refs)}')
    out += ['', '## 来源索引', ''] + [f'- {s["id"]}：{link(s["title"], s["href"])}；{s["coverage"]}；{txt(s["locator"])}；{txt(s.get("note", ""))}' for s in data['sources']]
    for key, label in [('open_questions', '待确认'), ('revisions', '修订记录')]:
        if data[key]:
            out += ['', '## '+label, ''] + ['- '+txt(t) for t in data[key]]
    return '\n'.join(out)+'\n'


def render(source, out):
    source, out = Path(source).resolve(), Path(out).resolve()
    raw = json.loads(source.read_text(encoding='utf-8-sig'))
    data = validate(copy.deepcopy(raw), source.parent, out)
    positions, ranks, width, height = layout(data)
    svg = svg_graph(data, positions, ranks, width, height)
    template = (Path(__file__).parent.parent / 'assets' / 'viewer.html').read_text(encoding='utf-8')
    embedded = json.dumps(data, ensure_ascii=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    replacements = {'@@TITLE@@': html.escape(data['project']['title']), '@@GRAPH@@': svg, '@@DATA@@': embedded}
    page = re.sub(r'@@(?:TITLE|GRAPH|DATA)@@', lambda m: replacements[m[0]], template)
    out.mkdir(parents=True, exist_ok=True)
    replaced = [out / ('evolution.' + suffix) for suffix in ['html', 'svg', 'md']]
    if source != out / 'evolution.json':
        replaced.append(out / 'evolution.json')
    existing = [p for p in replaced if p.exists()]
    if existing:
        backup = out / 'history' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        backup.mkdir(parents=True)
        for p in existing:
            shutil.copy2(p, backup / p.name)
    (out / 'evolution.html').write_text(page, encoding='utf-8')
    (out / 'evolution.svg').write_text('<?xml version="1.0" encoding="UTF-8"?>\n'+svg, encoding='utf-8')
    (out / 'evolution.md').write_text(markdown(data), encoding='utf-8')
    if source != out / 'evolution.json':
        # Rebase relative targets so a copied JSON remains usable on the next run.
        links = raw['sources'] + [a for n in raw['nodes'] for a in n.get('artifacts', [])]
        for item in links:
            uri = item.get('uri', '')
            if uri and not uri.startswith('#') and not urlsplit(uri).scheme and not Path(uri).is_absolute():
                target = (source.parent / uri).resolve()
                try:
                    item['uri'] = Path(os.path.relpath(target, out)).as_posix()
                except ValueError:
                    item['uri'] = target.as_uri()
        (out / 'evolution.json').write_text(json.dumps(raw, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return {'nodes': len(data['nodes']), 'edges': len(data['edges']), 'sources': len(data['sources']), 'output': str(out)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('json_file', type=Path)
    parser.add_argument('--out-dir', required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(render(args.json_file, args.out_dir), ensure_ascii=False))
    except (ValueError, OSError, TypeError, KeyError) as error:
        print(f'无法生成演进图: {error}', file=sys.stderr)
        sys.exit(1)
