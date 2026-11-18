import json,math,tempfile,unittest
import xml.etree.ElementTree as E
import yaml
from pathlib import Path
from freeze_m2 import m2_card
from ros.prepare_mission_world import prepare
from gongyu.berths import Berths,physical_card
from gongyu.geometry import segment_hits_box


class MissionScene(unittest.TestCase):
    def test_navigation_cannot_substitute_a_nearby_endpoint_for_the_reserved_berth(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);prepare(root,m2_card())
            fleet=json.loads((root/'config/fleet.json').read_text())
            for actor in (a['id'] for a in fleet if a['mode']=='ground'):
                params=yaml.safe_load((root/f'config/nav2_{actor}.yaml').read_text())[actor]
                self.assertEqual(params['planner_server']['ros__parameters']['GridBased']['tolerance'],0.)
                self.assertLessEqual(params['controller_server']['ros__parameters']['goal_checker']['xy_goal_tolerance'],.08)
                for costmap,layer in [('local_costmap','voxel_layer'),('global_costmap','obstacle_layer')]:
                    layers=params[costmap][costmap]['ros__parameters']
                    for layer_name,scan in [(layer,'scan'),('peer_layer','peer_scan')]:
                        self.assertTrue(layers[layer_name][scan].get('inf_is_valid',False))

    def test_continuous_behavior_tree_is_copied_into_the_frozen_scene(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);prepare(root,m2_card())
            bt=E.parse(root/'config/axial_transit.xml').getroot()
            self.assertEqual(float(bt.find('.//RemovePassedGoals').get('radius')),.7)
            self.assertAlmostEqual(float(bt.find('.//RateController').get('hz')),.333)
            self.assertIsNotNone(bt.find('.//ComputePathThroughPoses'))
            self.assertIsNotNone(bt.find('.//FollowPath'))

    def test_generated_bounds_include_physical_parking_margin(self):
        card=physical_card(m2_card());card['physical_berths']['D'][0]=[-4.,0.]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);prepare(root,card)
            bounds=json.loads((root/'mission_scene.json').read_text())['bounds']
            self.assertLessEqual(bounds[0],-6.)

    def test_scene_covers_card_and_has_separate_initial_ground_berths(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);card=m2_card();prepare(root,card)
            fleet=json.loads((root/'config/fleet.json').read_text())
            berths=Berths(physical_card(card))
            for a in fleet:
                expected=berths.position(a['id'],card['fleet'][a['id']]['node'])
                self.assertEqual(a['initial_xyz'][:2],list(expected[:2]))
            e=[a['initial_xyz'] for a in fleet if a['id'] in ('R1','R2')]
            self.assertGreaterEqual(math.dist(*e),.79)
            receipt=json.loads((root/'mission_scene.json').read_text());xmin,ymin,xmax,ymax=receipt['bounds']
            self.assertTrue(all(xmin<x<xmax and ymin<y<ymax for x,y in card['nodes'].values()))
            self.assertEqual(receipt['obstacles'],card['geometry']['obstacles'])
            self.assertTrue((root/'config/nav_gui.config').is_file())
            world=E.parse(root/'worlds/fleet.sdf').getroot().find('world')
            meta=yaml.safe_load((root/'maps/nav_calibration.yaml').read_text())
            _,shape,_,pixels=(root/'maps/nav_calibration.pgm').read_bytes().split(b'\n',3)
            width,height=map(int,shape.split())
            for obstacle in card['geometry']['obstacles']:
                center=[(a+b)/2 for a,b in zip(obstacle['minimum'],obstacle['maximum'])]
                actual=list(map(float,world.find(f'model[@name="{obstacle["id"]}"]/pose').text.split()))
                self.assertEqual(actual[:3],center)
                col=int((center[0]-meta['origin'][0])/meta['resolution'])
                row=height-1-int((center[1]-meta['origin'][1])/meta['resolution'])
                self.assertEqual(pixels[row*width+col],0)

    def test_east_parking_protection_envelope_clears_tunnel_walls(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);prepare(root,m2_card());card=json.loads((root/'scenario.json').read_text())
            world=E.parse(root/'worlds/fleet.sdf').getroot().find('world');walls=[]
            for model in world.findall('model'):
                if model.get('name','').startswith('channel_wall_'):
                    p=list(map(float,model.find('pose').text.split()))
                    size=list(map(float,model.find('link/collision/geometry/box/size').text.split()))
                    walls.append(([p[i]-size[i]/2 for i in range(3)],[p[i]+size[i]/2 for i in range(3)]))
            config=yaml.safe_load((root/'config/nav2_R1.yaml').read_text())
            polygon=json.loads(config['R1']['collision_monitor']['ros__parameters']['PeerStop']['rotation']['points'])
            for x,y in card['physical_berths']['E']:
                heading=math.atan2(y,x-5.6)
                for i in range(72):
                    dx=.1*math.cos(i*math.pi/36);dy=.1*math.sin(i*math.pi/36)
                    for da in (-.25,0,.25):
                        yaw=heading+da
                        ps=[(x+dx+u*math.cos(yaw)-v*math.sin(yaw),y+dy+u*math.sin(yaw)+v*math.cos(yaw),.1) for u,v in polygon]
                        self.assertFalse(any(segment_hits_box(a,b,mn,mx) for a,b in zip(ps,ps[1:]+ps[:1]) for mn,mx in walls),(x,y,i,da))

    def test_information_parking_clears_static_envelope_and_east_departure_peer_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);prepare(root,m2_card());card=json.loads((root/'scenario.json').read_text())
            config=yaml.safe_load((root/'config/nav2_R1.yaml').read_text())
            polygon=json.loads(config['R1']['collision_monitor']['ros__parameters']['PeerStop']['rotation']['points'])
            radius=config['R1']['local_costmap']['local_costmap']['ros__parameters']['robot_radius']
            guard_radius=max(math.hypot(*p) for p in polygon)
            world=E.parse(root/'worlds/fleet.sdf').getroot().find('world')
            for x,y in card['physical_berths']['L']:
                for model in world.findall('model'):
                    collision=model.find('link/collision/geometry/box/size')
                    if collision is None or model.get('name')=='ground_plane':continue
                    p=list(map(float,model.find('pose').text.split()));size=list(map(float,collision.text.split()))
                    gap=math.hypot(max(abs(x-p[0])-size[0]/2,0),max(abs(y-p[1])-size[1]/2,0))
                    self.assertGreater(gap,guard_radius+.1,(x,y,model.get('name')))
            forward=json.loads(config['R1']['collision_monitor']['ros__parameters']['PeerStop']['forward']['points'])
            def clearance(position,yaw,peer,polygon=forward):
                dx,dy=peer[0]-position[0],peer[1]-position[1]
                x=dx*math.cos(yaw)+dy*math.sin(yaw);y=-dx*math.sin(yaw)+dy*math.cos(yaw)
                crosses=[(b[0]-a[0])*(y-a[1])-(b[1]-a[1])*(x-a[0]) for a,b in zip(polygon,polygon[1:]+polygon[:1])]
                if all(c>=0 for c in crosses) or all(c<=0 for c in crosses):return 0.
                distances=[]
                for a,b in zip(polygon,polygon[1:]+polygon[:1]):
                    vx,vy=b[0]-a[0],b[1]-a[1]
                    t=max(0.,min(1.,((x-a[0])*vx+(y-a[1])*vy)/(vx*vx+vy*vy)))
                    distances.append(math.hypot(x-a[0]-t*vx,y-a[1]-t*vy))
                return min(distances)
            # Retain the observed phase15 counterexample before checking the new route.
            self.assertLess(clearance((5.399301136,.059829520),.202804529,(5.960005917,-.323509731)),radius)
            from gongyu.physical_world import PhysicalWorld
            sent=[];w=PhysicalWorld(card,'guard',lambda *a:sent.append(a))
            source=w.berths.position('R1','E');w.receive_pose('R1',source,0.,0.,0)
            self.assertTrue(w.start_move('R1','W'));points=sent[-1][2]
            previous_yaw=0.
            for a,b in zip(points,points[1:]):
                yaw=math.atan2(b[1]-a[1],b[0]-a[0])
                for i in range(41):
                    position=[a[j]+(b[j]-a[j])*i/40 for j in range(2)]
                    turn=previous_yaw+(yaw-previous_yaw)*i/40
                    for peer in card['physical_berths']['L']:
                        self.assertGreater(clearance(position,yaw,peer),radius+.2)
                        self.assertGreater(clearance(a,turn,peer,polygon),radius+.2)
                previous_yaw=yaw

    def test_east_entry_guard_clears_the_other_E_peer_with_both_position_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);prepare(root,m2_card());card=json.loads((root/'scenario.json').read_text())
            config=yaml.safe_load((root/'config/nav2_R1.yaml').read_text())
            polygon=json.loads(config['R1']['collision_monitor']['ros__parameters']['PeerStop']['rotation']['points'])
            envelope=max(math.hypot(*p) for p in polygon)
            radius=config['R1']['local_costmap']['local_costmap']['ros__parameters']['robot_radius']
            for x,y in card['physical_berths']['E']:
                # At the alignment goal, either E departure points toward the other parked peer.
                gap=abs(y)-2*card['physical_berth_tolerance_m']
                self.assertGreater(gap,envelope+radius,(x,y,gap,envelope+radius))

    def test_west_alignment_has_turning_clearance_from_D_and_parked_W_peer(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);base=m2_card();base['fleet']['B1']['node']='W';base['fleet']['R1']['node']='D'
            prepare(root,base);card=json.loads((root/'scenario.json').read_text())
            from gongyu.physical_world import PhysicalWorld
            sent=[];w=PhysicalWorld(card,'west',lambda *a:sent.append(a))
            p=w.reference_position('R2','E');w.receive_pose('R2',p,0.,0.,0);self.assertTrue(w.start_move('R2','W'))
            alignment=sent[-1][2][-2];self.assertEqual(alignment,(2.,0.,.3))
            config=yaml.safe_load((root/'config/nav2_R2.yaml').read_text())
            polygon=json.loads(config['R2']['collision_monitor']['ros__parameters']['PeerStop']['rotation']['points'])
            envelope=max(math.hypot(*p) for p in polygon)
            radius=config['R2']['local_costmap']['local_costmap']['ros__parameters']['robot_radius']
            peers=card['physical_berths']['D']+[list(w.reference_position('B1','W')[:2])]
            for peer in peers:self.assertGreater(math.dist(alignment[:2],peer),envelope+radius+.2,peer)
            observed_D=(1.117328902,.058023593)
            self.assertGreater(math.dist(alignment[:2],observed_D),envelope+radius+.1)
            world=E.parse(root/'worlds/fleet.sdf').getroot().find('world')
            for model in world.findall('model'):
                if not model.get('name','').startswith('channel_wall_'):continue
                p=list(map(float,model.find('pose').text.split()));size=list(map(float,model.find('link/collision/geometry/box/size').text.split()))
                gap=math.hypot(max(abs(alignment[0]-p[0])-size[0]/2,0),max(abs(alignment[1]-p[1])-size[1]/2,0))
                self.assertGreater(gap,envelope+.1)


if __name__=='__main__':unittest.main()
