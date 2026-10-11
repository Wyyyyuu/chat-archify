"""Narrow, audited box-and-arrow layouts for short project chapters."""
from collections import defaultdict
from workbench_data import audit_layout


def compact_layout(record, limit=1500):
    """Try bounded topological orders; route consecutive steps down the center.

    Nonconsecutive edges occupy outside channels. Interleaving intervals must
    use opposite sides; nested intervals use distinct depths. A final geometric
    audit remains authoritative. Return None if this narrower drawing cannot
    preserve the complete graph; callers retain the checked original layout.
    """
    ids = [node['id'] for node in record['nodes']]
    edges = record['edges']
    original_position = {nid: i for i, nid in enumerate(ids)}
    predecessors = {nid: set() for nid in ids}
    for edge in edges:
        predecessors[edge['to']].add(edge['from'])
    best, visited = None, 0

    def consider(order):
        nonlocal best
        position = {nid: i for i, nid in enumerate(order)}
        outside, direct, used = [], set(), set()
        for i, edge in enumerate(edges):
            a, b = position[edge['from']], position[edge['to']]
            if b == a + 1 and (a, b) not in used:
                direct.add(i)
                used.add((a, b))
            else:
                outside.append((i, a, b))
        colors = {}
        for k, edge in enumerate(outside):
            if k in colors:
                continue
            colors[k], stack = 0, [k]
            while stack:
                x = stack.pop()
                _, a, b = outside[x]
                for y, (_, c, d) in enumerate(outside):
                    if not (a < c < b < d or c < a < d < b):
                        continue
                    if y in colors:
                        if colors[y] == colors[x]:
                            return
                    else:
                        colors[y] = 1 - colors[x]
                        stack.append(y)
        sides = {edge[0]: colors[k] for k, edge in enumerate(outside)}
        depth, extent = {}, []
        for side in (0, 1):
            group = [edge for edge in outside if sides[edge[0]] == side]
            for i, a, b in sorted(group, key=lambda edge: (edge[2] - edge[1], edge[0])):
                depth[i] = 1 + max([depth[j] for j, c, d in group
                                   if a <= c and d <= b and ((a, b) != (c, d) or j < i)] + [0])
            extent.append(max([depth[edge[0]] for edge in group] + [0]))
        inversions = sum(original_position[a] > original_position[b]
                         for i, a in enumerate(order) for b in order[i+1:])
        score = (sum(extent), len(outside), sum(b-a for _, a, b in outside), inversions)
        if best is None or score < best[0]:
            best = (score, order[:], depth, sides, direct, extent)

    def visit(order, remaining):
        nonlocal visited
        if visited >= limit:
            return
        if not remaining:
            visited += 1
            consider(order)
            return
        remaining_set = set(remaining)
        for nid in remaining:
            if not (predecessors[nid] & remaining_set):
                visit(order + [nid], [other for other in remaining if other != nid])

    visit([], ids)
    if best is None:
        return None
    _, order, depth, sides, direct, extent = best
    width, height, gap, padding, channel = 200, 92, 40, 20, 18
    left = padding + extent[0] * channel
    nodes = [{'id': nid, 'x': left, 'y': padding + i * (height+gap),
              'width': width, 'height': height} for i, nid in enumerate(order)]
    by_id = {node['id']: node for node in nodes}
    outgoing, incoming = defaultdict(list), defaultdict(list)
    for i in depth:
        edge = edges[i]
        outgoing[(edge['from'], sides[i])].append(i)
        incoming[(edge['to'], sides[i])].append(i)
    ports = {}
    for direction, groups in [('out', outgoing), ('in', incoming)]:
        for (nid, side), group in groups.items():
            ordered = sorted(group, key=lambda i: depth[i], reverse=direction == 'out')
            for k, i in enumerate(ordered):
                fraction = (.58 if direction == 'out' else .2) + .22*k/max(1, len(group)-1)
                ports[(i, direction)] = round(by_id[nid]['y'] + height*fraction, 6)
    routes = []
    for i, edge in enumerate(edges):
        a, b = by_id[edge['from']], by_id[edge['to']]
        if i in direct:
            points = [[left+width/2, a['y']+height], [left+width/2, b['y']]]
        else:
            x = left if sides[i] == 0 else left+width
            outside_x = x + (-1 if sides[i] == 0 else 1)*depth[i]*channel
            y1, y2 = ports[(i, 'out')], ports[(i, 'in')]
            points = [[x, y1], [outside_x, y1], [outside_x, y2], [x, y2]]
        routes.append({**edge, 'id': f'compact-{i}', 'points': points})
    layout = {'width': width+2*padding+sum(extent)*channel,
              'height': 2*padding+len(nodes)*height+max(0,len(nodes)-1)*gap,
              'nodes': nodes, 'edges': routes, 'strategy': 'compact-vertical'}
    try:
        layout['audit'] = audit_layout(layout)
    except ValueError:
        return None
    return layout
