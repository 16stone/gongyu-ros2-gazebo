import copy
import json
import unittest
from pathlib import Path

from gongyu.world import World, load_card, without_red_traffic
from gongyu.run import simulate

ROOT = Path(__file__).resolve().parents[1]


class Episode(unittest.TestCase):
    def test_c0_witness_is_executed_not_assigned(self):
        result = simulate(load_card(ROOT/'scenarios/C0.json'), 'witness')
        delivered = {e.task_id:e.t_ms for e in result.events if e.kind == 'delivery'}
        self.assertEqual([delivered[x] for x in ('blue1','blue2','red1','red2')],
                         [26000,34000,10000,18000])
        self.assertEqual(result.metrics['constraint_violations'], [])
        ages = [e.payload['report_age_ms'] for e in result.events if e.kind == 'load_started']
        self.assertEqual(ages, [5000,1000])

    def test_m1_has_real_prefix_and_failure_kept(self):
        card = load_card(ROOT/'scenarios/M1.json')
        result = simulate(card, 'P0')
        kinds = {e.kind for e in result.events}
        self.assertTrue({'observation_completed','message_arrived','load_started','delivery'} <= kinds)
        self.assertEqual(result.metrics['constraint_violations'], [])
        self.assertTrue(any(e.actor == 'B1' and e.kind == 'report_rejected' for e in result.events))
        self.assertEqual(result.metrics['backend'], 'graph')

    def test_air_cannot_use_ground_edge(self):
        w = World(load_card(ROOT/'scenarios/C0.json'), 'test')
        with self.assertRaises(ValueError):
            w.start_move('B3','L',0)

    def test_invalid_and_future_report_not_accepted(self):
        from gongyu.model import Report
        from gongyu.mission import Mission
        m = Mission({'a':'device'})
        m.receive('B1',Report('B2','device',1000,6000,1,'O'))
        self.assertFalse(m.can_load('B1','a',0,'L'))

    def test_deterministic_event_trace(self):
        card = load_card(ROOT/'scenarios/M1.json')
        a = simulate(card, 'P0')
        b = simulate(copy.deepcopy(card), 'P0')
        self.assertEqual(a.events,b.events)

    def test_c0_long_simpler_witness_keeps_delivery(self):
        result = simulate(load_card(ROOT/'scenarios/C0_long.json'),'witness')
        times = {e.task_id:e.t_ms for e in result.events if e.kind in ('delivery','inspection')}
        self.assertEqual(times['blue2'],34000)
        self.assertEqual(times['blue_inspect'],12000)
        self.assertFalse(any(e.actor=='B3' and e.kind=='arrived' and e.payload['node']=='H' for e in result.events))

    def test_m1_queue_causes_report_rejection(self):
        card = load_card(ROOT/'scenarios/M1.json')
        without = without_red_traffic(card)
        a,b = simulate(card,'P0'),simulate(without,'P0')
        self.assertTrue(any(e.kind=='report_rejected' and e.actor=='B1' for e in a.events))
        first_load = next(e.t_ms for e in b.events if e.kind=='load_started' and e.actor=='B1')
        self.assertFalse(any(e.kind=='report_rejected' and e.actor=='B1' and e.t_ms<first_load for e in b.events))
        self.assertEqual(b.metrics['constraint_violations'],[])

    def test_inspection_requires_assigned_actor_and_region(self):
        w = World(load_card(ROOT/'scenarios/C0.json'),'test')
        with self.assertRaises(ValueError):
            w.service('B1','inspect','blue_inspect')

    def test_late_reservation_is_not_used(self):
        w = World(load_card(ROOT/'scenarios/C0.json'),'test')
        w.reserve('R1',0)
        self.assertFalse(w.start_move('R1','W',20000))
        self.assertIsNone(w.channel.occupant)
        self.assertTrue(any(e.kind=='reservation_expired' for e in w.events))

if __name__ == '__main__':
    unittest.main()
