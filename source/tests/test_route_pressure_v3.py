import copy,unittest
from dataclasses import replace
from freeze_g2 import g2_card
from gongyu.adaptive import Adaptive
from gongyu.model import Message
from gongyu.modes import ModeRouteController,with_target_mode
from gongyu.red_routes import red_candidates
from gongyu.world import World


class RoutePressureV3(unittest.TestCase):
    def view(self,node='L',booking=150000):
        card=with_target_mode(g2_card(),'adversarial')
        next(t for t in card['tasks'] if t['id']=='red1')['deadline_ms']=350000
        w=World(card,'proxy');w.now=120000
        booking={'actor':'R1','start':booking,'end':booking+48000,'used':False,'direction':['E','W'],'slot_id':'own'}
        msg=Message('entrance','R1',{'kind':'entrance_observation','observed_at':120000,'waiting':[{'actor':'B2','node':node,'since_ms':100000}]},119000,'seen',arrived_at=120000)
        return replace(w.view('R1'),reservations=(booking,),inbox=(msg,))

    def test_faster_alternative_cannot_be_claimed_as_channel_delay(self):
        v=self.view();rows=red_candidates(v)
        own=ModeRouteController('R1',[],'independent').choose_route(v,rows)[0]
        chosen,details=ModeRouteController('R1',[],'adversarial').choose_route(v,rows)
        self.assertEqual(chosen['id'],own['id'])
        self.assertEqual(details['adversarial_proxy_ms'],0)

    def test_nonoverlapping_future_booking_has_zero_marginal_delay(self):
        v=self.view(node='E',booking=200000);rows=red_candidates(v)
        chosen,details=ModeRouteController('R1',[],'adversarial').choose_route(v,rows)
        self.assertEqual(chosen['id'],'rebook')
        self.assertEqual(details['adversarial_proxy_ms'],0)

    def test_unknown_observed_node_does_not_create_pressure(self):
        v=self.view(node='unknown');rows=red_candidates(v)
        chosen,details=ModeRouteController('R1',[],'adversarial').choose_route(v,rows)
        self.assertEqual(chosen['id'],'rebook')
        self.assertEqual(details['adversarial_proxy_ms'],0)

    def test_genuine_overlap_is_capped_by_the_available_alternative(self):
        v=self.view();m=copy.deepcopy(v.public_map)
        m['travel_time_ms']['L>D']=m['travel_time_ms']['D>L']=116667
        v=replace(v,public_map=m);chosen,details=ModeRouteController('R1',[],'adversarial').choose_route(v,red_candidates(v))
        self.assertEqual(chosen['id'],'channel')
        self.assertGreater(details['adversarial_proxy_ms'],0)
        self.assertLessEqual(details['adversarial_proxy_ms'],116667-90000)

    def blue(self,blocked=False):
        card=with_target_mode(g2_card(),'independent')
        card['fleet']['B1']['node']='E'
        card['fleet']['R1']['node']=card['fleet']['R2']['node']='D'
        w=World(card,'blue_rebook');w.now=120000
        own=w.reserve('B1',200000,direction=('E','W'))
        if blocked:w.reserve('R1',150000,direction=('E','W'))
        w.inbox['B1']=[Message('entrance','B1',{'kind':'reservation','reservation':dict(r)},0,'known_'+r['slot_id'],arrived_at=1000) for r in w.reservations]
        return w,Adaptive('B1',[('move','W')],'P3')

    def test_blue_can_promote_its_own_future_slot_only_after_actual_cancel_ack(self):
        w,c=self.blue();c.step(w)
        requested=lambda:any(e.kind=='message_queued' and e.actor=='B1' and isinstance(e.payload.get('payload'),dict) and e.payload['payload'].get('kind')=='reservation_cancel' for e in w.events)
        self.assertTrue(requested(),'blue should have the same lawful cancellation mechanism as red')
        self.assertNotIn('B1',w.busy)
        w.advance(121000);c.step(w)
        self.assertNotIn('B1',w.busy,'server release alone does not replace a delivered acknowledgement')
        w.advance(122000);c.step(w)
        self.assertIn('B1',w.busy)
        self.assertTrue(any(r['actor']=='B1' and r['used'] and r['start']==122000 for r in w.reservations))

    def test_blue_does_not_cancel_when_other_bookings_remove_the_gain(self):
        w,c=self.blue(blocked=True);c.step(w)
        self.assertFalse(any(e.kind=='message_queued' and e.actor=='B1' and isinstance(e.payload.get('payload'),dict) and e.payload['payload'].get('kind')=='reservation_cancel' for e in w.events))

    def test_legacy_resource_without_cancel_protocol_keeps_its_booking(self):
        w,c=self.blue();w.card.pop('m2');c.step(w)
        self.assertFalse(any(e.kind=='channel_rebook_requested' for e in w.events))
        w.advance(200000);c.step(w)
        self.assertIn('B1',w.busy)

    def test_foreign_ack_cannot_release_the_blue_local_wait(self):
        w,c=self.blue();c.step(w)
        c.on_message(w,Message('R1','B1',{'kind':'reservation_cancel_ack','slot_id':c.channel_cancel['slot_id'],'released':True},w.now,'forged'))
        self.assertIsNotNone(c.channel_cancel)
        self.assertNotIn('B1',w.busy)

    def test_denied_cancel_keeps_the_original_slot_without_retry_loop(self):
        w,c=self.blue();c.step(w);slot=c.channel_cancel['slot_id']
        c.on_message(w,Message('entrance','B1',{'kind':'reservation_cancel_ack','slot_id':slot,'released':False},w.now,'denied'))
        c.step(w);c.step(w)
        self.assertNotIn('B1',w.busy)
        self.assertEqual(sum(e.kind=='channel_rebook_requested' for e in w.events),1)

if __name__=='__main__':unittest.main()
