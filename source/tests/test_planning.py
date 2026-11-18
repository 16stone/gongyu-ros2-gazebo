import unittest
from gongyu.planning import diagnose, propose, search_candidates
from gongyu.model import LocalView, Report


def checkpoint(tau=6000):
    return LocalView('B1',5000,'L',(Report('B2','device',0,tau,1,'O'),),(),
        ({'id':'blue1','deadline_ms':36000},{'id':'blue2','deadline_ms':36000}),
        public_map={'edges':[['L','E',1,'ground'],['E','W',3,'ground'],['W','D',1,'ground'],
                             ['O','J',2,'ground'],['J','L',2,'ground'],['L','D',12,'ground'],
                             ['F','K',4,'air'],['K','H',4,'air']],
                    'ground_speed':.5,'air_speed':1,'service_ms':2000,'message_delay_ms':1000,
                    'tau_ms':tau,'channel_gap_ms':2000,'end_ms':60000},
        teammate_status={'B2':{'node':'J','observed_at':4000,'available_until':60000,'report_sampled_at':0,
                              'report':{'source_id':'B2','subject_id':'device','sampled_at':0,'valid_for_ms':tau,'quality':1,'observation_region':'O'}},
                         'B3':{'node':'K','observed_at':4000,'available_until':6000,
                               'inspection_done':False,'inspection_deadline_ms':30000}},
        reservations=({'actor':'R1','start':0,'end':6000},{'actor':'R2','start':8000,'end':14000}))


class Planning(unittest.TestCase):
    def test_unknown_is_not_failure(self):
        v = LocalView('B1',1000,'L')
        self.assertEqual(diagnose(v,5000).status,'unknown')

    def test_search_semantics_and_same_budget(self):
        rows = [dict(id='base',z=(0,0,0),score=(1,0,0)),
                dict(id='a',z=(1,0,0),score=(1,-1,0)),
                dict(id='b',z=(0,1,0),score=(1,-1,0)),
                dict(id='joint',z=(1,1,0),score=(2,-2,0))]
        self.assertEqual(search_candidates(rows,'P2',64)[0]['id'],'base')
        self.assertEqual(search_candidates(rows,'P3',64)[0]['id'],'joint')
        self.assertLessEqual(len({r['id'] for r in search_candidates(rows,'P3',2)[1]}),2)
        self.assertEqual(search_candidates(rows,'P2_equal',64)[0]['id'],'joint')

    def test_c0_automatic_joint_and_long_simple(self):
        p = propose(checkpoint(),'P3')
        chosen = next(c for c in p.candidates if c['id']==p.chosen)
        self.assertEqual(chosen['assignment'],'split')
        self.assertEqual(chosen['support'],'air')
        self.assertEqual(chosen['deliveries_ms'],[26000,34000])
        long = propose(checkpoint(20000),'P3')
        selected = next(c for c in long.candidates if c['id']==long.chosen)
        self.assertEqual(selected['assignment'],'split')
        self.assertEqual(selected['support'],'fixed')

    def test_all_legal_simple_modes_are_visible(self):
        p = propose(checkpoint(),'P0')
        modes = {c['information'] for c in p.candidates}
        self.assertTrue({'refresh','self','carry','wait'} <= modes)
        routes = {c['route'] for c in p.candidates}
        self.assertEqual(routes,{'channel','bypass'})
        self.assertTrue(any(c['information']=='self' and not c['legal'] for c in p.candidates))

    def test_no_peer_status_no_invented_air_support(self):
        from dataclasses import replace
        v = replace(checkpoint(),teammate_status={})
        decision = propose(v,'P3')
        self.assertFalse(any(c['legal'] and c['support']=='air' for c in decision.candidates))

    def test_c0_selected_plan_reaches_actual_execution(self):
        from pathlib import Path
        from gongyu.run import simulate
        from gongyu.world import load_card
        c = load_card(Path(__file__).resolve().parents[1]/'scenarios/C0.json')
        result = simulate(c,'P3')
        self.assertEqual(result.world.completed.get('blue1'),26000)
        self.assertEqual(result.world.completed.get('blue2'),34000)
        self.assertEqual(result.metrics['constraint_violations'],[])
        states = [e for e in result.events if e.kind=='role_state' and e.actor=='B3']
        times = {e.payload['state']:e.t_ms for e in states}
        self.assertEqual(times['CONFIRMED'],6000)
        self.assertEqual(times['MOVING'],8000)
        self.assertGreater(times['ACTIVE'],times['READY'])
        active = [e for e in result.events if e.kind=='service_edge_active']
        self.assertTrue(any(e.actor=='B2' and e.payload['provider']=='B3' for e in active))

    def test_m1_reconfiguration_and_local_decision_input(self):
        from pathlib import Path
        from gongyu.run import simulate
        from gongyu.world import load_card
        c=load_card(Path(__file__).resolve().parents[1]/'scenarios/M1.json')
        r=simulate(c,'P3')
        self.assertEqual(r.metrics['constraint_violations'],[])
        self.assertTrue(any(e.kind=='service_edge_active' for e in r.events))
        self.assertTrue(r.decisions)
        self.assertLessEqual(r.decisions[0]['distinct_evaluated'],64)
        data=r.decisions[0]['input']
        self.assertFalse(any(t['id'].startswith('red') for t in data['own_tasks']))
        self.assertNotIn('poses',data)

    def test_expired_prepare_does_not_change_role(self):
        from pathlib import Path
        from gongyu.adaptive import Adaptive
        from gongyu.model import Message
        from gongyu.world import World,load_card
        w=World(load_card(Path(__file__).resolve().parents[1]/'scenarios/C0.json'),'late')
        w.now=10000
        controller=Adaptive('B2',[('hold',None)],'P3')
        controller.on_message(w,Message('B1','B2',{'kind':'prepare','proposal_id':'x',
            'role':'transport','expires_at':9000},0,'late'))
        self.assertIsNone(controller.pending)
        self.assertFalse(any(e.kind=='role_state' and e.payload['state']=='CONFIRMED' for e in w.events))

    def test_duplicate_abort_does_not_restart_released_role(self):
        from pathlib import Path
        from gongyu.adaptive import Adaptive
        from gongyu.model import Message
        from gongyu.world import World,load_card
        w=World(load_card(Path(__file__).resolve().parents[1]/'scenarios/C0.json'),'duplicate')
        c=Adaptive('B3',[('hold',None)],'P3')
        c.proposal='x';c.pending={'role':'observe'}
        m=Message('B1','B3',{'kind':'abort','proposal_id':'x'},0,'a')
        c.on_message(w,m)
        commands=list(c.commands)
        c.on_message(w,m)
        self.assertEqual(list(c.commands),commands)
        self.assertEqual(sum(e.kind=='role_state' and e.payload['state']=='RELEASED' for e in w.events),1)

    def test_low_quality_report_is_not_fresh_usable_information(self):
        from dataclasses import replace
        v=replace(checkpoint(),reports=(Report('B2','device',5000,6000,.5,'O'),))
        self.assertEqual(diagnose(v,5000).status,'violated')
        d=propose(v,'P3')
        selected=next(c for c in d.candidates if c['id']==d.chosen)
        self.assertGreater(selected['sampling_ms'][0],5000)

    def test_late_contact_prediction_has_enough_service_time(self):
        from pathlib import Path
        from gongyu.world import load_card
        from gongyu.run import simulate
        card=load_card(Path(__file__).resolve().parents[1]/'scenarios/M1_t6000_r4000_p20000.json')
        r=simulate(card,'P3')
        d=r.decisions[0]
        c=next(c for c in d['candidates'] if c['id']==d['chosen'])
        self.assertEqual([r.world.completed.get(x) for x in ('blue1','blue2')],c['deliveries_ms'])

    def test_lost_ready_releases_air_and_preserves_own_inspection(self):
        from pathlib import Path
        from gongyu.world import World,load_card
        from gongyu.policies import controllers
        card=load_card(Path(__file__).resolve().parents[1]/'scenarios/C0.json')
        w=World(card,'lost_ready')
        cs=controllers(card,'P3')
        for actor,release in zip(('R1','R2'),card['red_release_ms']):
            w.reserve(actor,release)
        link=w.network.link
        for now in range(0,60001,100):
            w.network.link=lambda a,b: link(a,b) and not (now==13000 and {a,b}=={'H','L'})
            w.advance(now)
            for actor in sorted(cs):
                cs[actor].step(w)
        self.assertIsNotNone(w.completed.get('blue_inspect'))
        self.assertLessEqual(w.completed['blue_inspect'],30000)
        self.assertNotEqual(w.poses['B3'],'H')
        self.assertTrue(any(e.kind=='role_state' and e.actor=='B3' and e.payload['state']=='RELEASED' for e in w.events))

    def test_carried_report_candidate_includes_send_dwell(self):
        from pathlib import Path
        from unittest.mock import patch
        from gongyu.world import load_card
        from gongyu.run import simulate
        from gongyu.model import Decision
        original=propose
        def force(view,policy):
            decision=original(view,'P3')
            return Decision('102',decision.candidates,decision.elapsed_ms)
        card=load_card(Path(__file__).resolve().parents[1]/'scenarios/M1_t20000_r4000_p12000.json')
        with patch('gongyu.adaptive.propose',force):
            r=simulate(card,'P3')
        c=next(c for c in r.decisions[0]['candidates'] if c['id']=='102')
        self.assertEqual([r.world.completed.get(x) for x in ('blue1','blue2')],c['deliveries_ms'])

    def test_periodic_diagnosis_uses_real_local_inventory(self):
        from pathlib import Path
        from gongyu.run import simulate
        from gongyu.world import load_card
        card=load_card(Path(__file__).resolve().parents[1]/'scenarios/C0.json')
        r=simulate(card,'P3')
        self.assertTrue(r.world.diagnostics)
        times=[d['t_ms'] for d in r.world.diagnostics]
        self.assertLessEqual(max(b-a for a,b in zip(times,times[1:])),500)
        self.assertTrue(any(d['inventory']=='blue1' and d['status']=='report_not_required' for d in r.world.diagnostics))

    def test_ready_retry_recovers_actual_failed_message(self):
        from pathlib import Path
        from gongyu.world import World,load_card
        from gongyu.policies import controllers
        card=load_card(Path(__file__).resolve().parents[1]/'scenarios/C0.json')
        card['ready_retry_ms']=2000
        w=World(card,'retry_ready');cs=controllers(card,'P3')
        for actor,release in zip(('R1','R2'),card['red_release_ms']):
            w.reserve(actor,release)
        link=w.network.link
        for now in range(0,60001,100):
            w.network.link=lambda a,b: link(a,b) and not (now==13000 and {a,b}=={'H','L'})
            w.advance(now)
            for actor in sorted(cs):
                cs[actor].step(w)
        self.assertEqual(w.completed.get('blue2'),34000)
        self.assertTrue(any(e.kind=='message_retry' for e in w.events))
        self.assertLessEqual(w.completed['blue_inspect'],30000)

    def test_retried_message_is_a_real_second_copy_not_a_recycled_id(self):
        from pathlib import Path
        from gongyu.world import World,load_card
        from gongyu.policies import controllers
        card=load_card(Path(__file__).resolve().parents[1]/'scenarios/C0.json')
        card['ready_retry_ms']=2000
        w=World(card,'retry_ids');cs=controllers(card,'P3')
        for actor,release in zip(('R1','R2'),card['red_release_ms']):
            w.reserve(actor,release)
        link=w.network.link
        for now in range(0,60001,100):
            w.network.link=lambda a,b: link(a,b) and not (now==13000 and {a,b}=={'H','L'})
            w.advance(now)
            for actor in sorted(cs):
                cs[actor].step(w)
        retried={e.payload['message_id'] for e in w.events if e.kind=='message_retry'}
        self.assertTrue(retried)
        self.assertTrue(retried <= {e.payload['message_id'] for e in w.events if e.kind=='message_arrived'})
        self.assertFalse([e for e in w.events if e.kind=='duplicate_send_ignored'
                          and e.payload['message_id'] in retried])

if __name__=='__main__':
    unittest.main()
