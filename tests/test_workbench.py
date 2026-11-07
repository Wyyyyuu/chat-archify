"""Presentation must preserve source topology and reject unsupported navigation."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from workbench_data import navigation_data, vertical_layout, validate_groups, initial_target
from branch_layout import branch_layout


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.record={'nodes':[{'id':x,'title':x,'status':'completed'} for x in ['a','b','c']],
                     'edges':[{'from':'a','to':'b','type':'adds','confidence':'explicit','reason':'recorded'},
                              {'from':'a','to':'c','type':'branches','confidence':'inferred','reason':'supported inference'}]}
        self.packed=[{'id':'overview','label':'Overview','record':self.record}]
        self.manifest={'navigation':{'source_chapter':'overview',
            'items':[{'id':x,'chapter':'overview','node':x,'lane':lane,'order':i} for i,(x,lane) in enumerate([('a',0),('b',0),('c',1)])],
            'edges':copy.deepcopy(self.record['edges'])}}

    def test_source_status_and_relationships_are_retained(self):
        self.manifest['navigation']['items'][0]['status']='failed'
        nav=navigation_data(self.manifest,self.packed)
        self.assertEqual(nav['items'][0]['status'],'completed')
        self.assertEqual(nav['edges'],self.record['edges'])
        self.assertEqual(nav['source_chapter'],'overview')

    def test_no_metadata_creates_independent_entries(self):
        self.assertEqual(navigation_data({},self.packed)['edges'],[])

    def test_unknown_target_is_rejected(self):
        self.manifest['navigation']['items'][0]['node']='missing'
        with self.assertRaisesRegex(ValueError,'target'):navigation_data(self.manifest,self.packed)

    def test_unsupported_relationship_is_rejected(self):
        self.manifest['navigation']['edges'][0]['type']='merges'
        with self.assertRaisesRegex(ValueError,'unsupported'):navigation_data(self.manifest,self.packed)

    def test_omitted_relationship_is_rejected(self):
        self.manifest['navigation']['edges'].pop()
        with self.assertRaisesRegex(ValueError,'omits'):navigation_data(self.manifest,self.packed)

    def test_groups_do_not_duplicate_or_drop_resource_indices(self):
        node={'artifacts':[{},{}],'change_groups':[{'title':'Feature','summary':'One change','artifact_indices':[0,1]}]}
        validate_groups(node)
        node['change_groups'].append({'title':'Duplicate','summary':'','artifact_indices':[1]})
        with self.assertRaisesRegex(ValueError,'repeated'):validate_groups(node)

    def test_start_requires_existing_node(self):
        with self.assertRaisesRegex(ValueError,'start'):initial_target({'start':{'chapter':'overview','node':'no'}},self.packed)

    def test_unequal_fork_keeps_every_event_and_relationship(self):
        record={'nodes':[{'id':x} for x in ['a','b','c','d','e','f']],
                'edges':[{'from':a,'to':b,'type':'adds','confidence':'explicit','reason':'recorded'}
                         for a,b in [('a','b'),('b','c'),('b','d'),('d','e'),('c','f'),('e','f')]]}
        before=copy.deepcopy(record)
        layout=branch_layout(record)
        self.assertEqual(record,before)
        self.assertEqual(layout['audit'],{'nodes':6,'edges':6,'crossings':0,'node_crossings':0})
        self.assertEqual([{k:v for k,v in edge.items() if k not in ('id','points')} for edge in layout['edges']],record['edges'])
        nodes={n['id']:n for n in layout['nodes']}
        self.assertEqual(nodes['c']['y'],nodes['d']['y'])
        self.assertNotEqual(nodes['c']['x'],nodes['d']['x'])
        self.assertGreater(nodes['f']['y'],nodes['e']['y'])

    def test_unjoined_or_ambiguous_forks_keep_checked_fallback(self):
        self.assertIsNone(branch_layout(self.record))
        layout=vertical_layout(b'',self.record,prefer_branches=True)
        self.assertEqual(layout['strategy'],'compact-vertical')
        self.assertEqual(len(layout['nodes']),3)
        self.assertEqual(len(layout['edges']),2)

    def test_compact_geometry_retains_full_topology(self):
        viewer=b'''<svg><g data-node-id="a"><rect x="0" y="0" width="100" height="60"/></g>
        <g data-node-id="b"><rect x="200" y="0" width="100" height="60"/></g>
        <g data-node-id="c"><rect x="200" y="120" width="100" height="60"/></g>
        <path data-edge-id="ab" data-edge-from="a" data-edge-to="b" d="M 100 20 L 200 20"/>
        <path data-edge-id="ac" data-edge-from="a" data-edge-to="c" d="M 100 45 L 140 45 L 140 150 L 200 150"/></svg>'''
        layout=vertical_layout(viewer,self.record)
        self.assertEqual([(e['from'],e['to']) for e in layout['edges']],[('a','b'),('a','c')])
        self.assertEqual(layout['audit'],{'nodes':3,'edges':2,'crossings':0,'node_crossings':0})
        self.assertGreater(layout['nodes'][1]['y'],layout['nodes'][0]['y'])
        self.assertEqual(layout['edges'][1]['confidence'],'inferred')
        self.assertLessEqual(layout['width'],300)
        self.assertEqual(layout['strategy'],'compact-vertical')


if __name__=='__main__':unittest.main()
