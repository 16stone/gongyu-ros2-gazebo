import unittest
from freeze_m2 import m2_card
from gongyu.adaptive import Adaptive,custom
from gongyu.berths import physical_card
from gongyu.physical_world import PhysicalWorld
from gongyu.world import World


class PhysicalContact(unittest.TestCase):
    def test_late_actual_arrival_keeps_contact_until_a_message_can_arrive(self):
        card=m2_card();card['fleet']['B1']['node']='L';card['fleet']['B3']['node']='K'
        sent=[];w=PhysicalWorld(physical_card(card),'contact',lambda *a:sent.append(a))
        c=Adaptive('B3',[custom('status',until=6000),('at',6000),('move','F')],'P3')
        for now in range(11000,17000,100):
            w.advance(now)
            for a in ('B1','B3'):w.receive_pose(a,w.reference_position(a,card['fleet'][a]['node']),0.,0.,now)
            c.step(w)
            self.assertFalse(sent,'departed before the actual six-second contact hold finished')
        arrived=[e for e in w.events if e.kind=='message_arrived' and e.payload['sender']=='B3']
        self.assertEqual(len(arrived),1);self.assertEqual(arrived[0].payload['payload']['available_until'],17000)
        w.advance(17000)
        for a in ('B1','B3'):w.receive_pose(a,w.reference_position(a,card['fleet'][a]['node']),0.,0.,17000)
        c.step(w);self.assertEqual(len(sent),1)

    def test_legacy_graph_status_does_not_add_a_new_hold(self):
        w=World(m2_card(),'graph');w.advance(4000)
        c=Adaptive('B3',[],'P3')
        self.assertEqual(c.command(w,dict(kind='status',until=6000)),[])

    def test_contact_availability_cannot_extend_the_physical_episode(self):
        w=World(physical_card(m2_card()),'end');w.advance(119000)
        c=Adaptive('B3',[],'P3')
        self.assertEqual(c.command(w,dict(kind='status',until=54000)),[('at',120000)])
        status=next(e.payload['payload'] for e in w.events if e.kind=='message_queued')
        self.assertEqual(status['available_until'],120000)


if __name__=='__main__':unittest.main()
