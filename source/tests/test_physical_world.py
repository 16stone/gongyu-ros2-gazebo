import unittest
from freeze_m2 import m2_card
from gongyu.physical_world import PhysicalWorld


class PhysicalExecution(unittest.TestCase):
    def world(self):
        self.sent=[]
        return PhysicalWorld(m2_card(),'feedback_gate',lambda *args:self.sent.append(args))

    def pose(self,w,actor,xyz,t,token=None,success=False,speed=0.):
        w.advance(t)
        return w.receive_pose(actor,xyz,speed,0.,t,token,success)

    def test_nonberth_arrival_mutex_keeps_a_valid_two_point_gate(self):
        from gongyu.actuation import MoveDispatcher
        card=m2_card();card['physical_arrival_mutex_nodes']=['D']
        class Ground:
            state='IDLE'
            def submit(self,*args):self.state='PENDING'
        driver=MoveDispatcher(card['fleet'],{'R1':Ground()},lambda *args:None)
        w=PhysicalWorld(card,'no_berths',driver.begin,release_arrival=driver.release_arrival)
        self.pose(w,'R1',w.node_position('R1','E'),0)
        self.assertTrue(w.start_move('R1','W'))
        self.assertEqual(driver.pending['R1']['arrival_gate_before'],1)
        self.assertEqual(driver.arrival_owners['D'],('R1',1))

    def test_predicted_time_never_releases_actual_channel(self):
        w=self.world();self.pose(w,'R1',w.node_position('R1','E'),0)
        self.assertTrue(w.start_move('R1','W'))
        w.advance(20000)
        self.assertIsNone(w.poses['R1']);self.assertEqual(w.channel.occupant,'R1')
        self.assertIn('R1',w.busy)

    def test_arrival_requires_matching_goal_success_and_unbroken_fresh_dwell(self):
        w=self.world();self.pose(w,'R1',w.node_position('R1','E'),0);w.start_move('R1','W')
        token=self.sent[-1][1];target=w.node_position('R1','W')
        self.assertFalse(self.pose(w,'R1',target,1000,token+1,True))
        for t in range(1100,2200,100):self.pose(w,'R1',target,t,token,False)
        self.assertIsNone(w.poses['R1'])
        for t in range(2200,3300,100):self.pose(w,'R1',target,t,token,True)
        w.advance(3300);self.assertEqual(w.poses['R1'],'W');self.assertIsNone(w.channel.occupant)

    def test_air_arrival_waits_for_actuator_completion_after_a_short_feedback_gap(self):
        from gongyu.actuation import MoveDispatcher
        card=m2_card();actor='R5'
        d=MoveDispatcher({actor:card['fleet'][actor]},{},lambda *args:None)
        w=PhysicalWorld(card,'air_gap',d.begin)
        source=w.reference_position(actor,'F_R');target=w.reference_position(actor,'K_R')
        self.pose(w,actor,source,0)
        self.assertTrue(w.start_move(actor,'K_R'));token=w.moves[actor]['token']
        for t in range(1000,2100,100):
            w.advance(t)
            samples={} if t==1600 else {actor:dict(t=t/1000,xyz=target,speed=0.,wz=0.,yaw=0.)}
            d.tick(samples,t/1000)
            if samples:w.receive_pose(actor,target,0.,0.,t,token,d.done(actor,token))
        w.advance(2100)
        self.assertFalse(d.done(actor,token))
        self.assertIsNone(w.poses[actor], 'task arrival must not outrun the matching actuator result')
        self.assertIn(actor,w.busy)
        for t in range(2100,2900,100):
            w.advance(t);d.tick({actor:dict(t=t/1000,xyz=target,speed=0.,wz=0.,yaw=0.)},t/1000)
            w.receive_pose(actor,target,0.,0.,t,token,d.done(actor,token))
        w.advance(2900)
        self.assertEqual(w.poses[actor],'K_R')
        self.assertTrue(w.start_move(actor,'F_R'), 'a genuine completed token accepts the next move')

    def test_service_cannot_complete_from_clock_alone_or_across_missing_feedback(self):
        w=self.world();a='R5';p=w.node_position(a,w.poses[a]);self.pose(w,a,p,0)
        self.assertTrue(w.service(a,'inspect','red_return'))
        w.advance(5000);self.assertNotIn('red_return',w.completed)
        for t in range(5100,7200,100):self.pose(w,a,p,t)
        w.advance(7200);self.assertIn('red_return',w.completed)

    def test_missing_physical_feedback_does_not_preserve_radio_contact(self):
        w=self.world();self.pose(w,'B1',w.node_position('B1',w.poses['B1']),0)
        self.assertIsNotNone(w.radio_positions()['B1'])
        w.advance(300);self.assertIsNone(w.radio_positions()['B1'])

    def test_refused_service_stays_in_controller_queue_until_feedback_is_ready(self):
        from gongyu.policies import Controller
        w=self.world();c=Controller('R5',[('inspect','red_return')]);c.step(w)
        self.assertEqual(len(c.commands),1)
        for t in range(0,2300,100):
            self.pose(w,'R5',WorldPosition(w,'R5'),t);c.step(w)
        self.assertIn('red_return',w.completed)

    def test_sample_before_service_start_does_not_advance_service_dwell(self):
        w=self.world();p=WorldPosition(w,'R5');self.pose(w,'R5',p,0)
        w.advance(200);w.service('R5','inspect','red_return')
        w.receive_pose('R5',p,0.,0.,100)
        for t in range(300,2200,100):self.pose(w,'R5',p,t)
        w.advance(2200);self.assertNotIn('red_return',w.completed)
        for t in (2200,2300,2400):self.pose(w,'R5',p,t)
        w.advance(2500);self.assertIn('red_return',w.completed)


def WorldPosition(w,actor):
    from gongyu.world import World
    return World.node_position(w,actor,w.poses[actor])


if __name__=='__main__':unittest.main()


class EntryApron(unittest.TestCase):
    """phase123: the staging point is a conditional gain, so it must yield."""

    def world(self):
        card=m2_card();card['physical_channel_east_alignment']=[5.4,0.0,0.3]
        return PhysicalWorld(card,'entry_apron',lambda *args:None)

    def test_staging_point_yields_to_a_peer_crossing_the_apron(self):
        w=self.world();point=(5.4,0.0,0.3)
        w.samples['R2']=dict(xyz=(6.0,0.0,0.3),speed=0.,wz=0.,at=0)
        w.moves['R2']=dict(payload=dict(actor='R2',**{'from':'L','node':'E'}),since=0.,queued=False,started_ms=0)
        self.assertFalse(w.apron_clear('R1',point),'a peer berth transfer owns the apron')
        w.moves['R2']=dict(payload=dict(actor='R2',**{'from':'W','node':'D'}),since=0.,queued=False,started_ms=0)
        self.assertTrue(w.apron_clear('R1',point),'a peer away from the apron must not withhold the staging point')

    def test_a_stale_peer_sample_does_not_withhold_the_apron(self):
        w=self.world();point=(5.4,0.0,0.3)
        w.samples['R2']=dict(xyz=(6.0,0.0,0.3),speed=0.,wz=0.,at=-1000)
        w.moves['R2']=dict(payload=dict(actor='R2',**{'from':'L','node':'E'}),since=None,queued=False,started_ms=0)
        self.assertTrue(w.apron_clear('R1',point),'an unobserved peer cannot reserve ground')
