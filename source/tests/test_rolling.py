import unittest
from dataclasses import replace

from gongyu.planning import forecast,propose
from gongyu.run import simulate
from gongyu.world import load_card
from pathlib import Path
from test_planning import checkpoint


class Rolling(unittest.TestCase):
    def test_relocation_recovers_a_status_lost_at_the_first_radio_boundary(self):
        from run_rolling import held_card
        card=held_card('blue1');card['id']='T_staging_D';card['end_ms']=120000
        card['fleet']['B1']['node']='D'
        r=simulate(card,'P0','staging_status_loss')
        self.assertIsNotNone(r.world.completed.get('blue1'))
        self.assertIsNotNone(r.world.completed.get('blue2'))
        self.assertTrue(any(e.kind=='message_failed' for e in r.events))

    def test_first_collection_timeout_repairs_both_unfinished_deliveries(self):
        from run_online import fault_run
        card=load_card(Path(__file__).resolve().parents[1]/'scenarios/G_M1_t6000_r0_p12000.json')
        card['online_replanning']=True
        r=fault_run(card,'P0','first_report_lost',(35000,37000))
        self.assertEqual(r.world.completed.get('blue1'),64000)
        self.assertEqual(r.world.completed.get('blue2'),100000)
        self.assertEqual([e.task_id for e in r.events if e.kind=='load_started'],['blue1','blue2'])
        self.assertTrue(any(d.get('mode')=='rolling' and d['applied'] and d['t_ms']==38000 for d in r.decisions))

    def test_actual_load_of_either_cargo_survives_two_task_plan_repair(self):
        from freeze_remaining import residual_air_card
        from gongyu.world import World
        from gongyu.policies import controllers
        for cargo in ('blue1','blue2'):
            with self.subTest(cargo=cargo):
                card=residual_air_card();del card['initial_completed']['blue1']
                card['initial_reports']['B1']=0
                for task in card['tasks']:
                    if task['id'] in ('blue1','blue2'):
                        task['deadline_ms']=90000
                w=World(card,'held_'+cargo);cs=controllers(card,'P0')
                w.service('B1','load',cargo)
                for now in range(0,card['end_ms']+1,card['step_ms']):
                    w.advance(now)
                    for a in sorted(cs):
                        cs[a].step(w)
                self.assertEqual(w.completed.get(cargo),14000)
                self.assertEqual(set(e.task_id for e in w.events if e.kind=='load_started'),{'blue1','blue2'})
                self.assertEqual(sum(e.kind=='load_started' for e in w.events),2)
                self.assertEqual(w.completed.get('blue2' if cargo=='blue1' else 'blue1'),50000)

    def view(self):
        v=checkpoint(20000)
        return replace(v,public_map={**v.public_map,'online_replanning':True})

    def test_two_unfinished_tasks_relocate_before_using_load_site_forecast(self):
        v=replace(self.view(),node='D')
        decision=propose(v,'P0');c=next(c for c in decision.candidates if c['id']==decision.chosen)
        self.assertTrue(c['staging_commands'])
        self.assertGreater(c['planning_at_ms'],v.now_ms)
        at_l=replace(v,node='L',now_ms=c['planning_at_ms'])
        expected=forecast(at_l,c)
        self.assertEqual(c['deliveries_ms'],expected['deliveries_ms'])

    def test_either_held_cargo_is_delivered_before_planning_the_other(self):
        for cargo in ('blue1','blue2'):
            with self.subTest(cargo=cargo):
                v=replace(self.view(),inventory=cargo)
                d=propose(v,'P0');c=next(c for c in d.candidates if c['id']==d.chosen)
                self.assertEqual(c['preserved_cargo'],cargo)
                commands=c['staging_commands']+c['own_commands']
                self.assertNotIn(('load',cargo),commands)
                self.assertIn(('unload',cargo),commands)
                self.assertLess(c['deliveries_ms'][('blue1','blue2').index(cargo)],
                                c['deliveries_ms'][('blue1','blue2').index('blue2' if cargo=='blue1' else 'blue1')])

    def test_two_task_wait_does_not_override_a_proven_late_plan(self):
        v=replace(self.view(),now_ms=80000)
        d=propose(v,'P0');c=next(c for c in d.candidates if c['id']==d.chosen)
        self.assertNotEqual(c['information'],'wait')


if __name__=='__main__':
    unittest.main()
