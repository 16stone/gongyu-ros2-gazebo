import unittest
from unittest.mock import Mock
from freeze_m2 import m2_card
from gongyu.actuation import MoveDispatcher
from gongyu.physical_world import PhysicalWorld
from tests.test_actuation import Nav


class ArrivalGate(unittest.TestCase):
    def test_first_move_waiter_retries_without_previous_nav_goal(self):
        nav={a:Nav() for a in ('B1','B2')};d=MoveDispatcher({a:{'mode':'ground'} for a in nav},nav,lambda *a:None)
        for a in nav:d.begin(a,1,[(0,0,0),(1,0,0)],arrival_region='D',arrival_gate_before=1)
        self.assertEqual(len(nav['B2'].goals),0)
        nav['B1'].state='SUCCEEDED_NAV2';d.tick({},.1);self.assertTrue(d.release_arrival('B1',1))
        d.tick({},.2)
        self.assertEqual(len(nav['B2'].goals),1);self.assertEqual(d.arrival_owners['D'],('B2',1))

    def test_final_approaches_are_fifo_and_claim_survives_W_to_D_transfer(self):
        nav={a:Nav() for a in ('B1','B2','R1')};d=MoveDispatcher({a:{'mode':'ground'} for a in nav},nav,lambda *a:None)
        d.begin('B1',1,[(0,0,0),(1,0,0)],arrival_region='D',arrival_gate_before=1)
        d.begin('B2',1,[(0,2,0),(1,2,0),(2,2,0)],arrival_region='D',arrival_gate_before=2)
        d.begin('R1',1,[(0,1,0),(1,1,0),(2,1,0),(3,1,0)],arrival_region='D',arrival_gate_before=2)
        nav['R1'].state='SUCCEEDED_NAV2';d.tick({},.1)
        nav['B2'].state='SUCCEEDED_NAV2';d.tick({},.2)
        self.assertEqual(len(nav['R1'].goals),1);self.assertEqual(len(nav['B2'].goals),1)
        self.assertFalse(d.done('R1',1));self.assertFalse(d.release_arrival('B1',1))
        nav['B1'].state='SUCCEEDED_NAV2';d.tick({},.3);self.assertTrue(d.release_arrival('B1',1));d.tick({},.4)
        self.assertEqual(len(nav['R1'].goals),2);self.assertEqual(len(nav['B2'].goals),1)
        nav['R1'].state='SUCCEEDED_NAV2';d.tick({},.5);nav['R1'].state='SUCCEEDED_NAV2';d.tick({},.6)
        self.assertTrue(d.done('R1',1))
        d.begin('R1',2,[(3,1,0),(4,1,0)],arrival_region='D',arrival_gate_before=1)
        self.assertFalse(d.release_arrival('R1',1));self.assertFalse(d.release_arrival('R1',2));self.assertEqual(len(nav['B2'].goals),1)
        nav['R1'].state='SUCCEEDED_NAV2';d.tick({},.7);self.assertTrue(d.release_arrival('R1',2));d.tick({},.8)
        self.assertEqual(len(nav['B2'].goals),2)

    def test_world_releases_only_after_real_success_and_continuous_dwell(self):
        card=m2_card();card['fleet']['R1']['node']='W';card['physical_arrival_mutex_nodes']=['D'];sent=[];release=Mock(return_value=True)
        w=PhysicalWorld(card,'arrival_fixture',lambda *a,**kw:sent.append((a,kw)),release_arrival=release)
        w.receive_pose('R1',w.reference_position('R1','W'),0.,0.,0)
        self.assertTrue(w.start_move('R1','D'));token=sent[0][0][1];self.assertEqual(sent[0][1]['arrival_region'],'D')
        target=w.reference_position('R1','D');w.advance(10000);release.assert_not_called()
        for t in range(10100,11100,100):
            w.advance(t);w.receive_pose('R1',target,0.,0.,t,token,True)
        release.assert_not_called();self.assertIsNone(w.poses['R1'])
        w.advance(11100);w.receive_pose('R1',target,0.,0.,11100,token,True);w.advance(11200)
        release.assert_called_once_with('R1',token);self.assertEqual(w.poses['R1'],'D')

    def test_air_and_earlier_long_edge_waypoints_remain_parallel(self):
        nav=Nav();fleet={'B1':{'mode':'ground'},'B3':{'mode':'air'}};d=MoveDispatcher(fleet,{'B1':nav},lambda *a:None)
        d.begin('B1',1,[(0,0,0),(1,0,0)],arrival_region='D',arrival_gate_before=1)
        d.begin('B3',1,[(0,0,0),(0,0,2)])
        for i in range(12):
            t=i/10;d.tick({'B3':dict(t=t,xyz=(0,0,2),yaw=0.,speed=0.,wz=0.)},t)
        self.assertTrue(d.done('B3',1));self.assertFalse(d.done('B1',1))


if __name__=='__main__':unittest.main()
