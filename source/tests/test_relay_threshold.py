"""Response-threshold relay volunteering: what it decides, what it costs, and what it does not touch."""
import unittest

from freeze_g2 import g2_card
from gongyu import thresholds
from gongyu.run import simulate


def queued(result, kind):
    return [e for e in result.events if e.kind == 'message_queued'
            and isinstance(e.payload, dict) and e.payload.get('payload', {}).get('kind') == kind]


class RelayThresholdSelection(unittest.TestCase):
    def setUp(self):
        self.addCleanup(thresholds.attach, None)

    def test_shipped_card_is_untouched_and_advertises_on_its_own_clock(self):
        card = g2_card()
        self.assertNotIn('relay_selection', card['g2'])
        result = simulate(card, 'P3', 'threshold_off')
        self.assertFalse([e for e in result.events if e.kind == 'relay_offer_decided'])
        offers = queued(result, 'relay_offer')
        self.assertGreater(len(offers), 1, 'advertising repeats while the provider stays able')
        self.assertFalse(offers[0].payload['payload'].get('stimulus_deadline_ms'),
                         'the advertised offer carries no stimulus, because nothing computed one')

    def test_request_carries_the_stimulus_only_when_selection_is_switched(self):
        thresholds.attach(thresholds.Thresholds({'R3': 0.5, 'R4': 0.5}, reinforced=False))
        result = simulate(g2_card(relay_selection='threshold'), 'P3', 'threshold_stimulus')
        requests = queued(result, 'relay_offer_request')
        self.assertTrue(requests)
        self.assertIn('stimulus_deadline_ms', requests[0].payload['payload'])
        self.assertTrue([e for e in result.events if e.kind == 'relay_offer_decided'])

    def test_a_learner_without_a_ledger_is_refused_not_silently_hard(self):
        with self.assertRaisesRegex(ValueError, 'threshold ledger'):
            simulate(g2_card(relay_selection='threshold'), 'P3', 'threshold_no_ledger')

    def test_high_threshold_makes_every_provider_decline(self):
        thresholds.attach(thresholds.Thresholds({'R3': 0.99, 'R4': 0.99}, reinforced=False))
        result = simulate(g2_card(relay_selection='threshold'), 'P3', 'threshold_decline')
        decided = [e.payload for e in result.events if e.kind == 'relay_offer_decided']
        self.assertTrue(decided)
        self.assertTrue(all(not d['answers'] for d in decided))
        self.assertFalse(queued(result, 'relay_offer'))
        self.assertFalse(result.world.violations)

    def test_declining_gives_the_provider_its_own_return_window_back(self):
        hard = simulate(g2_card(), 'P3', 'threshold_window_hard')
        thresholds.attach(thresholds.Thresholds({'R3': 0.99, 'R4': 0.99}, reinforced=False))
        declined = simulate(g2_card(relay_selection='threshold'), 'P3', 'threshold_window_decline')
        for actor in ('red3_return', 'red4_return'):
            self.assertLess(declined.metrics['tasks'][actor]['completed_ms'],
                            hard.metrics['tasks'][actor]['completed_ms'])
        self.assertTrue(hard.metrics['tasks']['red1']['on_time'])
        self.assertFalse(declined.metrics['tasks']['red1']['on_time'],
                         'nobody forwarded the report, so the requester kept its own option')

    def test_low_threshold_reproduces_the_advertising_outcome_with_fewer_messages(self):
        hard = simulate(g2_card(), 'P3', 'threshold_cover_hard')
        thresholds.attach(thresholds.Thresholds({'R3': 0.05, 'R4': 0.05}, reinforced=False))
        answer = simulate(g2_card(relay_selection='threshold'), 'P3', 'threshold_cover_answer')
        self.assertEqual([t['on_time'] for t in hard.metrics['tasks'].values()],
                         [t['on_time'] for t in answer.metrics['tasks'].values()])
        self.assertLess(len(queued(answer, 'relay_offer')), len(queued(hard, 'relay_offer')))

    def test_service_lowers_the_threshold_of_the_provider_that_was_chosen(self):
        ledger = thresholds.attach(thresholds.Thresholds({'R3': 0.55, 'R4': 0.55}, reinforced=True))
        for episode in range(3):
            result = simulate(g2_card(relay_selection='threshold'), 'P3', f'threshold_reinforce_{episode}')
            served = [e.actor for e in result.events if e.kind == 'message_queued'
                      and isinstance(e.payload, dict)
                      and e.payload.get('payload', {}).get('kind') == 'inspection_report'
                      and e.payload['payload'].get('source_id') == 'R5'
                      and e.actor in ('R3', 'R4')]
            self.assertTrue(served)
            self.assertEqual(ledger.served[served[0]], episode + 1)
            self.assertAlmostEqual(ledger.threshold(served[0]),
                                   max(thresholds.FLOOR, 0.55 - thresholds.REINFORCE_DOWN * (episode + 1)), 6)
            other = {'R3', 'R4'} - {served[0]}
            self.assertAlmostEqual(ledger.threshold(next(iter(other))), 0.55, 6)

    def test_static_ledger_leaves_thresholds_alone(self):
        ledger = thresholds.attach(thresholds.Thresholds({'R3': 0.55, 'R4': 0.55}, reinforced=False))
        simulate(g2_card(relay_selection='threshold'), 'P3', 'threshold_static_run')
        self.assertEqual(ledger.threshold('R3'), 0.55)
        self.assertEqual(ledger.threshold('R4'), 0.55)

    def test_demand_mode_answers_every_request_without_a_ledger(self):
        result = simulate(g2_card(relay_selection='demand'), 'P3', 'demand_mode')
        self.assertFalse([e for e in result.events if e.kind == 'relay_offer_decided'])
        self.assertTrue(queued(result, 'relay_offer'))
        self.assertTrue(all(t['on_time'] for t in result.metrics['tasks'].values()))
        self.assertFalse(result.world.violations)


if __name__ == '__main__':
    unittest.main()
