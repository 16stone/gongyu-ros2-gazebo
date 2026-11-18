import unittest
from pathlib import Path

from gongyu.communication import Network
from gongyu.model import Message
from gongyu.world import World,load_card


def world():
    card=load_card(Path(__file__).resolve().parents[1]/'scenarios/G_M1_t6000_r0_p12000.json')
    card['m2']={'enabled':True}
    return World(card,'m2_resource')


def tickets(w):
    blue=w.reserve('B1',20000,direction=('E','W'),exchangeable=True)
    red=w.reserve('R1',28000,direction=('E','W'),exchangeable=True)
    return {'contract_id':'m2','accept_by_ms':20000,'slots':[blue['slot_id'],red['slot_id']],
            'parties':['B1','R1']}


def impaired_m2_run(peers,dark_from,dark_until):
    """Replay the frozen m2 card with B3's downlink to `peers` dark for one window."""
    from freeze_m2 import m2_card
    from gongyu.policies import controllers
    card=m2_card();card['id']=f'T_dark{dark_from}'
    w=World(card,card['id']);cs=controllers(card,'P3')
    w.initialize_bookings()
    link=w.network.link
    for now in range(0,card['end_ms']+1,100):
        air=w.radio_positions()['B3'];targets=[w.radio_positions()[p] for p in peers]
        w.network.link=lambda a,b: link(a,b) and not (
            a==air and any(b==t for t in targets) and dark_from<=now<dark_until)
        w.advance(now)
        for actor in sorted(cs):cs[actor].step(w)
    return w


class M2Resource(unittest.TestCase):
    def test_quote_cannot_misdescribe_the_real_future_slot(self):
        w=world();q=tickets(w);w.now=18000
        q['blue_slot']={**w.reservations[0],'start':21000}
        with self.assertRaises(ValueError):
            w.exchange_slots('B1',q)

    def test_full_six_entity_trade_has_real_observation_and_bilateral_acceptance(self):
        from freeze_m2 import m2_card
        from gongyu.run import simulate
        r=simulate(m2_card(),'P0','m2_mutual')
        self.assertEqual(len(r.world.card['fleet']),6)
        self.assertTrue(any(e.kind=='slot_exchange_committed' for e in r.events))
        load=next(e for e in r.events if e.kind=='load_started' and e.task_id=='blue1')
        self.assertEqual(load.payload['report']['source_id'],'R5')
        self.assertEqual(r.world.completed['red1'],34000)
        self.assertLessEqual(r.world.completed['red_return'],37000)
        self.assertTrue(any(e.kind=='contract_state' and e.actor=='R1' and e.payload['state']=='FULFILLED' for e in r.events))
        self.assertFalse(r.world.violations)

    def test_provider_refusal_keeps_own_return_task_and_blue_self_help(self):
        from freeze_m2 import m2_card
        from gongyu.run import simulate
        r=simulate(m2_card(return_deadline_ms=34000),'P0','m2_refusal')
        self.assertFalse(any(e.kind=='slot_exchange_committed' for e in r.events))
        self.assertTrue(any(e.kind=='contract_state' and e.actor=='R1' and e.payload['state']=='REJECTED' for e in r.events))
        self.assertLessEqual(r.world.completed['red_return'],34000)
        self.assertIn('blue2',r.world.completed)

    def test_late_offer_does_not_exchange_slots(self):
        from freeze_m2 import m2_card
        from gongyu.run import simulate
        r=simulate(m2_card(offer_delay_ms=4000),'P0','m2_late')
        self.assertFalse(any(e.kind=='slot_exchange_committed' for e in r.events))
        self.assertTrue(any(e.kind=='contract_state' and e.payload['state']=='EXPIRED' for e in r.events))
        self.assertIn('blue2',r.world.completed)

    def test_blue_keeps_a_better_lawful_independent_plan(self):
        from freeze_m2 import m2_card
        from gongyu.run import simulate
        r=simulate(m2_card(tau_ms=20000),'P0','m2_blue_refusal')
        self.assertFalse(any(e.kind=='slot_exchange_committed' for e in r.events))
        self.assertTrue(any(e.kind=='contract_state' and e.actor=='B1' and e.payload['state']=='REJECTED' for e in r.events))
        first=next(e for e in r.events if e.kind=='load_started' and e.task_id=='blue1')
        self.assertEqual(first.payload['report']['sampled_at'],8000)


    def test_forecast_uses_the_robots_own_exchanged_slot(self):
        from dataclasses import replace
        from test_planning import checkpoint
        from gongyu.planning import forecast
        from gongyu.model import Report
        v=checkpoint(6000)
        v=replace(v,now_ms=27000,reports=(Report('R5','device',26000,6000,1,'H_R'),),
            own_tasks=({'id':'blue1','deadline_ms':90000},{'id':'blue2','deadline_ms':90000}),
            reservations=({'actor':'R1','start':24000,'end':30000,'used':False,'slot_id':'blue',
                           'direction':['E','W']},
                          {'actor':'B1','start':32000,'end':38000,'used':False,'slot_id':'red',
                           'direction':['E','W']}))
        c=forecast(v,{'id':'external','z':(0,0,0),'assignment':'single','support':'fixed','route':'channel','information':'refresh'})
        self.assertEqual(c['deliveries_ms'],[42000,78000])

    def test_future_outbound_slot_does_not_hold_the_inbound_robot(self):
        w=world();w.reserve('R2',0);out=w.reserve('B1',20000,direction=('E','W'),exchangeable=True)
        w.start_move('B1','W');w.advance(2000)
        self.assertFalse(w.start_move('B1','E'))
        inbound=next(r for r in w.reservations if r['actor']=='B1' and r.get('direction')==['W','E'])
        self.assertEqual(inbound['start'],8000)
        self.assertFalse(out['used'])

    def test_bilateral_exchange_changes_real_bookings_once(self):
        w=world();q=tickets(w);w.now=18000
        self.assertFalse(w.exchange_slots('B1',q))
        self.assertEqual([r['actor'] for r in w.reservations],['B1','R1'])
        self.assertTrue(w.exchange_slots('R1',q))
        self.assertEqual([r['actor'] for r in w.reservations],['R1','B1'])
        self.assertTrue(w.exchange_slots('R1',q))
        self.assertEqual([r['actor'] for r in w.reservations],['R1','B1'])

    def test_occupied_resource_cannot_be_exchanged_before_clearance(self):
        w=world();q=tickets(w);w.now=18000;w.channel.enter('R2',18000)
        self.assertFalse(w.exchange_slots('B1',q));self.assertFalse(w.exchange_slots('R1',q))
        self.assertEqual([r['actor'] for r in w.reservations],['B1','R1'])
        w.channel.leave('R2',19000);w.now=19000
        self.assertFalse(w.exchange_slots('B1',q));self.assertTrue(w.exchange_slots('R1',q))

    def test_versioned_booking_view_replaces_old_owner_only_after_delivery(self):
        w=world();q=tickets(w)
        old=dict(w.reservations[0]);new={**old,'actor':'R1','revision':1}
        w.inbox['B1']=[Message('entrance','B1',{'kind':'reservation','reservation':old},0,'old')]
        self.assertEqual(w.view('B1').reservations[0]['actor'],'B1')
        w.inbox['B1'].append(Message('entrance','B1',{'kind':'reservation','reservation':new},0,'new'))
        self.assertEqual(len(w.view('B1').reservations),1)
        self.assertEqual(w.view('B1').reservations[0]['actor'],'R1')

    def test_extra_transmission_delay_is_real_network_time(self):
        net=Network(1000,lambda a,b:True);poses={'a':'L','b':'E'}
        net.send('a','b',{'kind':'offer'},0,'offer',poses=poses,delay_ms=4000)
        self.assertEqual(net.advance(1000,poses),[])
        self.assertEqual(net.advance(4000,poses)[0].arrived_at,4000)

    def test_dropped_station_receipt_is_recovered_by_re_offering_the_report(self):
        from freeze_m2 import m2_card
        from gongyu.world import World
        from gongyu.m2 import m2_controllers
        card=m2_card();card['id']='T_receipt_gap'
        w=World(card,'receipt_gap');cs=m2_controllers(card,'P3')
        link=w.network.link;pad=w.radio_positions()['red_station']
        for now in range(0,60001,100):
            w.network.link=lambda a,b: link(a,b) and not (a==pad and 3000<=now<5500)
            w.advance(now)
            for actor in sorted(cs):cs[actor].step(w)
        self.assertEqual(w.completed.get('red_inspect'),3000)
        self.assertTrue(any(e.kind=='report_retransmitted' and e.payload['task_id']=='red_inspect' for e in w.events))
        self.assertEqual(w.local_results['R5'].get('red_inspect'),3000)

    def test_own_return_flight_does_not_wait_on_the_market_offer(self):
        from freeze_m2 import m2_card
        from gongyu.world import World
        from gongyu.m2 import m2_controllers
        card=m2_card();card['id']='T_station_dark'
        w=World(card,'station_dark');cs=m2_controllers(card,'P3')
        pad=w.radio_positions()['red_station']
        w.network.link=lambda a,b: a!=pad and b!=pad
        for now in range(0,60001,100):
            w.advance(now)
            for actor in sorted(cs):cs[actor].step(w)
        self.assertIsNone(w.local_results['R5'].get('red_inspect'))
        self.assertFalse([e for e in w.events if e.kind=='message_queued'
                          and isinstance(e.payload.get('payload'),dict)
                          and e.payload['payload'].get('kind')=='m2_air_status'])
        self.assertLessEqual(w.completed['red_return'],37000)

    def test_the_mission_recovers_from_a_randomly_lost_negotiation_message(self):
        from freeze_m2 import m2_card
        from gongyu.run import simulate
        for seed in (0,1):
            card=m2_card();card['channel_loss_rate']=0.30;card['seed']=seed;card['id']=f'T_loss{seed}'
            r=simulate(card,'P3',card['id'])
            for task in ('blue1','blue2','red_return'):
                self.assertIsNotNone(r.metrics['tasks'][task]['completed_ms'],(seed,task))
            self.assertFalse(r.metrics['constraint_violations'],seed)

    def test_a_lost_support_report_is_pulled_back_and_then_given_up_in_one_bound(self):
        w=impaired_m2_run(('B2',),35000,41000)
        for actor in ('B1','B2'):
            pulls=[e for e in w.events if e.actor==actor and e.kind=='support_report_rerequested']
            give_up=[e for e in w.events if e.actor==actor and e.kind=='support_report_unreachable']
            self.assertTrue(pulls,(actor,'a consumer must ask the provider again'))
            self.assertEqual(len(give_up),1,(actor,'giving up is declared once, not repeatedly'))
        self.assertTrue([e for e in w.events if e.kind=='release_complete'])
        self.assertIsNotNone(w.completed.get('blue2'))
        self.assertFalse(w.violations)

    def test_a_delivered_cargo_is_never_planned_a_second_time(self):
        w=impaired_m2_run(('B2',),40000,46000)
        self.assertEqual(w.completed.get('blue2'),53000)
        self.assertEqual(w.mission.delivered.count('blue2'),1)
        self.assertTrue([e for e in w.events if e.kind=='message_arrived' and e.actor=='B1'
                         and str(e.payload.get('message_id','')).startswith('task_result_reoffer_blue2')])
        self.assertEqual(w.local_results['B1'].get('blue2'),53000)
        self.assertFalse(w.violations)

    def test_peer_arbitration_commits_without_the_central_grant(self):
        from freeze_m2 import m2_card
        from gongyu.run import simulate
        card=m2_card();card['m2']['arbitration']='peer'
        r=simulate(card,'P3','m2_peer')
        active={a:next((e.t_ms for e in r.events if e.kind=='contract_state' and e.actor==a
                        and e.payload['state']=='ACTIVE'),None) for a in ('B1','R1')}
        self.assertEqual(active['B1'],22000);self.assertEqual(active['R1'],21000)
        committed=next(e for e in r.events if e.kind=='slot_exchange_committed')
        self.assertEqual(committed.payload['arbitration'],'peer')
        self.assertEqual(committed.payload['owners'],{'B1_24000':'R1','R1_32000':'B1'})
        kinds={e.payload['payload'].get('kind') for e in r.events if e.kind=='message_queued'
               and isinstance(e.payload.get('payload'),dict)}
        self.assertNotIn('m2_confirm',kinds);self.assertNotIn('m2_commit',kinds)
        self.assertIn('m2_bilateral',kinds)
        self.assertFalse(r.world.violations)
        self.assertTrue(all(t['on_time'] for t in r.metrics['tasks'].values()))

    def test_lost_reservation_broadcast_does_not_make_an_owner_reject_the_trade(self):
        from freeze_m2 import m2_card
        from gongyu.m2 import m2_controllers
        card=m2_card();card['m2']['arbitration']='peer';card['id']='T_peer_view'
        w=World(card,'peer_view');b1=m2_controllers(card,'P3')['B1']
        q=tickets(w);w.now=19000
        self.assertEqual(w.view('B1').reservations,())
        self.assertEqual([b1.open_replica(w,q).owners[s] for s in q['slots']],q['parties'])
        self.assertFalse(b1.confirm_to(w,q,'B1'))
        self.assertTrue(b1.confirm_to(w,q,'R1'))
        self.assertFalse([e for e in w.events if e.kind=='invalid_exchange'])

    def test_accepted_owner_adopts_a_commit_the_ledger_already_holds(self):
        from freeze_m2 import m2_card
        from gongyu.m2 import m2_controllers
        card=m2_card();card['m2']['arbitration']='peer';card['id']='T_peer_adopt'
        w=World(card,'peer_adopt');r1=m2_controllers(card,'P3')['R1']
        q=dict(tickets(w),report_sample_ms=24000,report_received_ms=25000,
               fulfillment_ack_by_ms=40000)
        w.now=19000
        self.assertTrue(w.record_bilateral_commit('B1',q))
        r1.cid=q['contract_id'];r1.quote=q;r1.market_state='ACCEPTED'
        r1.before_actions(w)
        self.assertEqual(r1.market_state,'ACTIVE')
        states=[e.payload['state'] for e in w.events
                if e.kind=='contract_state' and e.actor=='R1' and e.t_ms==w.now]
        self.assertEqual(states,['ACTIVE'])
        self.assertEqual([e for e in w.events if e.kind=='contract_state' and e.actor=='R1'
                          and e.payload['state']=='ACTIVE'][0].payload['adopted_from'],
                         'ledger record')

    def test_central_arbitration_still_routes_through_the_grantor(self):
        from freeze_m2 import m2_card
        from gongyu.run import simulate
        r=simulate(m2_card(),'P3','m2_central')
        confirm=next(e for e in r.events if e.kind=='message_arrived' and e.actor=='entrance'
                     and isinstance(e.payload.get('payload'),dict) and e.payload['payload'].get('kind')=='m2_confirm')
        self.assertIn(confirm.payload['sender'],('B1','R1'))
        self.assertTrue(any(e.kind=='slot_exchange_committed' and 'arbitration' not in e.payload for e in r.events))

    def test_only_an_owner_may_file_a_bilateral_commit(self):
        w=world();q=tickets(w);w.now=18000
        with self.assertRaises(ValueError):
            w.record_bilateral_commit('R2',q)

    def test_bilateral_record_swaps_bookings_once_and_survives_the_second_filing(self):
        w=world();q=tickets(w);w.now=18000
        self.assertTrue(w.record_bilateral_commit('R1',q))
        self.assertEqual([r['actor'] for r in w.reservations],['R1','B1'])
        self.assertEqual([r['revision'] for r in w.reservations],[1,1])
        self.assertTrue(w.bilateral_recorded(q))
        self.assertFalse(w.record_bilateral_commit('B1',q))
        self.assertEqual([r['actor'] for r in w.reservations],['R1','B1'])
        self.assertEqual([r['revision'] for r in w.reservations],[1,1])

    def test_occupied_channel_defers_the_bilateral_record(self):
        w=world();q=tickets(w);w.now=18000;w.channel.enter('R2',18000)
        self.assertFalse(w.record_bilateral_commit('B1',q))
        self.assertEqual([r['actor'] for r in w.reservations],['B1','R1'])
        w.channel.leave('R2',19000);w.now=19000
        self.assertTrue(w.record_bilateral_commit('B1',q))
        self.assertEqual([r['actor'] for r in w.reservations],['R1','B1'])

    def test_expired_quote_is_not_recorded(self):
        w=world();q=tickets(w);w.now=21000
        self.assertFalse(w.record_bilateral_commit('B1',q))
        self.assertEqual([r['actor'] for r in w.reservations],['B1','R1'])

    def test_negotiation_margin_follows_the_published_channel_model(self):
        from freeze_m2 import m2_card
        from gongyu.m2 import hop_budget
        plain=World(m2_card(),'hop_plain')
        self.assertEqual(hop_budget(plain),plain.network.delay)
        impaired=dict(m2_card(),channel_jitter_ms=400,channel_loss_rate=0.25,controller_sees_channel=True)
        w=World(impaired,'hop_impaired')
        self.assertEqual(hop_budget(w),1000+400+int(0.25*2000))
        unobserved=World(dict(m2_card(),channel_jitter_ms=400),'hop_unobserved')
        self.assertEqual(hop_budget(unobserved),unobserved.network.delay)

    def test_card_rejects_impossible_channel_settings(self):
        from freeze_m2 import m2_card
        from gongyu.world import load_card
        import json,tempfile,os
        for bad in ({'channel_jitter_ms':1000},{'channel_loss_rate':1.0},
                    {'controller_sees_channel':True},{'m2':{'enabled':True,'arbitration':'voting'}}):
            card=dict(m2_card(),**bad)
            with tempfile.NamedTemporaryFile('w',suffix='.json',delete=False,encoding='utf-8') as f:
                f.write(json.dumps(card));path=f.name
            try:
                with self.assertRaises(ValueError):
                    load_card(path)
            finally:
                os.unlink(path)


if __name__=='__main__':
    unittest.main()
