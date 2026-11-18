import json,math,unittest
from pathlib import Path
import yaml

class RecoverySafetyConfig(unittest.TestCase):
    def test_direction_guards_keep_old_clearance_and_cover_navigation_speeds(self):
        card=yaml.safe_load((Path(__file__).resolve().parents[1]/'ros/config/nav2_B1.yaml').read_text())['B1']
        behavior=card['behavior_server']['ros__parameters']
        self.assertEqual(behavior.get('local_frame'),'B1/odom')
        monitor=card['collision_monitor']['ros__parameters'];guard=monitor['PeerStop']
        self.assertEqual(guard['type'],'velocity_polygon')
        self.assertEqual(monitor['observation_sources'],['scan','peer_scan'])
        self.assertTrue(monitor['FootprintApproach']['enabled'])
        self.assertEqual(guard['action_type'],'stop');self.assertEqual(guard['velocity_polygons'][-1],'fallback')
        expected=[[0.,.32],[.38,.32],[.38,-.32],[0.,-.32]]
        self.assertEqual(json.loads(guard['forward']['points']),expected)
        self.assertEqual(json.loads(guard['backward']['points']),[[-x,y] for x,y in expected])
        for name in ('rotation','fallback'):
            points=json.loads(guard[name]['points'])
            old_radius=math.hypot(.38,.32)
            self.assertLessEqual(max(math.hypot(*q) for q in points),.501)
            for a,b in zip(points,points[1:]+points[:1]):
                inradius=abs(a[0]*b[1]-a[1]*b[0])/math.dist(a,b)
                self.assertGreaterEqual(inradius,old_radius)
        for v in (-.5,-.01,0.,.01,.5,2.):
            for w in (-1.,0.,1.):
                self.assertTrue(any(guard[n]['linear_min']<=v<=guard[n]['linear_max'] and guard[n]['theta_min']<=w<=guard[n]['theta_max'] for n in guard['velocity_polygons']))
