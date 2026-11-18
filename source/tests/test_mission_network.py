import unittest

from gongyu.model import Report
from gongyu.mission import Mission, Channel
from gongyu.communication import Network


class Semantics(unittest.TestCase):
    def test_report_boundary_and_receipt(self):
        r = Report('B2', 'device', 0, 6000, 1.0, 'O')
        m = Mission({'cargo': 'device'})
        self.assertFalse(m.can_load('B1', 'cargo', 6000, 'L'))
        m.receive('B1', r)
        self.assertTrue(m.can_load('B1', 'cargo', 6000, 'L'))
        self.assertFalse(m.can_load('B1', 'cargo', 6001, 'L'))

    def test_duplicate_cargo_and_air_capability(self):
        m = Mission({'cargo': 'device'})
        for who in ('B1', 'B2', 'B3'):
            m.receive(who, Report('B2', 'device', 0, 6000, 1.0, 'O'))
        self.assertFalse(m.can_load('B3', 'cargo', 0, 'L', can_transport=False))
        m.start_load('B1', 'cargo', 0, 'L')
        self.assertFalse(m.can_load('B2', 'cargo', 0, 'L'))
        self.assertNotIn('B1', m.inventory)
        m.finish_load('B1', 'cargo')
        self.assertEqual(m.inventory['B1'], 'cargo')
        self.assertTrue(m.deliver('B1', 'D'))
        self.assertFalse(m.deliver('B1', 'D'))

    def test_second_load_after_delivery_without_reusing_cargo(self):
        m = Mission({'a':'device','b':'device'})
        m.receive('B1',Report('B2','device',0,6000,1,'O'))
        m.start_load('B1','a',0,'L')
        m.finish_load('B1','a')
        m.deliver('B1','D')
        with self.assertRaises(ValueError):
            m.finish_load('B1','a')
        self.assertTrue(m.can_load('B1','b',1000,'L'))

    def test_relay_preserves_sampling_time(self):
        n = Network(1000, lambda a,b: a == b or {a,b} == {'J','L'})
        r = Report('B2', 'device', 0, 6000, 1.0, 'O')
        n.send('B2', 'B1', r, 4000, 'report')
        self.assertEqual(n.advance(4000, {'B2':'O','B1':'L'}), [])
        self.assertEqual(n.advance(5000, {'B2':'J','B1':'L'}), [])
        delivery = n.advance(6000, {'B2':'J','B1':'L'})
        self.assertEqual(len(delivery), 1)
        self.assertEqual(delivery[0].payload.sampled_at, 0)
        self.assertEqual(delivery[0].arrived_at, 6000)

    def test_link_required_at_arrival_and_dedup(self):
        n = Network(1000, lambda a,b: a == b)
        n.send('B1','B3',{'kind':'recall'},0,'x')
        self.assertEqual(n.advance(0, {'B1':'L','B3':'L'}), [])
        self.assertEqual(n.advance(1000, {'B1':'L','B3':'K'}), [])
        self.assertEqual(len(n.failures), 1)
        n.send('B1','B3',{},2000,'y')
        n.send('B1','B3',{},2000,'y')
        n.advance(2000, {'B1':'L','B3':'L'})
        self.assertEqual(len(n.advance(3000, {'B1':'L','B3':'L'})), 1)

    def test_clearance_requires_exit_and_gap(self):
        c = Channel(2000)
        self.assertTrue(c.enter('R1',0))
        self.assertFalse(c.enter('B1',99999))
        c.leave('R1',6000)
        self.assertFalse(c.enter('B1',7999))
        self.assertTrue(c.enter('B1',8000))

    def test_report_sender_learns_station_receipt_only_after_ack(self):
        from pathlib import Path
        from gongyu.world import World,load_card
        w=World(load_card(Path(__file__).resolve().parents[1]/'scenarios/G_M1.json'),'station_receipt')
        w.send('R5',w.station,{'kind':'inspection_report','task_id':'red_inspect'},'inspection_red_inspect')
        w.advance(0);w.advance(1000)
        self.assertEqual(w.completed['red_inspect'],1000)
        self.assertNotIn('red_inspect',w.local_results['R5'])
        w.advance(2000);w.advance(3000)
        self.assertEqual(w.local_results['R5']['red_inspect'],1000)

    def test_coordinator_learns_delegated_completion_only_after_receipt(self):
        from pathlib import Path
        from gongyu.world import World,load_card
        w=World(load_card(Path(__file__).resolve().parents[1]/'scenarios/C0.json'),'receipt')
        w.poses['B2']='D'
        w.complete('B2','blue2','delivery')
        own=next(t for t in w.view('B1').own_tasks if t['id']=='blue2')
        self.assertIsNone(own['completed_ms'])
        w.poses['B1']='D'
        w.advance(1000);w.advance(2000)
        own=next(t for t in w.view('B1').own_tasks if t['id']=='blue2')
        self.assertEqual(own['completed_ms'],0)

if __name__ == '__main__':
    unittest.main()
