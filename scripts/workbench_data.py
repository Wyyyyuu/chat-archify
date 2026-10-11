"""Presentation metadata and lossless vertical geometry for the workbench."""
from collections import defaultdict, deque
from itertools import combinations
from statistics import median

from check_routes import DiagramParser, intersection, interior_intersection, node_boundary, segments


def _warp(intervals, occupied_size, gap_size):
    """A strictly increasing axis map: keep topology, resize boxes and whitespace."""
    bounds = sorted({v for a, b in intervals for v in (a, b)})
    scale = occupied_size / median(b - a for a, b in intervals)
    spans, offset = [], 0.0
    for a, b in zip(bounds, bounds[1:]):
        inside = any(lo <= (a + b) / 2 <= hi for lo, hi in intervals)
        length = (b - a) * scale if inside else gap_size
        spans.append((a, b, offset, length / (b - a)))
        offset += length

    def transform(value):
        if value <= bounds[0]:
            return (value - bounds[0]) * scale
        for a, b, start, rate in spans:
            if value <= b:
                return start + (value - a) * rate
        return offset + (value - bounds[-1]) * scale
    return transform


def audit_layout(layout):
    nodes = {n['id']: (n['x'], n['y'], n['width'], n['height']) for n in layout['nodes']}
    edges = layout['edges']
    conflicts, crossings = [], []
    for edge in edges:
        if edge['from'] not in nodes or edge['to'] not in nodes:
            raise ValueError('Layout contains an unknown endpoint')
        for a, b in segments(edge['points']):
            if abs(a[0]-b[0]) > 1e-7 and abs(a[1]-b[1]) > 1e-7:
                raise ValueError('Layout route is not orthogonal')
            for name, rect in nodes.items():
                if interior_intersection(a, b, rect):
                    crossings.append((edge['id'], name))
    for first, second in combinations(edges, 2):
        shared = {first['from'], first['to']} & {second['from'], second['to']}
        for a, b in segments(first['points']):
            for c, d in segments(second['points']):
                hit = intersection(a, b, c, d)
                if not hit:
                    continue
                point = hit[1]
                if hit[0] == 'point' and point in tuple(map(tuple, (first['points'][0], first['points'][-1]))) and point in tuple(map(tuple, (second['points'][0], second['points'][-1]))) and any(node_boundary(point, nodes[n]) for n in shared):
                    continue
                conflicts.append((first['id'], second['id']))
    if conflicts or crossings:
        raise ValueError(f'Workbench geometry conflicts: {conflicts}; node crossings: {crossings}')
    return {'nodes': len(nodes), 'edges': len(edges), 'crossings': 0, 'node_crossings': 0}


def vertical_layout(viewer_bytes, record):
    from compact_layout import compact_layout
    compact = compact_layout(record)
    if compact is not None:
        return compact
    parser = DiagramParser()
    parser.feed(viewer_bytes.decode('utf-8'))
    if not parser.nodes:
        raise ValueError('No checked viewer geometry available')
    # Transpose both node boxes and complete edge routes using increasing maps.
    # No node/edge is removed or independently repositioned.
    to_x = _warp([(y, y+h) for x, y, w, h in parser.nodes.values()], 224, 64)
    to_y = _warp([(x, x+w) for x, y, w, h in parser.nodes.values()], 104, 72)
    points = [(to_x(y), to_y(x)) for x, y, w, h in parser.nodes.values()]
    points += [(to_x(y+h), to_y(x+w)) for x, y, w, h in parser.nodes.values()]
    points += [(to_x(y), to_y(x)) for e in parser.edges for x, y in e['points']]
    left, top = min(p[0] for p in points)-32, min(p[1] for p in points)-32
    def transform(x, y):
        return [round(to_x(y)-left, 6), round(to_y(x)-top, 6)]
    nodes = []
    for nid, (x, y, w, h) in parser.nodes.items():
        a, b = transform(x, y), transform(x+w, y+h)
        nodes.append({'id': nid, 'x': a[0], 'y': a[1], 'width': round(b[0]-a[0], 6), 'height': round(b[1]-a[1], 6)})
    semantics = defaultdict(deque)
    for edge in record['edges']:
        semantics[(edge['from'], edge['to'])].append(edge)
    edges = []
    for edge in parser.edges:
        original = semantics[(edge['from'], edge['to'])].popleft()
        edges.append({**edge, 'points': [transform(x, y) for x, y in edge['points']],
                      **{k: original[k] for k in ('type', 'confidence', 'reason')}})
    layout = {'width': round(max(p[0] for p in points)-left+32, 6),
              'height': round(max(p[1] for p in points)-top+32, 6), 'nodes': nodes, 'edges': edges}
    layout['strategy'] = 'preserved-planar'
    layout['audit'] = audit_layout(layout)
    return layout


def validate_groups(node):
    if 'change_groups' not in node:
        return
    groups, used = node['change_groups'], set()
    if not isinstance(groups, list):
        raise ValueError('change_groups must be an array')
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get('title'), str) or not group['title'].strip() or not isinstance(group.get('summary'), str):
            raise ValueError('Each change group needs a title and a summary')
        indices = group.get('artifact_indices')
        if not isinstance(indices, list):
            raise ValueError('artifact_indices must be an array')
        for index in indices:
            if type(index) is not int or not 0 <= index < len(node['artifacts']) or index in used:
                raise ValueError('Change group artifact index is invalid or repeated')
            used.add(index)


def navigation_data(manifest, packed):
    chapters = {c['id']: c for c in packed}
    nav = manifest.get('navigation')
    if nav is None:
        return {'items': [{'id': c['id'], 'chapter': c['id'], 'label': c['label'], 'summary': '',
                           'status': 'unknown', 'lane': 0, 'order': i} for i, c in enumerate(packed)],
                'edges': [], 'note': '主题入口；未提供主题之间的演进关系。'}
    if not isinstance(nav, dict) or not isinstance(nav.get('items'), list) or not nav['items'] or not isinstance(nav.get('edges'), list):
        raise ValueError('navigation needs nonempty items and an edges array')
    source = chapters.get(nav.get('source_chapter'))
    if source is None:
        raise ValueError('navigation.source_chapter must name the evidence-bearing overview chapter')
    original_nodes = {n['id']: n for n in source['record']['nodes']}
    items, ids, orders = [], set(), set()
    for index, entry in enumerate(nav['items']):
        item = dict(entry)
        if not isinstance(item.get('id'), str) or not item['id'] or item['id'] in ids or item.get('chapter') not in chapters:
            raise ValueError('Navigation item has duplicate id or unknown chapter')
        source_id = item.get('source_node', item['id'])
        original = original_nodes.get(source_id)
        if original is None:
            raise ValueError('Navigation item has no source event')
        targets = {n['id'] for n in chapters[item['chapter']]['record']['nodes']}
        if item.get('node') and item['node'] not in targets:
            raise ValueError('Navigation target node is unknown')
        order, lane = item.get('order', index), item.get('lane', 0)
        if type(order) is not int or order < 0 or order in orders or type(lane) is not int or not 0 <= lane <= 4:
            raise ValueError('Navigation order/lane is invalid')
        if not isinstance(item.get('label', original['title']), str) or not isinstance(item.get('summary', ''), str):
            raise ValueError('Navigation labels must be text')
        item.update(source_node=source_id, status=original['status'], order=order, lane=lane,
                    label=item.get('label') or original['title'], summary=item.get('summary', ''), date=original.get('date', ''))
        ids.add(item['id']); orders.add(order); items.append(item)
    by_id = {n['id']: n for n in items}
    source_edges = {(e['from'], e['to'], e['type']): e for e in source['record']['edges']}
    edges, seen = [], set()
    for edge in nav['edges']:
        a, b = by_id.get(edge.get('from')), by_id.get(edge.get('to'))
        if a is None or b is None or a['order'] >= b['order']:
            raise ValueError('Navigation edge must reference known events in forward order')
        key = (a['source_node'], b['source_node'], edge.get('type'))
        if key not in source_edges or key in seen:
            raise ValueError('Navigation relationship is unsupported or duplicated')
        original = source_edges[key]
        edges.append({**original, 'from': a['id'], 'to': b['id']})
        seen.add(key)
    expected = {key for key in source_edges if key[0] in {n['source_node'] for n in items} and key[1] in {n['source_node'] for n in items}}
    if seen != expected:
        raise ValueError('Navigation omits a relationship between included source events')
    items.sort(key=lambda n: n['order'])
    return {'items': items, 'edges': edges,
            'source_chapter': source['id'], 'note': str(nav.get('note', '点击总流程中的节点，查看对应的阶段与文件。'))}


def initial_target(manifest, packed):
    start = manifest.get('start', {})
    if not start:
        return {'chapter': packed[0]['id'], 'node': packed[0]['record']['nodes'][0]['id']}
    chapter = next((c for c in packed if c['id'] == start.get('chapter')), None)
    if not chapter or start.get('node') not in {n['id'] for n in chapter['record']['nodes']}:
        raise ValueError('start must reference an existing chapter and node')
    return {'chapter': start['chapter'], 'node': start['node']}
