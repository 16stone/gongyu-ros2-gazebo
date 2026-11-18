import unittest
from gongyu.actuation import MoveDispatcher


class Nav:
    def __init__(self):self.state='IDLE';self.goals=[]
    def submit(self,x,y,yaw):self.goals.append((x,y,yaw));self.state='ACTIVE'


class Dispatch(unittest.TestCase):
    def test_continuous_channel_action_waits_for_D_gate_and_has_no_interior_goal_results(self):
        class PathNav(Nav):
            def __init__(self):super().__init__();self.paths=[]
            def submit_path(self,targets):self.paths.append(targets);self.state='ACTIVE'
        nav=PathNav();d=MoveDispatcher({'R2':{'mode':'ground'}},{'R2':nav},lambda *a:None)
        route=[(5.25,.95,.3),(5.,0.,.3),(4.,0.,.3),(3.,0.,.3),(2.,0.,.3),(1.6,0.,.3),(1.8,.95,.3)]
        d.arrival_owners['D']=('R1',1)
        d.begin('R2',1,route,arrival_region='D',arrival_gate_before=2,continuous_ground=True)
        self.assertEqual(len(nav.goals),1);self.assertEqual(nav.paths,[])
        nav.state='SUCCEEDED_NAV2';d.tick({'R2':dict(t=1.,xyz=(5.,0.,.3))},1.)
        self.assertEqual(nav.paths,[]);self.assertTrue(d.pending['R2']['waiting_arrival'])
        del d.arrival_owners['D'];d.tick({'R2':dict(t=1.1,xyz=(5.,0.,.3))},1.1)
        self.assertEqual(len(nav.paths),1);self.assertEqual(len(nav.paths[0]),5)
        self.assertEqual(nav.paths[0][0][:2],(4.,0.));self.assertEqual(nav.paths[0][-1][:2],(1.8,.95))
        self.assertEqual(len(nav.goals),1,'interior points must not become stop-and-turn NavigateToPose goals')
        self.assertFalse(d.done('R2',1));nav.state='SUCCEEDED_NAV2'
        d.tick({'R2':dict(t=2.,xyz=route[-1])},2.)
        self.assertTrue(d.done('R2',1));self.assertEqual(d.arrival_owners['D'],('R2',1))

    def test_continuous_path_rejects_an_air_actuator_before_dispatch(self):
        d=MoveDispatcher({'B3':{'mode':'air'}},{},lambda *a:None)
        with self.assertRaises(ValueError):d.begin('B3',1,[(0,0,2),(1,0,2)],continuous_ground=True)
        self.assertNotIn('B3',d.pending)

    def test_ground_waypoints_wait_for_actual_result_and_tokens_are_isolated(self):
        nav=Nav();d=MoveDispatcher({'B1':{'mode':'ground'}},{'B1':nav},lambda *a:None)
        d.begin('B1',4,[(0,0,.3),(1,0,.3),(2,0,.3)])
        d.tick({},0.)
        self.assertEqual(len(nav.goals),1);self.assertFalse(d.done('B1',4))
        nav.state='SUCCEEDED_NAV2';d.tick({},.1)
        self.assertEqual(len(nav.goals),2);self.assertFalse(d.done('B1',4))
        nav.state='SUCCEEDED_NAV2';d.tick({},.2)
        self.assertTrue(d.done('B1',4));self.assertFalse(d.done('B1',3))

    def test_aircraft_are_independent_and_do_not_finish_on_elapsed_time(self):
        fleet={a:{'mode':'air'} for a in ('B3','R5')};sent=[];d=MoveDispatcher(fleet,{},lambda *a:sent.append(a))
        for a in fleet:d.begin(a,1,[(0,0,0),(0,0,2)])
        def s(t,z):return dict(t=t,xyz=(0,0,z),speed=0.,wz=0.,yaw=0.)
        for t in (0.,.1,.2,.3,.4,.5,.6,.7,.8,.9,1.,1.1):d.tick({'B3':s(t,2.),'R5':s(t,0.)},t)
        self.assertTrue(d.done('B3',1));self.assertFalse(d.done('R5',1));self.assertTrue(sent)

    def test_air_success_survives_missing_feedback_for_next_goal(self):
        sent=[];d=MoveDispatcher({'B3':{'mode':'air'}},{},lambda *a:sent.append(a))
        d.begin('B3',24,[(0,0,2),(1,0,2)])
        for t in (0.,.5,1.):
            d.tick({'B3':dict(t=t,xyz=(1,0,2),speed=0.,wz=0.,yaw=0.)},t)
        self.assertTrue(d.done('B3',24))
        d.tick({},1.1)
        self.assertEqual(sent[-1][1],(0.,0.,0.,0.))
        self.assertTrue(d.done('B3',24))
        with self.assertRaises(RuntimeError):d.begin('B3',24,[(1,0,2),(0,0,2)])
        d.begin('B3',25,[(1,0,2),(0,0,2)])
        self.assertFalse(d.done('B3',24));self.assertFalse(d.done('B3',25))
        d.tick({},1.2)
        with self.assertRaises(RuntimeError):d.begin('B3',26,[(1,0,2),(0,0,2)])

    def test_intermediate_pose_faces_next_segment_and_final_pose_keeps_arrival_heading(self):
        import math
        nav=Nav();d=MoveDispatcher({'B1':{'mode':'ground'}},{'B1':nav},lambda *a:None)
        d.begin('B1',1,[(0,0,0),(1,0,0),(1,1,0)])
        self.assertAlmostEqual(nav.goals[0][2],math.pi/2)
        nav.state='SUCCEEDED_NAV2';d.tick({'B1':dict(t=1.,xyz=(1,0,0))},1.)
        self.assertAlmostEqual(nav.goals[-1][2],math.pi/2)

    def test_rejected_navigation_is_not_relabelled_as_success(self):
        nav=Nav();d=MoveDispatcher({'R1':{'mode':'ground'}},{'R1':nav},lambda *a:None)
        d.begin('R1',1,[(0,0,0),(1,0,0)]);nav.state='ABORTED'
        with self.assertRaises(RuntimeError):d.tick({},1.)

    def test_ground_failure_stops_air_commands_before_propagating(self):
        nav=Nav();sent=[];fleet={'B1':{'mode':'ground'},'B3':{'mode':'air'},'R5':{'mode':'air'}}
        d=MoveDispatcher(fleet,{'B1':nav},lambda *a:sent.append(a))
        for a in fleet:d.begin(a,1,[(0,0,0),(1,0,2 if a!='B1' else 0)])
        nav.state='ABORTED'
        with self.assertRaises(RuntimeError):d.tick({},1.)
        self.assertEqual({a for a,v in sent},{'B3','R5'})
        self.assertTrue(all(v==(0.,0.,0.,0.) for a,v in sent))

    def test_six_entity_snapshot_keeps_all_completion_states_separate(self):
        ground={a:Nav() for a in ('B1','B2','R1','R2')}
        fleet={**{a:{'mode':'ground'} for a in ground},**{a:{'mode':'air'} for a in ('B3','R5')}}
        d=MoveDispatcher(fleet,ground,lambda *a:None)
        for a in fleet:d.begin(a,1,[(0,0,0),(1,0,0)])
        ground['R1'].state='SUCCEEDED_NAV2'
        for t in (0.,.1,.2,.3,.4,.5,.6,.7,.8,.9,1.,1.1):
            d.tick({a:dict(t=t,xyz=(1,0,0) if a=='B3' else (0,0,0),speed=0.,wz=0.,yaw=0.) for a in ('B3','R5')},t)
        self.assertEqual({a for a in fleet if d.done(a,1)},{'R1','B3'})

    def test_ground_success_with_residual_error_dispatches_real_correction(self):
        nav=Nav();d=MoveDispatcher({'B1':{'mode':'ground'}},{'B1':nav},lambda *a:None)
        d.begin('B1',1,[(0,0,0),(1,0,0)]);nav.state='SUCCEEDED_NAV2'
        s=dict(t=1.,xyz=(.89,0,0),speed=0.,wz=0.,yaw=0.)
        d.tick({'B1':s},1.)
        self.assertEqual(len(nav.goals),2);self.assertFalse(d.done('B1',1))
        nav.state='SUCCEEDED_NAV2';s.update(t=1.1,xyz=(.95,0,0));d.tick({'B1':s},1.1)
        self.assertTrue(d.done('B1',1));self.assertEqual(len(nav.goals),2)

    def test_stale_pose_cannot_trigger_correction_and_retries_are_bounded(self):
        nav=Nav();d=MoveDispatcher({'B1':{'mode':'ground'}},{'B1':nav},lambda *a:None)
        d.begin('B1',1,[(0,0,0),(1,0,0)]);nav.state='SUCCEEDED_NAV2'
        s=dict(t=0.,xyz=(.8,0,0),speed=0.,wz=0.,yaw=0.);d.tick({'B1':s},1.)
        self.assertEqual(len(nav.goals),1)
        for t in (1.,1.1,1.2):
            nav.state='SUCCEEDED_NAV2';s['t']=t;d.tick({'B1':s},t)
        nav.state='SUCCEEDED_NAV2';s['t']=1.3
        with self.assertRaises(RuntimeError):d.tick({'B1':s},1.3)


if __name__=='__main__':unittest.main()
