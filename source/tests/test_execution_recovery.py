"""Phase 102 regression: an own cargo must not be stranded by a stale no-route verdict.

The eight physical units in phase97/98 left red1 unfinished in three adversarial
scenarios. Their event streams show the same mechanism: after a clearance hold pushed
the forecast past the 250 s deadline, `feasible_red_routes` returned an empty set,
the controller replaced a still-pending move with a terminal `hold`, and the
time-free `route_signature` never changed again. These tests reproduce that failure
in the pure graph model, where the repair can be proven without ROS/Gazebo.
"""
import copy
import tempfile
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import Mock

from freeze_g2 import g2_card
from gongyu.modes import with_target_mode
from gongyu.policies import controllers
from gongyu.red_routes import red_candidates
from gongyu.run import simulate
from gongyu.world import World


def tight_card(deadline_ms=1000):
    card = with_target_mode(g2_card(), 'adversarial')
    for task in card['tasks']:
        if task['id'] == 'red1':
            task['deadline_ms'] = deadline_ms
    return card


def budget_exhausted_card():
    card = tight_card()
    card['target_constraints']['movement_budget_ms']['R1'] = 0
    return card


class ExecutionRecovery(unittest.TestCase):
    def test_overdue_own_task_is_executed_and_still_recorded_late(self):
        result = simulate(tight_card(), 'P3')
        red1 = result.metrics['tasks']['red1']
        self.assertIsNotNone(red1['completed_ms'],
            'an already-late own task must still be delivered, not held until the window ends')
        self.assertFalse(red1['on_time'], 'recovery must not launder a late delivery into an on-time one')
        recovery = [e for e in result.events if e.kind == 'deadline_miss_recovery' and e.actor == 'R1']
        self.assertTrue(recovery, 'every deviation from the declared quota needs an explicit receipt')
        payload = recovery[0].payload
        self.assertEqual(payload['task_id'], 'red1')
        self.assertIsNone(payload['decision_chosen'])
        self.assertGreater(payload['overdue_ms'], 0)
        self.assertLessEqual(recovery[0].t_ms, red1['completed_ms'])

    def test_scoring_layer_still_declares_no_legal_route(self):
        """The frozen nine-card baseline depends on choose_route staying unchanged."""
        card = tight_card()
        world = World(card, 'quota')
        world.initialize_bookings()
        controller = controllers(card, 'P3')['R1']
        world.advance(1000)
        view = world.view('R1')
        best, details = controller.choose_route(view, red_candidates(view))
        self.assertIsNone(best)
        self.assertEqual(details['feasible_candidate_ids'], [])

    def test_recovery_respects_the_movement_budget(self):
        result = simulate(budget_exhausted_card(), 'P3')
        self.assertIsNone(result.metrics['tasks']['red1']['completed_ms'])
        self.assertFalse([e for e in result.events if e.kind == 'deadline_miss_recovery'],
            'no budget means no legal recovery; the hard constraint is intact')

    def test_pending_move_survives_a_later_reforecast(self):
        card = with_target_mode(g2_card(), 'adversarial')
        world = World(card, 'pending')
        world.initialize_bookings()
        controller = controllers(card, 'P3')['R1']
        world.advance(1000)
        # Reproduce the phase97 long-bypass trace: an admitted E->W exit is held
        # because the predecessor has not cleared the local exit.
        from types import SimpleNamespace
        world.events.append(SimpleNamespace(actor='R1', kind='physical_departure_held',
                                            t_ms=world.now, payload={}, task_id=None))
        controller.route_choice = 'channel'
        controller.route_committed_at = world.now
        controller.route_signature = ('FORCE_REEVALUATION',)
        controller.commands = deque([('move', 'W'), ('move', 'D'), ('unload', 'red1')])
        controller.route_before_actions(world)
        self.assertEqual(controller.commands[0], ('move', 'W'),
            'a forecast must not strand an already admitted exit while physics clears it')

    def test_no_route_verdict_rechecks_on_the_clock_alone(self):
        """A time-free signature must not freeze a 'no legal route' verdict forever."""
        card = budget_exhausted_card()
        card['route_recheck_ms'] = 5000
        world = World(card, 'recheck')
        world.initialize_bookings()
        controller = controllers(card, 'P3')['R1']
        world.advance(1000)
        view = world.view('R1')
        emitted = []
        mock_world = Mock()
        mock_world.view.return_value = view
        mock_world.card = card
        mock_world.now = 1000
        mock_world.emit = lambda actor, kind, payload: emitted.append((actor, kind, payload))
        controller.route_before_actions(mock_world)
        decisions = lambda: [e for e in emitted if e[1] == 'red_route_decision']
        self.assertEqual(len(decisions()), 1)
        mock_world.now = 2000
        controller.route_before_actions(mock_world)
        self.assertEqual(len(decisions()), 1, 'inside the cooldown the verdict is throttled')
        mock_world.now = 7000
        controller.route_before_actions(mock_world)
        self.assertEqual(len(decisions()), 2, 'time alone must invalidate a frozen no-route verdict')

    def test_source_fingerprint_uses_posix_keys_on_windows(self):
        import ros.fleet_runner as runner
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'gongyu').mkdir()
            (root / 'gongyu' / 'model.py').write_text('VALUE=1\n', encoding='utf-8')
            info = runner.source_fingerprint(root)
            self.assertIn('gongyu/model.py', info['sha256'])
            self.assertEqual(len(info['sha256']['gongyu/model.py']), 64)


if __name__ == '__main__':
    unittest.main()
