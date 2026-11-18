"""The isolation boundary also covers the static brief, not just live state."""
import copy
import unittest
from pathlib import Path

from distributed.run_episode import Referee
from gongyu.isolation import EntityScope
from gongyu.private_card import private_card, visible_deadlines
from gongyu.policies import controllers
from gongyu.runtime import Link
from gongyu.world import World, load_card

HERE = Path(__file__).resolve().parents[1]
CARD_PATH = HERE / 'scenarios' / 'M1.json'


def card():
    return load_card(CARD_PATH)


class PrivateTaskCard(unittest.TestCase):
    def test_public_configuration_is_unchanged(self):
        original = card()
        for actor in original['fleet']:
            brief = private_card(original, actor, ('blue1',))
            for key, value in original.items():
                if key in ('tasks', 'blue_deadline_ms', 'red_deadline_ms'):
                    continue
                self.assertEqual(brief[key], value, key)
            self.assertEqual([t['id'] for t in brief['tasks']],
                             [t['id'] for t in original['tasks']])

    def test_a_unit_sees_only_its_own_deadlines(self):
        original = card()
        world = World(copy.deepcopy(original), 'isolation_check')
        for actor in original['fleet']:
            own = sorted(world.local_assignments[actor])
            brief = private_card(original, actor, own)
            self.assertEqual(set(visible_deadlines(brief)), set(own), actor)
        # The original card is never mutated by building a brief.
        self.assertEqual(len(visible_deadlines(original)), len(original['tasks']))

    def test_card_level_team_deadline_is_private(self):
        original = card()
        self.assertIn('blue_deadline_ms', original)
        self.assertIn('blue_deadline_ms', private_card(original, 'B1', ('blue1',)))
        self.assertNotIn('blue_deadline_ms', private_card(original, 'R1', ('red1',)))

    def test_strict_scope_serves_a_redacted_card(self):
        c = card()
        world = World(copy.deepcopy(c), 'scope_check')
        strict = EntityScope(world, 'R1', strict=True, own_task_ids=('red1',))
        historical = EntityScope(world, 'R1', strict=False)
        self.assertEqual(visible_deadlines(strict.card), {'red1': 12000})
        self.assertEqual(visible_deadlines(historical.card),
                         {t['id']: t['deadline_ms'] for t in c['tasks']})
        self.assertEqual(strict.card['edges'], c['edges'])

    def test_multiprocess_brief_carries_no_competitor_deadline(self):
        c = card()
        referee = Referee(c, 'P3', 'brief_check', Link(), len(c['fleet']))
        for actor in c['fleet']:
            brief = referee._brief(actor)
            own = set(brief['own_task_ids'])
            visible = set(visible_deadlines(brief['card']))
            self.assertEqual(visible, own, actor)
            self.assertEqual(set(brief['card']['fleet']), set(c['fleet']))
            # The redacted brief must still build exactly the same controller.
            self.assertIn(actor, controllers(brief['card'], brief['policy']))

    def test_redaction_does_not_change_controller_programs(self):
        c = card()
        for actor in c['fleet']:
            own = sorted(World(copy.deepcopy(c), 'program_' + actor)
                         .local_assignments[actor])
            brief = private_card(c, actor, own)
            full = controllers(c, 'P3')[actor]
            scoped = controllers(brief, 'P3')[actor]
            self.assertEqual(list(full.commands), list(scoped.commands), actor)
            self.assertEqual(full.actor, scoped.actor)


if __name__ == '__main__':
    unittest.main()
