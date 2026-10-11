#!/usr/bin/env python3
"""Portable package, topology, coverage, and embedded-byte regression checks."""
import argparse
import base64
import hashlib
import json
import re
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from check_routes import audit_file
from package_interactive import validate_viewer_relationships


def read_payload(path):
    page=Path(path).read_text(encoding='utf-8')
    match=re.search(r'<script type="application/json" id="explorer-data">([\s\S]*?)</script>',page)
    if not match:raise AssertionError('packaged HTML has no explorer-data payload')
    return json.loads(match.group(1))


class TopologyRegression(unittest.TestCase):
    def test_node_only_diagram_is_a_valid_zero_edge_audit(self):
        viewer='''<svg><g data-node-id="viewer-root" data-node-label="Root"><rect x="10" y="10" width="80" height="40" /></g></svg>'''
        with tempfile.TemporaryDirectory(prefix='chat-archify-empty-') as directory:
            path=Path(directory)/'archify-node-only.html';path.write_text(viewer,encoding='utf-8')
            result=audit_file(path)
        self.assertEqual(result['node_count'],1)
        self.assertEqual(result['edge_count'],0)
        self.assertEqual(result['conflicting_pair_count'],0)
        self.assertEqual(result['node_crossing_count'],0)

    def test_node_ids_must_match_for_the_interactive_bridge(self):
        record={'nodes':[{'id':'source-a','title':'Alpha'},{'id':'source-b','title':'Beta'}],
                'edges':[{'from':'source-a','to':'source-b'}]}
        viewer=b'''<svg>
          <g data-node-id="draw-a" data-node-label="Alpha"><rect x="0" y="0" width="40" height="30" /></g>
          <g data-node-id="draw-b" data-node-label="Beta"><rect x="100" y="0" width="40" height="30" /></g>
          <path data-edge-from="draw-a" data-edge-to="draw-b" data-edge-id="one" d="M 40 15 L 100 15" />
        </svg>'''
        with self.assertRaisesRegex(ValueError,'node IDs differ'):
            validate_viewer_relationships(record,viewer,'fixture')

    def test_missing_record_edge_is_rejected(self):
        record={'nodes':[{'id':'a','title':'Alpha'},{'id':'b','title':'Beta'}],
                'edges':[{'from':'a','to':'b'}]}
        viewer=b'''<svg>
          <g data-node-id="a" data-node-label="Alpha"><rect x="0" y="0" width="40" height="30" /></g>
          <g data-node-id="b" data-node-label="Beta"><rect x="100" y="0" width="40" height="30" /></g>
        </svg>'''
        with self.assertRaisesRegex(ValueError,'edge mismatch'):
            validate_viewer_relationships(record,viewer,'missing-edge')

    def test_reversed_edge_is_rejected(self):
        record={'nodes':[{'id':'a','title':'Alpha'},{'id':'b','title':'Beta'}],
                'edges':[{'from':'a','to':'b'}]}
        viewer=b'''<svg>
          <g data-node-id="a" data-node-label="Alpha"><rect x="0" y="0" width="40" height="30" /></g>
          <g data-node-id="b" data-node-label="Beta"><rect x="100" y="0" width="40" height="30" /></g>
          <path data-edge-from="b" data-edge-to="a" data-edge-key="reverse" d="M 100 15 L 40 15" />
        </svg>'''
        with self.assertRaisesRegex(ValueError,'edge mismatch'):
            validate_viewer_relationships(record,viewer,'reversed-edge')

    def test_extra_viewer_edge_is_rejected(self):
        record={'nodes':[{'id':'a','title':'Alpha'},{'id':'b','title':'Beta'}], 'edges':[]}
        viewer=b'''<svg>
          <g data-node-id="a" data-node-label="Alpha"><rect x="0" y="0" width="40" height="30" /></g>
          <g data-node-id="b" data-node-label="Beta"><rect x="100" y="0" width="40" height="30" /></g>
          <path data-edge-from="a" data-edge-to="b" data-edge-key="extra" d="M 40 15 L 100 15" />
        </svg>'''
        with self.assertRaisesRegex(ValueError,'edge mismatch'):
            validate_viewer_relationships(record,viewer,'extra-edge')

    def test_edge_multiplicity_is_checked(self):
        record={'nodes':[{'id':'a','title':'Alpha'},{'id':'b','title':'Beta'}],
                'edges':[{'from':'a','to':'b'},{'from':'a','to':'b'}]}
        viewer=b'''<svg>
          <g data-node-id="a" data-node-label="Alpha"><rect x="0" y="0" width="40" height="30" /></g>
          <g data-node-id="b" data-node-label="Beta"><rect x="100" y="0" width="40" height="30" /></g>
          <path data-edge-from="a" data-edge-to="b" data-edge-id="one" d="M 40 15 L 100 15" />
        </svg>'''
        with self.assertRaisesRegex(ValueError,'edge mismatch'):
            validate_viewer_relationships(record,viewer,'edge-multiplicity')


class DemoArtifactRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not getattr(cls,'html_path',None):raise RuntimeError('Pass --html to verify a generated demo package')
        cls.payload=read_payload(cls.html_path)
        cls.demo=cls.source_dir
        cls.viewer_path=cls.viewer

    def test_fictional_history_and_viewer_topology_are_complete(self):
        self.assertEqual(len(self.payload['chapters']),1)
        chapter=self.payload['chapters'][0]
        record=chapter['record']
        self.assertEqual(len(record['nodes']),5)
        self.assertEqual(len(record['edges']),5)
        self.assertIn('虚构',record['coverage'][0])
        viewer=base64.b64decode(chapter['viewer'],validate=True)
        self.assertEqual(hashlib.sha256(viewer).hexdigest(),chapter['viewer_sha256'])
        self.assertEqual(viewer,self.viewer_path.read_bytes())
        topology=validate_viewer_relationships(record,viewer,chapter['id'])
        self.assertEqual(topology['edge_count'],len(record['edges']))
        routes=audit_file(self.viewer_path)
        self.assertEqual(routes['node_count'],5)
        self.assertEqual(routes['edge_count'],5)
        self.assertEqual(routes['conflicting_pair_count'],0)
        self.assertEqual(routes['node_crossing_count'],0)

    def test_sources_turns_and_exact_node_matches_are_included(self):
        self.assertEqual(len(self.payload['conversations']),6)
        chapter=self.payload['chapters'][0]
        source=chapter['record']['sources'][0]
        self.assertEqual(len(source['conversation_entry_ids']),6)
        entries=self.payload['conversations']
        grouped=[entry for entry in entries if entry.get('turn_id')=='eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee5']
        self.assertEqual(len(grouped),2)
        self.assertEqual(len({entry['turn_group_id'] for entry in grouped}),1)
        self.assertTrue(all(not entry['original_url_verified'] for entry in entries))
        self.assertTrue(all(node['conversation_entry_ids'] for node in chapter['record']['nodes']))

    def test_four_markdown_snapshots_are_linked_and_byte_exact(self):
        chapter=self.payload['chapters'][0]
        file_by_name={item['name']:item for item in self.payload['files'].values()}
        expected={
            'reading-plan.md':self.demo/'resources'/'reading-plan.md',
            'daily-guide.md':self.demo/'resources'/'daily-guide.md',
            'review-checklist.md':self.demo/'resources'/'review-checklist.md',
            'source-brief.md':self.demo/'resources'/'source-brief.md',
            'conversation.md':self.demo/'conversation.md'
        }
        for name,source_path in expected.items():
            item=file_by_name[name]
            self.assertEqual(item['status'],'embedded')
            raw=base64.b64decode(item['data'],validate=True)
            self.assertEqual(raw,source_path.read_bytes())
            self.assertEqual(hashlib.sha256(raw).hexdigest(),item['sha256'])
        self.assertIn('review-checklist.md',file_by_name['reading-plan.md']['text'])
        self.assertIn('reading-plan.md',file_by_name['review-checklist.md']['text'])
        self.assertIn('蓝鲸书签',file_by_name['source-brief.md']['text'])
        source=next(item for item in chapter['record']['sources'] if item['id']=='source-brief')
        artifact=next(item for node in chapter['record']['nodes'] for item in node['artifacts'] if item['uri'].endswith('source-brief.md'))
        self.assertEqual(source['file_id'],artifact['file_id'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--html',required=True,type=Path)
    parser.add_argument('--source-dir',required=True,type=Path)
    parser.add_argument('--viewer',required=True,type=Path)
    args,remaining=parser.parse_known_args()
    DemoArtifactRegression.html_path=args.html.resolve()
    DemoArtifactRegression.source_dir=args.source_dir.resolve()
    DemoArtifactRegression.viewer=args.viewer.resolve()
    suite=unittest.TestSuite()
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(TopologyRegression))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(DemoArtifactRegression))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':sys.exit(main())
