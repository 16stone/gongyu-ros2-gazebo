"""Delayed local status must be refreshed through actual delivered messages."""
import unittest
from freeze_m2 import m2_card
from gongyu.m2 import Provider,RedMarket
from gongyu.model import Message
from gongyu.world import World


class ProviderRefresh(unittest.TestCase):
    def prepare(self):
        card=m2_card(return_deadline_ms=300000)
        card['m2']['red_radio_window_end_ms']=200000
        w=World(card,'delayed_status');w.now=100000
        w.poses['R5']='H_R';w.poses['R1']='E';w.network.link=lambda a,b:True
        w.local_results['R5'].update(red_inspect=2000,red_patrol=18000)
        blue=w.reserve('B1',140000,direction=('E','W'),exchangeable=True)
        red=w.reserve('R1',200000,direction=('E','W'),exchangeable=True)
        request=dict(subject_id='device',minimum_quality=1,maximum_age_ms=6000,report_by_ms=190000,
                     slots=[blue['slot_id'],red['slot_id']],parties=['B1','R1'],blue_slot=blue,red_slot=red,request_until_ms=138000)
        msg=Message('B1','R1',dict(kind='m2_request',contract_id='refresh',request=request),w.now,'request')
        return w,RedMarket([]),Provider([],'P0'),msg

    def test_missing_status_waits_for_real_query_and_reply(self):
        w,red,provider,msg=self.prepare();red.on_message(w,msg)
        self.assertEqual(red.market_state,'WAITING_PROVIDER')
        query=next(m for m in w.network.queue if m.receiver=='R5')
        self.assertEqual(query.payload['kind'],'m2_status_request')
        self.assertIsNone(red.air)
        w.advance(w.now+1000);provider.on_message(w,next(m for m in w.inbox['R5'] if m.message_id==query.message_id))
        self.assertIsNone(red.air)
        w.advance(w.now+1000)
        status=next(m for m in w.inbox['R1'] if isinstance(m.payload,dict) and m.payload.get('kind')=='m2_air_status')
        red.on_message(w,status)
        self.assertEqual(red.air['observed_at'],101000)
        self.assertNotEqual(red.market_state,'WAITING_PROVIDER')
        self.assertTrue(any(e.kind=='contract_decision' and e.actor=='R1' for e in w.events))

    def test_unreceived_provider_reply_expires_without_exchange(self):
        w,red,provider,msg=self.prepare();red.on_message(w,msg)
        w.now=msg.payload['request']['request_until_ms']+1;red.before_actions(w)
        self.assertEqual(red.market_state,'EXPIRED')
        self.assertFalse(any(e.kind=='slot_exchange_committed' for e in w.events))

    def test_moving_provider_cannot_advertise_stationary_availability(self):
        w,red,provider,msg=self.prepare();w.busy['R5']='move'
        provider.on_message(w,Message('R1','R5',{'kind':'m2_status_request'},w.now,'query'))
        self.assertFalse(any(isinstance(m.payload,dict) and m.payload.get('kind')=='m2_air_status' for m in w.network.queue))


if __name__=='__main__':unittest.main()
