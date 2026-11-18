import unittest
from dataclasses import replace
from freeze_physical import m1_card
from gongyu.planning import with_shared_plan
from gongyu.world import World


class DeliveredContactForecast(unittest.TestCase):
    def view(self,now):
        view=World(m1_card(),'contact_phase').view('B1')
        status=dict(node='K',observed_at=98890,available_until=104890,source='delivered_status',inspection_done=True)
        return replace(view,now_ms=now,node='L',teammate_status={'B3':status})

    def test_expired_actual_contact_cannot_be_extended_by_overlapping_static_window(self):
        result=with_shared_plan(self.view(107356));status=result.teammate_status['B3']
        self.assertEqual(status['predicted_contact_at'],134000)
        self.assertEqual(status['source'],'unconfirmed_shared_plan')

    def test_fresh_delivered_contact_is_kept(self):
        view=self.view(100000);self.assertIs(with_shared_plan(view),view)


if __name__=='__main__':unittest.main()
