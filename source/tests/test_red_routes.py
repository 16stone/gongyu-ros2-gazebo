import unittest
from pathlib import Path

from freeze_m2 import m2_card
from gongyu.model import Message
from gongyu.world import World


class RedRoutes(unittest.TestCase):
    def test_admitted_late_channel_exit_keeps_its_committed_move(self):
        from collections import deque
        from freeze_g2 import g2_card
        from gongyu.modes import ModeRouteController,with_target_mode
        for mode in ('independent','adversarial'):
            w=World(with_target_mode(g2_card(),mode),'late_exit_'+mode)
            c=ModeRouteController('R1',[],mode);c.before_actions(w)
            self.assertIsNotNone(c.route_choice)
            deadline=next(t['deadline_ms'] for t in w.view('R1').own_tasks if t['id']=='red1')
            w.poses['R1']='W';w.now=deadline
            c.commands=deque([('move','D'),('unload','red1')])
            c.step(w)
            self.assertIn('R1',w.busy,'a delayed admitted route must leave the shared exit')
            self.assertEqual(list(c.commands),[('unload','red1')])

    def test_admitted_late_cargo_is_unloaded_and_recorded_late(self):
        from collections import deque
        from freeze_g2 import g2_card
        from gongyu.modes import ModeRouteController,with_target_mode
        for mode in ('independent','adversarial'):
            w=World(with_target_mode(g2_card(),mode),'late_unload_'+mode)
            c=ModeRouteController('R1',[],mode);c.before_actions(w)
            self.assertIsNotNone(c.route_choice)
            deadline=next(t['deadline_ms'] for t in w.view('R1').own_tasks if t['id']=='red1')
            w.poses['R1']='D';w.now=deadline+1;c.commands=deque([('unload','red1')])
            c.step(w);w.advance(w.now+w.card['service_ms'])
            self.assertIn('red1',w.completed,'late arrival cannot strand an already carried cargo')
            self.assertGreater(w.completed['red1'],deadline)

    def test_unadmitted_late_route_still_obeys_the_shared_quota(self):
        from freeze_g2 import g2_card
        from gongyu.modes import ModeRouteController,with_target_mode
        for mode in ('independent','adversarial'):
            w=World(with_target_mode(g2_card(),mode),'late_admission_'+mode)
            deadline=next(t['deadline_ms'] for t in w.view('R1').own_tasks if t['id']=='red1')
            w.poses['R1']='W';w.now=deadline
            c=ModeRouteController('R1',[('move','D'),('unload','red1')],mode);c.step(w)
            self.assertNotIn('R1',w.busy)
            self.assertIsNone(c.route_choice)

    def test_only_owner_can_cancel_an_unused_real_booking(self):
        w=World(m2_card(),'cancel')
        r=w.reserve('R1',32000,direction=('E','W'),exchangeable=True)
        self.assertFalse(w.cancel_reservation('B1',r['slot_id']))
        self.assertTrue(w.cancel_reservation('R1',r['slot_id']))
        self.assertEqual(r['cancelled_at'],0)
        self.assertTrue(w.cancel_reservation('R1',r['slot_id']))
        self.assertEqual(r['revision'],1)

    def test_cancel_is_not_visible_to_another_actor_before_real_message_delivery(self):
        w=World(m2_card(),'cancel_local')
        r=w.reserve('R1',32000,direction=('E','W'),exchangeable=True)
        old=dict(r)
        w.inbox['B1']=[Message('entrance','B1',{'kind':'reservation','reservation':old},0,'old')]
        w.cancel_reservation('R1',r['slot_id'])
        self.assertNotIn('cancelled_at',w.view('B1').reservations[0])

    def test_cancelled_slot_does_not_block_a_new_actual_reservation(self):
        w=World(m2_card(),'cancel_then_book')
        r=w.reserve('R1',32000,direction=('E','W'),exchangeable=True)
        w.cancel_reservation('R1',r['slot_id'])
        new=w.reserve('R2',32000,direction=('E','W'))
        self.assertEqual(new['start'],32000)

    def test_unused_grace_expiry_releases_only_the_booking_not_a_busy_channel(self):
        w=World(m2_card(),'expire')
        r=w.reserve('R1',0,direction=('E','W'),exchangeable=True)
        w.channel.enter('B2',0)
        w.advance(2100)
        self.assertEqual(r['cancelled_at'],2100)
        self.assertEqual(w.channel.occupant,'B2')

    def test_red_compares_revocation_with_waiting_and_bypass_from_actual_local_view(self):
        from gongyu.red_routes import red_candidates
        w=World(m2_card(),'candidates')
        blue=w.reserve('B1',24000,direction=('E','W'),exchangeable=True)
        red=w.reserve('R1',32000,direction=('E','W'),exchangeable=True)
        w.reserve('R2',0,direction=('E','W'))
        w.advance(1000)
        candidates=red_candidates(w.view('R1'))
        self.assertEqual({c['id'] for c in candidates},{'channel','bypass','rebook'})
        self.assertGreater(next(c['utility'] for c in candidates if c['id']=='rebook'),
                           next(c['utility'] for c in candidates if c['id']=='channel'))

    def test_autonomous_route_rebooks_after_real_ack_without_a_market_exchange(self):
        from gongyu.run import simulate
        card=m2_card();card['m2']['red_route_policy']='autonomous'
        r=simulate(card,'P0')
        ack=next(e for e in r.events if e.actor=='R1' and e.kind=='red_cancel_acknowledged')
        new=next(e for e in r.events if e.kind=='reservation_granted' and e.payload['actor']=='R1'
                 and e.payload['start']!=32000)
        self.assertTrue(ack.payload['released'])
        self.assertGreaterEqual(new.t_ms,ack.t_ms)
        self.assertEqual(r.world.completed['red1'],26000)
        self.assertFalse(any(e.kind=='slot_exchange_committed' for e in r.events))
        self.assertTrue(any(e.kind=='market_unavailable' for e in r.events))


if __name__=='__main__':
    unittest.main()
