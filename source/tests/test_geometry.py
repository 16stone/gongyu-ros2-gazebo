import unittest
from gongyu.geometry import Geometry,segment_hits_box,path_length,default_geometry


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.g=Geometry(default_geometry())

    def test_visibility_is_geometric_and_capability_based(self):
        self.assertTrue(self.g.can_observe((8,2,.3),'ground'))
        self.assertFalse(self.g.can_observe((6,0,.3),'ground'))
        self.assertFalse(self.g.can_observe((6,2,.3),'ground'))
        self.assertTrue(self.g.can_observe((6,8,2.5),'air'))
        self.assertFalse(self.g.can_observe((10,8,2.5),'air'))
        self.assertFalse(self.g.can_observe((14,8,2.5),'air'))

    def test_radio_and_vision_have_separate_obstacles(self):
        l=(6,0,.3)
        self.assertFalse(self.g.radio((8,2,.3),l))
        self.assertTrue(self.g.radio((6,2,.3),l))
        self.assertTrue(self.g.radio((10,8,2.5),l))
        self.assertTrue(self.g.radio((6,8,2.5),l))
        self.assertFalse(self.g.radio((14,8,2.5),l))

    def test_fov_and_slab_boundary(self):
        self.assertFalse(self.g.can_observe((8,2,.3),'ground',yaw=90))
        self.assertTrue(self.g.can_observe((8,2,.3),'ground',yaw=-90))
        self.assertTrue(segment_hits_box((0,1,0),(2,1,0),(1,0,-1),(1.2,1,1)))
        self.assertFalse(segment_hits_box((0,2,0),(2,2,0),(1,0,-1),(1.2,1,1)))

    def test_bypass_has_actual_twelve_meter_polyline(self):
        self.assertAlmostEqual(path_length([(1,0,.3),(1,-3.5,.3),(6,-3.5,.3),(6,0,.3)]),12)

    def test_removing_wall_legally_enables_local_observation(self):
        config=default_geometry()
        config['obstacles']=[o for o in config['obstacles'] if o['id']!='device_screen']
        self.assertTrue(Geometry(config).can_observe((6,0,.3),'ground'))

    def card(self,visible=False):
        import json
        from pathlib import Path
        from freeze_geometry import geometry_card
        base=json.loads((Path(__file__).resolve().parents[1]/'scenarios/M1.json').read_text())
        return geometry_card(base,visible)

    def test_world_uses_geometry_for_every_ground_observer(self):
        from gongyu.world import World
        w=World(self.card(),'sensing')
        with self.assertRaises(ValueError):
            w.service('B1','observe')
        w.poses['B1']='O'
        w.service('B1','observe')
        w.advance(2000)
        self.assertEqual(w.mission.reports['B1','device'].observation_region,'O')

    def test_bypass_trajectory_follows_polyline(self):
        from gongyu.world import World
        w=World(self.card(),'path')
        w.start_move('B1','L',0)
        w.advance(6000)
        p=next(p for p in w.trajectories if p['actor']=='B1')
        self.assertAlmostEqual(p['x'],1)
        self.assertAlmostEqual(p['y'],-3)
        self.assertAlmostEqual(p['z'],.3)

    def test_visible_loading_is_a_legal_simple_candidate(self):
        from gongyu.run import simulate
        from gongyu.planning import propose
        from gongyu.model import Decision
        from unittest.mock import patch
        def self_candidate(view,policy):
            decision=propose(view,'P0')
            candidate=next(c for c in decision.candidates if c['id']=='001')
            self.assertTrue(candidate['legal'])
            return Decision('001',decision.candidates,decision.elapsed_ms)
        with patch('gongyu.adaptive.propose',self_candidate):
            r=simulate(self.card(True),'P0')
        loads=[e for e in r.events if e.kind=='load_started']
        self.assertTrue(loads)
        self.assertTrue(all(e.payload['report']['observation_region']=='L' for e in loads))
        self.assertEqual(r.metrics['constraint_violations'],[])

if __name__=='__main__':
    unittest.main()
