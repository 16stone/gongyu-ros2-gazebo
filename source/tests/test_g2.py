import unittest
from freeze_g2 import g2_card
from gongyu.model import Message
from gongyu.patrol import GroundInspector,RelayProvider
from gongyu.run import simulate
from gongyu.world import World


class EightEntityReports(unittest.TestCase):
    def test_eight_entities_have_real_tasks_and_r5_uses_actual_r4_relay(self):
        r=simulate(g2_card(),'P3','g2_r4')
        self.assertEqual(len(r.world.card['fleet']),8);self.assertEqual(len(r.metrics['tasks']),14)
        self.assertTrue(all(t['on_time'] for t in r.metrics['tasks'].values()))
        self.assertFalse(r.world.violations)
        route=next(e for e in r.events if e.actor=='R5' and e.kind=='inspection_route_selected' and e.payload['task_id']=='red_patrol')
        self.assertEqual(route.payload['chosen'],'R4')
        for actor in ('R3','R4'):
            self.assertTrue(any(e.actor==actor and e.kind=='arrived' for e in r.events))
            self.assertIsNotNone(r.world.completed['red'+actor[-1]+'_report'])
            self.assertFalse(any(e.actor==actor and e.kind=='inspect_started' and e.task_id=='red'+actor[-1]+'_report' for e in r.events))
        accepted=next(e for e in r.events if e.kind=='report_delivery' and e.task_id=='red_patrol')
        own_receipt=next(e for e in r.events if e.kind=='message_arrived' and e.actor=='R5' and e.payload.get('payload',{}).get('task_id')=='red_patrol' and e.payload['payload'].get('kind')=='task_result')
        self.assertGreater(own_receipt.t_ms,accepted.t_ms)
        self.assertTrue(any(e.kind=='message_arrived' and e.actor==r.world.station and e.payload['sender']=='R4' and e.payload.get('payload',{}).get('source_id')=='R5' for e in r.events))

    def test_private_return_budget_changes_the_actual_relay_choice(self):
        r=simulate(g2_card(red3_return_ms=110000),'P3','g2_r3')
        route=next(e for e in r.events if e.actor=='R5' and e.kind=='inspection_route_selected' and e.payload['task_id']=='red_patrol')
        self.assertEqual(route.payload['chosen'],'R3')
        self.assertTrue(all(t['on_time'] for t in r.metrics['tasks'].values()))

    def test_same_geometry_without_relay_forces_real_r5_carrying_flight(self):
        r=simulate(g2_card(six_entity_reference=True),'P3','g2_self_carry')
        self.assertEqual(len(r.world.card['fleet']),6)
        route=next(e for e in r.events if e.actor=='R5' and e.kind=='inspection_route_selected' and e.payload['task_id']=='red_patrol')
        self.assertEqual(route.payload['chosen'],'self_move')
        self.assertTrue(any(e.actor=='R5' and e.kind=='move_started' and e.payload['from']=='H_R' and e.payload['to']=='K_R' and e.t_ms<100000 for e in r.events))
        self.assertTrue(all(t['on_time'] for t in r.metrics['tasks'].values()))

    def test_busy_or_expired_ground_relay_cannot_forward_for_r5(self):
        for busy in (True,False):
            card=g2_card();w=World(card,'unavailable');cfg=card['g2']['patrols']['R4']
            peer=GroundInspector('R4',cfg,True);w.poses['R4']=cfg['relay']
            w.local_results['R4'][cfg['report_task']]=0
            w.now=40000 if busy else 100000
            if busy:w.busy['R4']=('move','PS','RS',0,50000)
            peer.on_message(w,Message('R5','R4',{'kind':'inspection_report','source_id':'R5','task_id':'red_patrol'},w.now,'report'))
            self.assertFalse(any(m.receiver==w.station for m in w.network.queue))
            self.assertTrue(any(e.kind=='relay_refused' for e in w.events))

    def test_relay_disabled_preserves_all_eight_entities_and_own_tasks(self):
        r=simulate(g2_card(relay_enabled=False),'P3','g2_no_relay')
        self.assertEqual(len(r.world.card['fleet']),8)
        self.assertTrue(all(t['on_time'] for t in r.metrics['tasks'].values()))
        route=next(e for e in r.events if e.actor=='R5' and e.kind=='inspection_route_selected' and e.payload['task_id']=='red_patrol')
        self.assertEqual(route.payload['chosen'],'self_move')

    def test_public_hardware_does_not_expose_private_task_deadlines(self):
        view=World(g2_card(),'public_hardware').view('R5')
        self.assertFalse(view.public_map['hardware']['R3']['payload_interface'])
        self.assertNotIn('deadline_ms',view.public_map['hardware']['R3'])

    def test_one_actual_sector_inspection_generates_the_separate_delivery_report(self):
        card=g2_card();card['g2']['reports_from']={'red3_inspect':'red3_report'}
        w=World(card,'one_inspection');w.poses['R3']='PN';w.service('R3','inspect','red3_inspect');w.advance(2000)
        self.assertEqual(w.completed['red3_inspect'],2000)
        report=w.view('R3').inspection_reports[0]
        self.assertEqual((report['task_id'],report['inspection_task_id'],report['sampled_at']),('red3_report','red3_inspect',2000))
        self.assertNotIn('red3_report',w.completed)
        with self.assertRaisesRegex(ValueError,'already completed'):w.service('R3','inspect','red3_inspect')

    def test_report_link_cannot_claim_another_actors_inspection(self):
        card=g2_card();card['g2']['reports_from']={'red3_inspect':'red4_report'}
        with self.assertRaisesRegex(ValueError,'linkage'):World(card,'bad_link')

    def test_late_ack_is_unknown_until_actually_received_not_a_fabricated_failure(self):
        card=g2_card();card['message_delay_overrides']={'task_result':2000}
        w=World(card,'late_ack');w.network.link=lambda a,b:True;w.poses['R5']='H_R'
        w.service('R5','inspect','red_patrol');w.advance(2000)
        report=next(r for r in w.view('R5').inspection_reports if r['task_id']=='red_patrol')
        w.advance(58000);w.send('R5',w.station,report,'own_report');w.advance(59000)
        peer=RelayProvider([],'P3',(),140000,6000);w.advance(60001)
        peer.command(w,{'kind':'deliver_own_report','task_id':'red_patrol'})
        self.assertTrue(any(e.kind=='inspection_delivery_unconfirmed' for e in w.events))
        self.assertFalse(any(e.kind=='inspection_delivery_failed' for e in w.events))
        w.advance(61000);receipt=next(m for m in w.inbox['R5'] if isinstance(m.payload,dict) and m.payload.get('task_id')=='red_patrol')
        peer.on_message(w,receipt)
        self.assertNotIn('red_patrol',peer.unconfirmed_reports)
        self.assertEqual(w.local_results['R5']['red_patrol'],59000)


if __name__=='__main__':unittest.main()
