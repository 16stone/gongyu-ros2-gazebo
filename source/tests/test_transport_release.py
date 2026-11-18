import unittest
from freeze_physical import m1_card
from gongyu.adaptive import Adaptive
from gongyu.run import simulate
from gongyu.world import World


class TransportRelease(unittest.TestCase):
    def test_actual_delivery_releases_transport_despite_terminal_hold(self):
        r=simulate(m1_card(),'P3','release_after_delivery')
        completed=r.world.completed['blue2']
        releases=[e for e in r.events if e.actor=='B2' and e.kind=='role_state' and e.payload['state']=='RELEASED']
        self.assertTrue(releases)
        self.assertGreaterEqual(releases[-1].t_ms,completed)

    def test_terminal_hold_cannot_release_an_unfinished_cargo(self):
        w=World(m1_card(),'unfinished');peer=Adaptive('B2',[('hold',None)],'P3')
        peer.pending={'role':'transport'};peer.proposal='unfinished_proposal';peer.committed=True
        peer.before_actions(w)
        self.assertIsNotNone(peer.pending);self.assertTrue(peer.committed)


if __name__=='__main__':unittest.main()
