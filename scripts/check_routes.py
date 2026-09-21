"""Read-only audit of Archify SVG routes, including edges sharing graph nodes.

Usage: python scripts/check_routes.py VIEWER_DIRECTORY [--fixes route_fixes.json]
The optional fixes are applied in memory only. JSON is written to stdout.
Exit 0 = clear, 1 = geometry conflicts, 2 = input/unsupported geometry error.
Only a point shared by both route endpoints on a shared node boundary is exempt.
Positive-length overlaps are never exempt. Labels/markers are outside this audit.
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

EPS = 1e-8
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def parse_path(d):
    tokens = re.findall(r"[A-Za-z]|" + NUMBER, d)
    if re.sub(r"[\s,]+", "", d) != "".join(tokens):
        raise ValueError(f"Unparsed SVG path syntax: {d}")
    points, index = [], 0
    while index < len(tokens):
        if tokens[index] not in ("M", "L") or index + 2 >= len(tokens):
            raise ValueError(f"Audit supports explicit absolute M/L paths only: {d}")
        points.append((float(tokens[index + 1]), float(tokens[index + 2])))
        index += 3
    if len(points) < 2:
        raise ValueError(f"Route needs at least two points: {d}")
    return points


class DiagramParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.edges, self.nodes, self.groups = [], {}, []

    def handle_starttag(self, tag, attributes):
        a = dict(attributes)
        if tag == "g":
            self.groups.append(a.get("data-node-id"))
        if tag == "rect":
            node = next((n for n in reversed(self.groups) if n), None)
            if node and node not in self.nodes:
                self.nodes[node] = tuple(float(a[k]) for k in ("x", "y", "width", "height"))
        if tag == "path" and "data-edge-from" in a:
            self.edges.append({"id": a["data-edge-id"], "from": a["data-edge-from"],
                               "to": a["data-edge-to"], "points": parse_path(a["d"])})

    def handle_endtag(self, tag):
        if tag == "g" and self.groups:
            self.groups.pop()


def segments(points):
    return list(zip(points, points[1:]))


def between(value, a, b):
    return min(a, b) - EPS <= value <= max(a, b) + EPS


def intersection(a, b, c, d):
    ah, ch = abs(a[1] - b[1]) < EPS, abs(c[1] - d[1]) < EPS
    if ah != ch:
        h1, h2, v1, v2 = (a, b, c, d) if ah else (c, d, a, b)
        p = (v1[0], h1[1])
        if between(p[0], h1[0], h2[0]) and between(p[1], v1[1], v2[1]):
            return ("point", p)
    elif abs((a[1] if ah else a[0]) - (c[1] if ch else c[0])) < EPS:
        k = 0 if ah else 1
        low = max(min(a[k], b[k]), min(c[k], d[k]))
        high = min(max(a[k], b[k]), max(c[k], d[k]))
        if low <= high + EPS:
            p = (low, a[1]) if ah else (a[0], low)
            q = (high, a[1]) if ah else (a[0], high)
            return ("point", p) if abs(high - low) < EPS else ("overlap", p, q)
    return None


def node_boundary(point, rect):
    x, y, width, height = rect
    px, py = point
    return between(px, x, x + width) and between(py, y, y + height) and (
        min(abs(px - x), abs(px - x - width), abs(py - y), abs(py - y - height)) < EPS)


def interior_intersection(a, b, rect):
    x, y, w, h = rect
    horizontal = abs(a[1] - b[1]) < EPS
    if horizontal and y + EPS < a[1] < y + h - EPS:
        low, high = max(min(a[0], b[0]), x), min(max(a[0], b[0]), x + w)
        if high - low > EPS:
            return ((low, a[1]), (high, a[1]))
    elif not horizontal and x + EPS < a[0] < x + w - EPS:
        low, high = max(min(a[1], b[1]), y), min(max(a[1], b[1]), y + h)
        if high - low > EPS:
            return ((a[0], low), (a[0], high))
    return None


def audit_file(path, overrides=None):
    parser = DiagramParser()
    parser.feed(path.read_text(encoding="utf-8"))
    edges, nodes = parser.edges, parser.nodes
    if not edges or not nodes:
        raise ValueError(f"No Archify route/node geometry found: {path}")
    edge_ids = {e["id"] for e in edges}
    for edge_id in (overrides or {}):
        if edge_id not in edge_ids:
            raise ValueError(f"Unknown route override {path.name}: {edge_id}")
    for e in edges:
        if overrides and e["id"] in overrides:
            e["points"] = [tuple(p) for p in overrides[e["id"]]]
        for a, b in segments(e["points"]):
            if abs(a[0] - b[0]) > EPS and abs(a[1] - b[1]) > EPS:
                raise ValueError(f"Non-orthogonal segment {path.name}: {e['id']} {a} {b}")
    pairs, node_crossings = [], []
    for ea, eb in itertools.combinations(edges, 2):
        common = {ea["from"], ea["to"]} & {eb["from"], eb["to"]}
        hits = set()
        for a, b in segments(ea["points"]):
            for c, d in segments(eb["points"]):
                hit = intersection(a, b, c, d)
                if not hit:
                    continue
                if hit[0] == "point":
                    p = hit[1]
                    if (p in (ea["points"][0], ea["points"][-1])
                            and p in (eb["points"][0], eb["points"][-1])
                            and any(node_boundary(p, nodes[n]) for n in common if n in nodes)):
                        continue
                hits.add(hit)
        # Suppress duplicate point reports along already reported overlap intervals.
        overlaps = [h for h in hits if h[0] == "overlap"]
        hits = {h for h in hits if h[0] != "point" or not any(
            between(h[1][0], o[1][0], o[2][0]) and between(h[1][1], o[1][1], o[2][1])
            for o in overlaps)}
        if hits:
            pairs.append({"edge_a": ea["id"], "edge_b": eb["id"],
                          "shared_nodes": sorted(common),
                          "conflicts": [{"kind": h[0], "points": h[1:]} for h in sorted(hits)]})
    for edge in edges:
        for segment_index, (a, b) in enumerate(segments(edge["points"])):
            for node, rect in nodes.items():
                hit = interior_intersection(a, b, rect)
                if hit:
                    node_crossings.append({"edge": edge["id"], "node": node,
                                           "segment": segment_index, "interior_interval": hit})
    return {"file": path.name, "edge_count": len(edges), "node_count": len(nodes),
            "conflicting_pair_count": len(pairs), "pairs": pairs,
            "node_crossing_count": len(node_crossings), "node_crossings": node_crossings}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path, help="Directory of archify-*.html or one HTML file")
    ap.add_argument("--fixes", type=Path, help="Per-diagram route point overrides; in memory only")
    args = ap.parse_args()
    try:
        fixes = json.loads(args.fixes.read_text(encoding="utf-8-sig")) if args.fixes else {}
        paths = sorted(args.input.glob("archify-*.html")) if args.input.is_dir() else [args.input]
        if not paths:
            raise ValueError("No archify-*.html files found")
        results = [audit_file(p, fixes.get(p.stem.removeprefix("archify-"), {})) for p in paths]
        totals = {"files": len(results), "conflicting_pairs": sum(r["conflicting_pair_count"] for r in results),
                  "node_crossings": sum(r["node_crossing_count"] for r in results)}
        ok = not totals["conflicting_pairs"] and not totals["node_crossings"]
        print(json.dumps({"ok": ok, "in_memory_overrides": bool(args.fixes),
                          "totals": totals, "files": results}, indent=2))
        return 0 if ok else 1
    except (ValueError, KeyError, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
