"""A plan built on lost knowledge must not abort the unit that holds the receipt.

The coordinator ranks candidates from `view.own_tasks`, whose completion column is filled by
delivery receipts that travel over the modelled lossy link. When every copy of a receipt is lost
the crate still looks outstanding, so a re-plan assigns a pickup that physically already happened.
`Mission.can_load` is right to refuse it -- the claim ledger still names the unit that hauled it --
and refusing used to raise, which killed the whole episode.
"""
import unittest

from freeze_m2 import m2_card
from gongyu.run import simulate


def stale_receipt_card():
    """The frozen M2 card under a link that drops the blue2 delivery receipt twice."""
    card = m2_card()
    card.update(channel_jitter_ms=400, channel_loss_rate=0.10, controller_sees_channel=True)
    card['red_release_ms'] = [32000, 0]
    card['seed'] = 789554
    card['id'] = f'{card["id"]}_impaired_link_r{card["seed"]}'
    return card


class StalePlanDelivery(unittest.TestCase):
    def test_the_unit_that_holds_the_receipt_drops_the_phantom_tour(self):
        card = stale_receipt_card()
        result = simulate(card, 'P3', card['id'])          # used to raise ValueError
        repairs = [e for e in result.events if e.kind == 'stale_plan_pickup_dropped']
        self.assertEqual([(e.actor, e.payload['cargo']) for e in repairs], [('B2', 'blue2')])
        self.assertTrue(all(e.t_ms >= 52600 for e in repairs))
        self.assertEqual(result.world.poses['B2'], 'L')
        self.assertEqual(result.metrics['constraint_violations'], [])
        self.assertEqual(len([e for e in result.events if e.kind == 'load_started'
                              and e.actor == 'B2']), 1)

    def test_the_receipt_really_is_lost_so_the_coordinator_is_blind(self):
        card = stale_receipt_card()
        result = simulate(card, 'P3', card['id'])
        receipt = [e for e in result.events if e.kind == 'message_failed'
                   and 'task_result_blue2' in str(e.payload.get('message_id', ''))]
        self.assertTrue(receipt)
        self.assertTrue(all(t['completed_ms'] is None for t in
                            result.world.view('B1').own_tasks if t['id'] == 'blue2'))
        self.assertEqual([t['completed_ms'] for t in result.world.view('B2').own_tasks
                          if t['id'] == 'blue2'], [52600])

    def test_a_plan_for_a_crate_that_is_genuinely_outstanding_is_untouched(self):
        """The repair must not swallow a real pickup: the nominal card still loads twice."""
        card = m2_card()
        card['id'] = 'T_stale_control'
        result = simulate(card, 'P3', card['id'])
        self.assertEqual([e for e in result.events if e.kind == 'stale_plan_pickup_dropped'], [])
        self.assertTrue(result.metrics['tasks']['blue2']['completed_ms'] is not None)


if __name__ == '__main__':
    unittest.main()
