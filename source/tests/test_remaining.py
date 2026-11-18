import unittest
from dataclasses import replace

from gongyu.model import Report
from gongyu.planning import propose,search_candidates
from test_planning import checkpoint


class Remaining(unittest.TestCase):
    def test_checkpoint_cannot_claim_an_aircraft_delivered_ground_cargo(self):
        from freeze_remaining import residual_card
        from gongyu.world import World
        card=residual_card();card['initial_completed']['blue1']['actor']='B3'
        with self.assertRaises(ValueError):
            World(card,'invalid_checkpoint')

    def test_residual_plan_is_executed_without_duplicate_completed_cargo(self):
        from freeze_remaining import residual_card
        from gongyu.run import simulate
        result=simulate(residual_card(),'P1','residual_end_to_end')
        self.assertEqual(result.world.completed['blue2'],18000)
        loads=[e for e in result.events if e.kind=='load_started']
        self.assertEqual([e.task_id for e in loads],['blue2'])
        self.assertEqual(loads[0].actor,'B2')
        self.assertFalse(result.world.violations)

    def test_full_prefix_replans_after_first_delivery_without_reloading_it(self):
        from pathlib import Path
        from gongyu.run import simulate
        from gongyu.world import load_card
        card=load_card(Path(__file__).resolve().parents[1]/'scenarios/G_M1_t6000_r0_p12000.json')
        card['online_replanning']=True
        result=simulate(card,'P0','online_full_prefix')
        self.assertEqual(result.world.completed['blue2'],86000)
        self.assertEqual([e.task_id for e in result.events if e.kind=='load_started'],['blue1','blue2'])
        self.assertTrue(any(d.get('mode')=='remaining' and d['t_ms']>=50000 for d in result.decisions))

    def test_residual_air_service_uses_actual_report_then_preserves_loaded_cargo(self):
        from freeze_remaining import residual_air_card
        from gongyu.run import simulate
        r=simulate(residual_air_card(),'P3','remaining_air')
        self.assertEqual(r.world.completed['blue2'],25000)
        loads=[e for e in r.events if e.kind=='load_started']
        self.assertEqual(len(loads),1)
        self.assertEqual(loads[0].task_id,'blue2')
        self.assertEqual(loads[0].payload['report']['source_id'],'B3')
        self.assertTrue(any(d.get('mode')=='remaining' and d['input']['inventory']=='blue2' for d in r.decisions))

    def test_missing_second_report_replans_and_keeps_late_delivery(self):
        from pathlib import Path
        from gongyu.policies import controllers
        from gongyu.world import World,load_card
        for begin,end in ((72000,72100),(71000,73000)):
            with self.subTest(outage=(begin,end)):
                card=load_card(Path(__file__).resolve().parents[1]/'scenarios/G_M1_t6000_r0_p12000.json')
                card['online_replanning']=True
                w=World(card,'late_remaining_report');cs=controllers(card,'P0')
                for actor,release in zip(('R1','R2'),card['red_release_ms']):
                    w.reserve(actor,release)
                link=w.network.link
                for now in range(0,card['end_ms']+1,card['step_ms']):
                    w.network.link=lambda a,b:link(a,b) and not begin<=now<end
                    w.advance(now)
                    for actor in sorted(cs):
                        cs[actor].step(w)
                self.assertEqual(w.completed.get('blue2'),100000)
                self.assertTrue(any(d.get('reason')=='collection acknowledgement timed out' and d['applied'] for d in w.decisions))
                self.assertEqual([e.task_id for e in w.events if e.kind=='load_started'],['blue1','blue2'])

    def test_unknown_wait_can_be_replaced_by_a_proven_late_delivery(self):
        from freeze_remaining import residual_air_card
        from gongyu.policies import controllers
        from gongyu.world import World
        card=residual_air_card();w=World(card,'recover_unknown');cs=controllers(card,'P0')
        link=w.network.link
        for now in range(0,card['end_ms']+1,card['step_ms']):
            w.network.link=lambda a,b:link(a,b) and now>=5000
            w.advance(now)
            for actor in sorted(cs):
                cs[actor].step(w)
        self.assertEqual(w.completed.get('blue2'),32000)

    def test_delivered_cargo_is_not_planned_or_loaded_again(self):
        v=checkpoint(20000)
        v=replace(v,now_ms=26000,node='D',own_tasks=(
            {'id':'blue1','deadline_ms':36000,'completed_ms':26000},
            {'id':'blue2','deadline_ms':90000,'completed_ms':None}))
        d=propose(v,'P0')
        chosen=next(c for c in d.candidates if c['id']==d.chosen)
        self.assertEqual(chosen['remaining_tasks'],['blue2'])
        self.assertEqual(chosen['cargo_id'],'blue2')
        self.assertNotIn(('load','blue1'),chosen['own_commands'])

    def test_loaded_cargo_needs_no_new_report_and_cannot_be_reassigned(self):
        v=checkpoint()
        v=replace(v,inventory='blue2',own_tasks=(
            {'id':'blue1','deadline_ms':36000,'completed_ms':0},
            {'id':'blue2','deadline_ms':36000,'completed_ms':None}),reports=())
        d=propose(v,'P3')
        chosen=next(c for c in d.candidates if c['id']==d.chosen)
        self.assertTrue(chosen['legal'])
        self.assertEqual(chosen['transport_actor'],'B1')
        self.assertFalse(any(a[0]=='load' for a in chosen['own_commands']))
        self.assertEqual(chosen['deliveries_ms'][1],26000)

    def test_first_held_cargo_in_two_task_forecast_is_not_loaded_twice(self):
        v=replace(checkpoint(),now_ms=8000,inventory='blue1',reports=())
        d=propose(v,'P0')
        chosen=next(c for c in d.candidates if c['id']==d.chosen)
        self.assertEqual(chosen['deliveries_ms'][0],26000)
        self.assertIsNone(chosen['sampling_ms'][0])

    def test_remaining_assignment_uses_only_available_delivered_peer_state(self):
        v=checkpoint(20000)
        v=replace(v,teammate_status={**v.teammate_status,'B2':{**v.teammate_status['B2'],
            'node':'L','report':{'source_id':'B2','subject_id':'device','sampled_at':-8000,
                'valid_for_ms':20000,'quality':1.,'observation_region':'O'}}},
            own_tasks=({'id':'blue1','deadline_ms':36000,'completed_ms':0},
                       {'id':'blue2','deadline_ms':36000,'completed_ms':None}))
        d=propose(v,'P1')
        self.assertTrue(any(c['assignment']=='split' and c['legal'] for c in d.candidates))
        locked=replace(v,public_map={**v.public_map,'unresolved_commitments':['B2']})
        d=propose(locked,'P3')
        self.assertFalse(any(c['assignment']=='split' and c['legal'] for c in d.candidates))

    def test_unknown_wait_is_not_a_cost_free_proven_improvement(self):
        rows=[dict(id='deliver_late',z=(0,0,0),legal=True,score=(0,-100,0)),
              dict(id='wait_unknown',z=(0,0,1),legal=True,forecast_comparable=False,score=(0,0,0))]
        self.assertEqual(search_candidates(rows,'P3')[0]['id'],'deliver_late')

    def test_carrier_forecast_counts_return_to_its_observer_waypoint(self):
        v=replace(checkpoint(20000),reports=(Report('B2','device',-30000,20000,1.,'O'),),
            own_tasks=({'id':'blue1','deadline_ms':36000,'completed_ms':0},
                       {'id':'blue2','deadline_ms':90000,'completed_ms':None}))
        d=propose(v,'P0')
        c=next(c for c in d.candidates if c['route']=='channel' and c['information']=='carry')
        self.assertEqual(c['migration_ms'],26000)


if __name__=='__main__':
    unittest.main()
