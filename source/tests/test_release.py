import unittest
from collections import deque
from pathlib import Path

from gongyu.adaptive import Adaptive,custom
from gongyu.model import Message
from gongyu.world import World,load_card


def setup():
    card=load_card(Path(__file__).resolve().parents[1]/'scenarios/G_M1_t6000_r0_p12000.json')
    card['online_replanning']=True
    w=World(card,'release');w.poses.update(B1='L',B2='J',B3='K')
    peer=Adaptive('B3',[('hold',None)],'P3')
    peer.proposal='p';peer.pending={'role':'observe'};peer.committed=True
    return w,peer


def message(kind,sender='B1',receiver='B3',proposal='p',mid='m'):
    return Message(sender,receiver,{'kind':kind,'proposal_id':proposal},0,mid)


class Release(unittest.TestCase):
    def test_consumed_report_does_not_erase_an_unreleased_provider_proposal(self):
        from freeze_remaining import residual_air_card
        from gongyu.policies import controllers
        card=residual_air_card();w=World(card,'old_service');cs=controllers(card,'P3')
        c=cs['B1'];c.commands=deque([('hold',None)])
        c.proposal='old';c.required={'B3'};c.committed=True;c.fresh_consumed={-8000}
        c.proposal_deadline=20000;c.service_deadline=30000
        c.selected={'id':'010','z':(0,1,0),'assignment':'single','support':'air','information':'refresh','route':'channel'}
        p=cs['B3'];p.commands=deque([('hold',None)])
        p.proposal='old';p.pending={'role':'observe','expires_at':20000};p.committed=True
        for now in range(0,card['end_ms']+1,card['step_ms']):
            w.advance(now)
            for actor in sorted(cs):
                cs[actor].step(w)
        ack=next(e.t_ms for e in w.events if e.kind=='release_complete' and e.payload['proposal_id']=='old')
        prepared=[e for e in w.events if e.kind=='message_arrived' and isinstance(e.payload.get('payload'),dict)
                  and e.payload['payload'].get('kind')=='prepare' and e.payload['payload']['proposal_id']!='old']
        self.assertTrue(all(e.t_ms>=ack for e in prepared))
        self.assertIn('old',p.terminal_proposals)
        self.assertTrue(any(e.kind=='commitment_released' and e.payload['proposal_id']=='old' for e in w.events))

    def test_delegate_completion_releases_local_commitment_and_arrived_receipt_unlocks_coordinator(self):
        w,_=setup();p=Adaptive('B2',[],'P3')
        p.proposal='p';p.pending={'role':'transport'};p.committed=True
        w.local_assignments['B2'].add('blue2');w.local_results['B2']['blue2']=0
        p.step(w)
        self.assertIsNone(p.pending)
        c=Adaptive('B1',[('hold',None)],'P3');c.proposal='p';c.required={'B2'}
        c.selected={'assignment':'split'}
        c.on_message(w,Message('B2','B1',{'kind':'task_result','task_id':'blue2','completed_ms':0},0,'done'))
        self.assertNotIn('B2',c.required)

    def test_duplicate_prepare_does_not_restart_a_committed_workflow(self):
        w,p=setup();p.commands=deque([('hold',None)])
        p.on_message(w,Message('B1','B3',{'kind':'prepare','proposal_id':'p','role':'observe',
            'expires_at':20000},0,'duplicate_prepare'))
        self.assertEqual(list(p.commands),[('hold',None)])
        self.assertTrue(p.committed)

    def test_full_prefix_support_loss_releases_then_retries_new_handshake(self):
        from run_online import fault_run
        card=load_card(Path(__file__).resolve().parents[1]/'scenarios/G_M1_t6000_r0_p12000.json')
        card['online_replanning']=True
        r=fault_run(card,'P3','lost_support',(38000,40000))
        self.assertIsNotNone(r.world.completed.get('blue1'))
        self.assertIsNotNone(r.world.completed.get('blue2'))
        self.assertTrue(any(e.kind=='release_complete' for e in r.events))
        self.assertTrue(any(e.kind=='protocol_retry' for e in r.events))
        self.assertEqual(sum(e.kind=='load_started' for e in r.events),2)

    def test_busy_peer_releases_only_after_actual_arrival(self):
        w,p=setup();w.start_move('B3','H')
        p.on_message(w,message('release_request'))
        self.assertFalse(any(m.payload.get('kind')=='release_ack' for m in w.network.queue))
        w.advance(4000);p.step(w)
        self.assertIn('p',p.terminal_proposals)
        self.assertIsNone(p.pending)
        self.assertTrue(any(m.payload.get('kind')=='release_ack' for m in w.network.queue))
        self.assertTrue(any(e.kind=='commitment_released' and e.payload['node']=='H' for e in w.events))

    def test_loaded_delegate_refuses_release_without_losing_cargo(self):
        w,_=setup();p=Adaptive('B2',[('hold',None)],'P3')
        p.proposal='p';p.pending={'role':'transport'};p.committed=True
        w.mission.inventory['B2']='blue2';w.mission.claimed['blue2']='B2'
        p.on_message(w,message('release_request',receiver='B2'));p.step(w)
        self.assertEqual(w.mission.inventory['B2'],'blue2')
        self.assertIsNotNone(p.pending)
        self.assertNotIn('p',p.terminal_proposals)
        self.assertTrue(any(m.payload.get('kind')=='release_denied' for m in w.network.queue))

    def test_coordinator_does_not_forget_until_ack_and_ignores_wrong_proposal(self):
        w,_=setup();p=Adaptive('B1',[('hold',None)],'P3')
        p.proposal='p';p.required={'B3'};p.committed=True
        p.selected={'assignment':'single','support':'air','information':'refresh','route':'channel'}
        p.abort(w,'support report timed out')
        self.assertEqual(p.required,{'B3'})
        self.assertNotIn('p',p.terminal_proposals)
        p.on_message(w,message('release_ack',sender='B3',receiver='B1',proposal='old'))
        self.assertEqual(p.required,{'B3'})
        p.on_message(w,message('release_ack',sender='B3',receiver='B1'))
        self.assertFalse(p.required)
        self.assertIn('p',p.terminal_proposals)

    def test_duplicate_request_repeats_ack_without_repeating_release(self):
        w,p=setup()
        p.on_message(w,message('release_request'));p.step(w)
        p.on_message(w,message('release_request',mid='retry'))
        self.assertEqual(sum(e.kind=='commitment_released' for e in w.events),1)
        self.assertEqual(sum(m.payload.get('kind')=='release_ack' for m in w.network.queue),2)

    def test_lost_ack_is_retried_over_actual_network_without_resetting_release_time(self):
        w,peer=setup();coordinator=Adaptive('B1',[('hold',None)],'P3')
        coordinator.proposal='p';coordinator.required={'B3'};coordinator.committed=True
        coordinator.proposal_deadline=20000;coordinator.service_deadline=20000
        coordinator.selected={'assignment':'single','support':'air','information':'refresh','route':'channel'}
        coordinator.abort(w,'test lost release acknowledgement')
        link=w.network.link
        for now in range(0,22001,100):
            w.network.link=lambda a,b:link(a,b) and not 1900<=now<2100
            w.advance(now);coordinator.step(w);peer.step(w)
        self.assertTrue(any(e.kind=='release_complete' for e in w.events))
        self.assertGreater(sum(e.kind=='release_requested' for e in w.events),1)
        self.assertEqual(peer.release_receipts['p'],1000)
        self.assertEqual(sum(e.kind=='commitment_released' for e in w.events),1)
        self.assertTrue(any(e.kind=='message_failed' for e in w.events))
        self.assertLessEqual(w.completed['blue_inspect'],30000)

    def test_release_invalidates_only_older_availability(self):
        w,_=setup()
        w.inbox['B1']=[Message('B2','B1',{'kind':'status','node':'J','observed_at':0,'available_until':60000},0,'s'),
                       Message('B2','B1',{'kind':'release_ack','proposal_id':'p','released_at':1000},0,'r')]
        self.assertNotIn('B2',w.view('B1').teammate_status)
        w.inbox['B1'].append(Message('B2','B1',{'kind':'status','node':'J','observed_at':1000,'available_until':60000},0,'s2'))
        self.assertIn('B2',w.view('B1').teammate_status)


if __name__=='__main__':
    unittest.main()
