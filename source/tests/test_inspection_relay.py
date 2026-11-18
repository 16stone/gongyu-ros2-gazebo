import copy,unittest
from freeze_m2 import m2_card
from gongyu.world import World


class InspectionRelay(unittest.TestCase):
    def world(self):
        card=m2_card();card['g2']={'manual_inspection_reports':True}
        card['fleet']['R3']=dict(mode='ground',node='L',role='transport',payload_interface=False)
        w=World(card,'actual_inspection');w.network.link=lambda a,b:True
        return w

    def issued(self):
        w=self.world();w.service('R5','inspect','red_inspect');w.advance(2000)
        report=w.view('R5').inspection_reports[0]
        return w,report

    def test_only_actual_completed_inspection_produces_own_report(self):
        w=self.world();self.assertEqual(w.view('R5').inspection_reports,())
        w.service('R5','inspect','red_inspect');w.advance(1000)
        self.assertEqual(w.view('R5').inspection_reports,())
        w.advance(2000);report=w.view('R5').inspection_reports[0]
        self.assertEqual((report['source_id'],report['task_id'],report['sampled_at']),('R5','red_inspect',2000))
        self.assertEqual(w.view('R1').inspection_reports,())
        self.assertNotIn('red_inspect',w.completed)
        self.assertFalse(any(m.receiver==w.station for m in w.network.queue))

    def test_station_delivery_and_two_hop_ack_are_distinct_actual_events(self):
        w,report=self.issued();w.send('R5','R1',report,'to_relay');w.advance(3000)
        w.send('R1',w.station,w.inbox['R1'][-1].payload,'forward_report');w.advance(4000)
        self.assertEqual(w.completed['red_inspect'],4000)
        self.assertIsNone(next(t for t in w.view('R5').own_tasks if t['id']=='red_inspect')['completed_ms'])
        w.advance(5000);ack=w.inbox['R1'][-1].payload
        self.assertEqual(ack['final_receiver'],'R5')
        w.send('R1','R5',ack,'forward_ack');w.advance(6000)
        self.assertEqual(next(t for t in w.view('R5').own_tasks if t['id']=='red_inspect')['completed_ms'],4000)

    def test_forged_or_modified_report_cannot_complete_task(self):
        for field,value in [('source_id','R1'),('sampled_at',0),('region','L')]:
            with self.subTest(field=field):
                w,report=self.issued();changed=copy.deepcopy(report);changed[field]=value
                w.send('R5','R1',report,'actual_origin_hop');w.advance(3000)
                w.send('R1',w.station,changed,'forged');w.advance(4000)
                self.assertNotIn('red_inspect',w.completed)
                self.assertTrue(any(e.kind=='invalid_inspection_report' for e in w.events))

    def test_duplicate_valid_forwarding_has_one_acceptance_and_same_completion_time(self):
        w,report=self.issued();w.send('R5','R1',report,'actual_origin_hop');w.advance(3000)
        w.send('R1',w.station,report,'first');w.advance(4000)
        w.send('R1',w.station,report,'retry');w.advance(5000)
        self.assertEqual(w.completed['red_inspect'],4000)
        self.assertEqual(sum(e.kind=='report_delivery' and e.task_id=='red_inspect' for e in w.events),1)

    def test_forged_ack_cannot_mark_the_origin_done(self):
        w,report=self.issued();w.send('R1','R5',dict(kind='task_result',task_id='red_inspect',completed_ms=2000,final_receiver='R5',receipt_id='invented'),'fake_ack')
        w.advance(3000)
        self.assertNotIn('red_inspect',w.local_results['R5'])

    def test_relay_cannot_forward_a_report_it_never_actually_received(self):
        w,report=self.issued();w.send('R1',w.station,report,'missing_origin_hop');w.advance(3000)
        self.assertNotIn('red_inspect',w.completed)

    def test_malformed_report_and_receipt_do_not_crash_the_episode(self):
        w=self.world();w.send('R1',w.station,{'kind':'inspection_report'},'missing_task')
        w.send('R1','R5',{'kind':'task_result'},'missing_receipt_task');w.advance(1000)
        self.assertFalse(w.completed)
        self.assertTrue(any(e.kind=='invalid_inspection_report' for e in w.events))

    def test_report_view_cannot_mutate_the_referees_issued_record(self):
        w,report=self.issued();report['sampled_at']=0
        self.assertEqual(w.view('R5').inspection_reports[0]['sampled_at'],2000)

    def test_ground_sensor_has_no_payload_interface_even_with_transport_role(self):
        w=self.world()
        with self.assertRaisesRegex(ValueError,'payload interface'):w.service('R3','load','blue1')
        with self.assertRaisesRegex(ValueError,'payload interface'):w.service('R3','unload','red1')


if __name__=='__main__':unittest.main()
