import copy,unittest
from dataclasses import replace
from freeze_m2 import m2_card
from gongyu.world import World
from gongyu.geometry import ground_observation
from gongyu.planning import forecast_initial,with_shared_plan
from gongyu.remaining import ground_travel
from gongyu.adaptive import Adaptive,custom
from test_planning import checkpoint


class TimingProfile(unittest.TestCase):
    def test_physical_ready_timeout_uses_delivery_slack_without_extending_task_deadlines(self):
        from gongyu.adaptive import Adaptive
        c=self.card();c['physical_contact_hold_ms']=6000;c['end_ms']=400000
        w=World(c,'late_ready');w.now=100000
        a=Adaptive('B1',[],'P3')
        a.selected=dict(support='air',sampling_ms=[129000,129000],deliveries_ms=[274000,324000])
        # Same 350 s task limits as the retained late-READY physical counterexample.
        for task in w.card['tasks']:
            if task['id'] in ('blue1','blue2'):task['deadline_ms']=350000
        view=w.view('B1');a.set_deadlines(w,view)
        self.assertGreaterEqual(a.service_deadline,157000)
        self.assertLessEqual(a.service_deadline,165000)
        self.assertEqual([t['deadline_ms'] for t in w.card['tasks'] if t['id'] in ('blue1','blue2')],[350000,350000])
        w.card['end_ms']=150000;a.set_deadlines(w,w.view('B1'))
        self.assertEqual(a.service_deadline,150000)
        w.card['end_ms']=400000;a.selected['deliveries_ms']=[374000,424000]
        a.set_deadlines(w,w.view('B1'));self.assertEqual(a.service_deadline,131000)

    def card(self):
        c=m2_card();c['travel_time_ms']={'E>W':17000,'W>D':7000,'O>J':18000,'J>O':18000}
        return c

    def test_resource_and_local_route_use_the_same_directional_estimate(self):
        w=World(self.card(),'timing');r=w.reserve('R1',0,direction=('E','W'))
        self.assertEqual(r['end']-r['start'],17000)
        view=w.view('R1');end,commands,active=ground_travel(view,'channel','E','D',0,'R1')
        self.assertEqual(end,24000);self.assertEqual(active,24000)
        self.assertEqual(commands,[('move','W'),('move','D')])

    def test_reverse_channel_booking_does_not_borrow_forward_duration(self):
        c=m2_card();c['travel_time_ms']={'W>E':17000}
        w=World(c,'reverse');r=w.reserve('B1',0,direction=('W','E'))
        self.assertEqual(r['end']-r['start'],17000)

    def test_initial_round_trip_uses_each_direction_and_cost_once(self):
        for route,estimates,deliveries,movement in (
            ('bypass',{'L>D':10000,'D>L':30000},[19000,63000],50000),
            ('channel',{'E>W':10000,'W>E':30000},[23000,75000],62000)):
            v=checkpoint(200000);v=replace(v,reservations=(),public_map={**v.public_map,'travel_time_ms':estimates})
            c=forecast_initial(v,dict(assignment='single',support='fixed',route=route,information='refresh'))
            self.assertEqual(c['deliveries_ms'],deliveries)
            self.assertEqual(c['migration_ms'],movement)

    def test_observation_cannot_use_a_graph_speed_to_keep_a_physical_report_fresh(self):
        view=World(self.card(),'observation').view('B2')
        self.assertIsNone(ground_observation(view.public_map,'J','J',True))

    def test_initial_forecast_waits_for_the_slower_transport_before_air_report(self):
        v=checkpoint();statuses=copy.deepcopy(v.teammate_status);statuses['B3']['inspection_done']=True
        m={**v.public_map,'travel_time_ms':{'J>L':20000,'K>H':15000}}
        v=replace(v,public_map=m,teammate_status=statuses,reports=())
        c=forecast_initial(v,dict(assignment='split',support='air',route='bypass',information='refresh'))
        self.assertTrue(c['legal']);self.assertEqual(c['sampling_ms'][0],32000)

    def test_invalid_or_unknown_override_is_rejected_before_resource_creation(self):
        for values in ({'E>W':-1},{'E>W':True},{'X>Y':1000}):
            c=self.card();c['travel_time_ms']=values
            with self.assertRaises(ValueError):World(c,'invalid')

    def test_protocol_deadline_covers_the_physical_forecast_and_logs_release_reason(self):
        c=self.card();c['protocol_margin_ms']=4000;c['end_ms']=180000
        w=World(c,'protocol');w.poses['B1']='L';w.advance(90000)
        a=Adaptive('B1',[],'P3');a.selected=dict(assignment='split',support='air',route='channel',
            information='refresh',sampling_ms=[124000,124000])
        a.command(w,dict(kind='initial_prepare'))
        self.assertGreaterEqual(a.service_deadline,130000)
        a.abort(w,'test timeout reason')
        release=next(e for e in w.events if e.kind=='reconfiguration_release_started')
        self.assertEqual(release.payload['reason'],'test timeout reason')

    def test_physical_contact_prediction_is_unconfirmed_and_includes_actual_hold_rule(self):
        w=World(self.card(),'contact');w.card['physical_contact_hold_ms']=6000
        w.card['travel_time_ms'].update({'F>K':12000,'K>F':12000})
        v=with_shared_plan(w.view('B1'));s=v.teammate_status['B3']
        self.assertEqual(s['predicted_contact_at'],12000)
        self.assertEqual(s['available_until'],18000)
        self.assertEqual(s['source'],'unconfirmed_shared_plan')
        self.assertIsNone(s['observed_at'])

    def test_frozen_physical_profile_keeps_freshness_pressure_and_own_task_margins(self):
        from freeze_physical import m1_card
        from gongyu.timing import travel_ms
        c=m1_card();w=World(c,'frozen');view=w.view('B1')
        self.assertEqual(c['tau_ms'],6000)
        self.assertIsNone(ground_observation(view.public_map,'J','J',True))
        expected=with_shared_plan(view).public_map['shared_blue_plan']['air_inspection_expected_ms']
        own=next(t for t in c['tasks'] if t['id']=='blue_inspect')
        self.assertEqual(expected,32000);self.assertLess(expected,own['deadline_ms'])
        self.assertEqual(travel_ms(view.public_map,'E','W'),48000)

    def test_initial_scheduled_observation_is_still_performed_when_the_report_will_expire(self):
        from freeze_physical import m1_card
        from gongyu.policies import controllers
        c=m1_card();w=World(c,'prefix');observer=controllers(c,'P3')['B2']
        for now in range(0,30001,100):w.advance(now);observer.step(w)
        observations=[e for e in w.events if e.actor=='B2' and e.kind=='observation_completed']
        self.assertEqual(len(observations),1)
        self.assertEqual(observations[0].payload['report']['sampled_at'],8000)
        self.assertEqual(w.poses['B2'],'J')

    def test_short_physical_horizon_does_not_predict_a_reachable_contact(self):
        from freeze_physical import m1_card
        from gongyu.timing import contact_windows
        c=m1_card();c['end_ms']=10000
        self.assertEqual(contact_windows(c),[])
        self.assertNotIn('B3',with_shared_plan(World(c,'short').view('B1')).teammate_status)

    def test_split_same_exit_forecast_includes_public_departure_clearance(self):
        v=checkpoint();statuses=copy.deepcopy(v.teammate_status);statuses['B3']['inspection_done']=True
        v=replace(v,reports=(),teammate_status=statuses,public_map={**v.public_map,'departure_clearance_ms':6000})
        c=forecast_initial(v,dict(assignment='split',support='air',route='bypass',information='refresh'))
        self.assertEqual(c['sampling_ms'],[16000,16000])
        self.assertEqual(c['deliveries_ms'],[44000,50000])

    def test_graph_backend_applies_the_public_local_exit_estimate(self):
        from freeze_physical import m1_card
        c=m1_card();c['fleet']['B1']['node']='L';c['fleet']['B2']['node']='L'
        w=World(c,'model_egress');self.assertTrue(w.start_move('B1','D'))
        self.assertFalse(w.start_move('B2','D'))
        w.advance(c['departure_clearance_ms']);self.assertTrue(w.start_move('B2','D'))
        self.assertIn('B1',w.busy)


if __name__=='__main__':unittest.main()
