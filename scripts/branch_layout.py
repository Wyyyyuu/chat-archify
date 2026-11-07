"""Checked two-lane layout for simple, evidence-backed fork/join chapters.

Unsupported topology returns None so the caller can retain its checked compact
layout. Nodes and relationships are never merged to fit this presentation.
"""
from collections import Counter


def branch_layout(record):
    ids = [n['id'] for n in record['nodes']]
    outgoing = {nid: [] for nid in ids}
    incoming = {nid: [] for nid in ids}
    for edge in record['edges']:
        outgoing[edge['from']].append(edge['to'])
        incoming[edge['to']].append(edge['from'])
    roots = [nid for nid in ids if not incoming[nid]]
    if len(roots) != 1 or any(len(v) > 2 for v in (*outgoing.values(), *incoming.values())):
        return None
    if not any(len(v) == 2 for v in outgoing.values()):
        return None
    width, height, gap, pad, lane_gap = 240, 104, 56, 24, 56
    canvas_width = 2 * width + lane_gap + 2 * pad
    center = canvas_width / 2
    lane_centers = [pad + width / 2, canvas_width - pad - width / 2]
    placed, positions, row = set(), {}, 0
    fork_routes, join_routes = {}, {}

    def place(nid, x, level):
        if nid in placed:
            return False
        placed.add(nid)
        positions[nid] = {'id': nid, 'x': x - width / 2,
                          'y': pad + level * (height + gap), 'width': width, 'height': height}
        return True

    current = roots[0]
    while current is not None:
        if not place(current, center, row):
            return None
        children = outgoing[current]
        if not children:
            break
        if len(children) == 1:
            current = children[0]
            row += 1
            continue
        arms, ends = [], []
        for child in children:
            path, seen = [], set()
            while len(incoming[child]) == 1:
                if child in seen or child in placed or len(outgoing[child]) != 1:
                    return None
                seen.add(child)
                path.append(child)
                child = outgoing[child][0]
            arms.append(path)
            ends.append(child)
        if ends[0] != ends[1] or not all(arms) or set(arms[0]) & set(arms[1]):
            return None
        join = ends[0]
        if Counter(incoming[join]) != Counter([arm[-1] for arm in arms]):
            return None
        for lane, arm in enumerate(arms):
            for offset, nid in enumerate(arm, 1):
                if not place(nid, lane_centers[lane], row + offset):
                    return None
            fork_routes[(current, arm[0])] = lane
            join_routes[(arm[-1], join)] = lane
        row += max(map(len, arms)) + 1
        current = join
    if placed != set(ids):
        return None

    edges = []
    for index, edge in enumerate(record['edges']):
        a, b = positions[edge['from']], positions[edge['to']]
        ax, ay = a['x'] + width / 2, a['y'] + height
        bx, by = b['x'] + width / 2, b['y']
        pair = (edge['from'], edge['to'])
        if pair in fork_routes:
            port = center + (-24 if fork_routes[pair] == 0 else 24)
            points = [[port, ay], [port, ay + gap / 2], [bx, ay + gap / 2], [bx, by]]
        elif pair in join_routes:
            port = center + (-24 if join_routes[pair] == 0 else 24)
            points = [[ax, ay], [ax, by - gap / 2], [port, by - gap / 2], [port, by]]
        elif ax == bx and by > ay:
            points = [[ax, ay], [bx, by]]
        else:
            return None
        edges.append({**edge, 'id': f'branch-{index}', 'points': points})
    layout = {'width': canvas_width, 'height': max(n['y'] + height for n in positions.values()) + pad,
              'nodes': [positions[nid] for nid in ids], 'edges': edges, 'strategy': 'checked-two-lane'}
    from workbench_data import audit_layout
    try:
        layout['audit'] = audit_layout(layout)
    except ValueError:
        return None
    return layout
