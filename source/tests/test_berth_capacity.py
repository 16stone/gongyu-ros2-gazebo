"""`berth_capacity` as an enforced arrival constraint rather than a referee finding."""
import unittest
from pathlib import Path

from gongyu.world import World, load_card


def card():
    return load_card(Path(__file__).resolve().parents[1]/'scenarios/G_M1_t6000_r0_p12000.json')


class BerthCapacity(unittest.TestCase):
    def test_full_node_holds_the_arrival_and_never_refuses_the_departure(self):
        spec=card();spec['berth_capacity']['L']=1;spec['id']='T_berth_hold'
        w=World(spec,'berth_hold')
        self.assertTrue(w.start_move('R1','L',0))
        self.assertTrue(w.start_move('B1','L',0))
        w.advance(2000)
        self.assertEqual(w.poses['R1'],'L')
        w.advance(24000)
        self.assertIsNone(w.poses['B1'])
        self.assertIsNone(w.radio_positions()['B1'])
        self.assertEqual([e.payload for e in w.events if e.kind=='berth_hold'],
                         [{'node':'L','from':'D','held_at_ms':24000}])
        self.assertTrue(w.start_move('R1','E',25000))
        self.assertEqual(w.poses['B1'],'L')
        arrival=[e for e in w.events if e.kind=='arrived' and e.actor=='B1'][0]
        self.assertEqual(arrival.t_ms,25000)
        self.assertEqual(arrival.payload['held_ms'],1000)
        self.assertEqual([v for v in w.violations if v['kind']=='berth_capacity'],[])

    def test_a_held_unit_is_drawn_at_the_node_mouth_and_never_off_the_polyline(self):
        spec=card();spec['berth_capacity']['L']=1;spec['id']='T_berth_trajectory'
        w=World(spec,'berth_trajectory')
        w.start_move('R1','L',0);w.start_move('B1','L',0)
        w.advance(24000)
        for now in range(24100,25100,100):
            w.advance(now)
        held=[p for p in w.trajectories if p['actor']=='B1' and p['t_ms']>=24000]
        self.assertEqual({(p['x'],p['y'],p['z']) for p in held},{w.node_position('B1','L')})
        self.assertEqual({p['node'] for p in held},{None})

    def test_short_message_delay_card_never_parks_more_units_than_a_node_holds(self):
        from freeze_m2 import m2_card
        from gongyu.run import simulate
        spec=m2_card();spec['message_delay_ms']=400;spec['id']='T_berth_sweep'
        result=simulate(spec,'P3','T_berth_sweep')
        self.assertEqual([v for v in result.metrics['constraint_violations']
                          if v['kind']=='berth_capacity'],[])


if __name__=='__main__':
    unittest.main()
