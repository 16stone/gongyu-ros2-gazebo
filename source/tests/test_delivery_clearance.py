import json,math,tempfile,unittest
from pathlib import Path
import yaml
from freeze_g2 import g2_card
from freeze_delivery_clearance import clearance_card
from gongyu.physical_world import PhysicalWorld
from gongyu.world import load_card


class DeliveryClearance(unittest.TestCase):
    def test_complete_card_loads_with_frozen_graph_edge_lengths(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'card.json';p.write_text(json.dumps(clearance_card()))
            self.assertEqual(load_card(p)['version'],'G2-D-clearance-development-v2.1')

    def test_invalid_physical_waypoint_is_rejected_before_dispatch(self):
        c=clearance_card();c['physical_delivery_waypoint']=[1.,float('nan'),.3]
        with self.assertRaises(ValueError):PhysicalWorld(c,'invalid_via',lambda *a:None,release_arrival=lambda *a:True)

    def test_parked_peers_and_west_exit_have_clearance_without_relaxing_tasks(self):
        c=clearance_card();old=g2_card();positions=c['physical_berths']['D']
        for name in ('tasks','geometry','travel_time_ms','end_ms','tau_ms','message_delay_ms','service_ms','physical_berth_tolerance_m'):
            self.assertEqual(c[name],old[name])
        self.assertGreaterEqual(min(math.dist(a,b) for i,a in enumerate(positions) for b in positions[i+1:]),1.8-1e-12)
        self.assertGreaterEqual(min(math.dist(p,[2.,0.]) for p in positions),1.5-1e-12)

    def test_west_entry_turn_uses_clear_exterior_alignment_and_preserves_arrival_gate(self):
        for source,target in [('W','E'),('E','W')]:
            card=clearance_card();card['physical_channel_west_alignment']=[1.6,0.,.3]
            card['fleet']['R1']['node']=source;sent=[]
            w=PhysicalWorld(card,'west_clearance',lambda *a,**kw:sent.append((a,kw)),release_arrival=lambda *a:True)
            w.receive_pose('R1',w.reference_position('R1',source),0.,0.,0)
            self.assertTrue(w.start_move('R1',target));args,kwargs=sent[-1];points=args[2]
            self.assertIn((1.6,0.,.3),[tuple(p) for p in points])
            if target=='W':self.assertEqual(points[kwargs['arrival_gate_before']-1],(5.,0.,.3))
            west=[p for p in points if p[0]<2.1]
            for a,b in zip(west,west[1:]):
                for i in range(101):
                    x,y=[a[j]+(b[j]-a[j])*i/100 for j in range(2)]
                    gap=math.hypot(max(2.35-x,0),max(.5-abs(y),abs(y)-.65,0))
                    # The .5m turn envelope also needs the .1m parking-error margin.
                    self.assertGreater(gap,.6,(source,target,x,y,gap))
            for peer in card['physical_berths']['D']:
                self.assertGreater(math.dist([1.6,0.],peer),.5+.22+.2)

    def test_nonfinite_west_alignment_is_rejected(self):
        c=clearance_card();c['physical_channel_west_alignment']=[1.6,float('nan'),.3]
        with self.assertRaises(ValueError):PhysicalWorld(c,'invalid_west',lambda *a:None,release_arrival=lambda *a:True)

    def test_declared_continuous_channel_reaches_the_ground_path_actuator(self):
        from gongyu.actuation import MoveDispatcher
        class Ground:
            state='IDLE'
            def __init__(self):self.singles=[];self.paths=[]
            def submit(self,*args):self.singles.append(args);self.state='ACTIVE'
            def submit_path(self,targets):self.paths.append(targets);self.state='ACTIVE'
        nav=Ground();card=clearance_card();card['physical_continuous_channel']=True
        d=MoveDispatcher(card['fleet'],{'R1':nav},lambda *args:None)
        d.arrival_owners['D']=('B1',99)
        w=PhysicalWorld(card,'continuous',d.begin,release_arrival=d.release_arrival)
        w.receive_pose('R1',w.reference_position('R1','E'),0.,0.,0)
        self.assertTrue(w.start_move('R1','W'))
        self.assertEqual(nav.singles,[]);self.assertEqual(nav.paths,[])
        self.assertEqual(d.pending['R1']['arrival_gate_before'],1)
        del d.arrival_owners['D']
        d.tick({'R1':dict(t=1.,xyz=w.reference_position('R1','E'))},1.)
        self.assertEqual(len(nav.paths),1);self.assertEqual(nav.paths[0][0][:2],(5.,0.))
        self.assertEqual(nav.singles,[]);self.assertFalse(d.done('R1',1))

    def test_W_to_D_staging_clears_parked_peers_and_reverse_stays_direct(self):
        card=clearance_card();card['fleet']['R1']['node']='W';sent=[]
        w=PhysicalWorld(card,'clearance_fixture',lambda *a,**kw:sent.append(a),release_arrival=lambda *a:True)
        for a in ('R2','B2'):w.berths.reserve(a,'D')
        w.receive_pose('R1',w.reference_position('R1','W'),0.,0.,0);self.assertTrue(w.start_move('R1','D'))
        points=sent[0][2];self.assertEqual(points[1],[1.8,1.5,.3])
        config=yaml.safe_load((Path(__file__).resolve().parents[1]/'ros/config/nav2_B1.yaml').read_text())['B1']
        polygon=json.loads(config['collision_monitor']['ros__parameters']['PeerStop']['rotation']['points'])
        radius=config['local_costmap']['local_costmap']['ros__parameters']['robot_radius']
        guard=max(math.hypot(*p) for p in polygon)+radius+2*.25
        for a,b in zip(points,points[1:]):
            for i in range(41):
                xy=[a[j]+(b[j]-a[j])*i/40 for j in range(2)]
                self.assertTrue(all(math.dist(xy,p)>guard for p in card['physical_berths']['D'][:3]))
        self.assertEqual(len(w.edge_points('B1','D','W')),2)


if __name__=='__main__':unittest.main()
