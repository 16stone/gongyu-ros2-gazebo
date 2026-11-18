# -*- coding: utf-8 -*-
"""The entity-process topology must not change a single decision.

`ros/entity_topology.py` is the full-physical-episode counterpart of
`distributed/run_episode.py`: one operating-system process per unit, a pipe
instead of an address space, and the referee as the only authority.  A topology
change that also changed behaviour would be worthless as evidence, so this test
pins the two implementations against each other on a registered graph card:
same card, same policy, same tick order, same event stream.

What is compared
----------------
The event digest used by `test_runtime_equivalence.py` (t_ms|actor|kind|task_id,
SHA256 over newline-joined rows), with the two bookkeeping events that only the
referee emits (`run_started` / `run_finished`) removed.  Everything the mission
does -- grants, entries, releases, deliveries, violations -- has to match.
"""
import hashlib
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from distributed.run_episode import Referee               # noqa: E402
from gongyu.runtime import Link                           # noqa: E402
from gongyu.world import World, load_card                 # noqa: E402
from ros.entity_topology import EntityTopology            # noqa: E402

BOOKKEEPING = ('run_started', 'run_finished')


def digest(events):
    rows = []
    for e in events:
        d = e if isinstance(e, dict) else e.__dict__
        if d.get('kind') in BOOKKEEPING:
            continue
        rows.append('|'.join(str(d.get(k, '')) for k in ('t_ms', 'actor', 'kind', 'task_id')))
    return hashlib.sha256('\n'.join(rows).encode()).hexdigest()


class EntityTopologyEquivalence(unittest.TestCase):
    """Same card, two process layouts, one event stream."""

    def test_entity_processes_reproduce_the_referee_event_stream(self):
        self._compare('phase111')

    def test_entity_processes_reproduce_the_referee_event_stream_with_layers_on(self):
        # With the release-aware layers on, the red route policy reads the channel
        # release counter, the measured traversal and the berth occupancy.  Those
        # three are exactly the values a shared address space used to supply, so
        # the comparison has to be repeated with the layers enabled: equality here
        # is what makes the published-status design a substitution, not a change.
        self._compare('joint')

    def _compare(self, mech):
        import os
        previous = os.environ.get('GONGYU_MECH')
        os.environ['GONGYU_MECH'] = mech
        try:
            self._run_comparison()
        finally:
            if previous is None:
                os.environ.pop('GONGYU_MECH', None)
            else:
                os.environ['GONGYU_MECH'] = previous

    def _run_comparison(self):
        card_path = HERE / 'scenarios' / 'M1.json'
        if not card_path.is_file():
            self.skipTest('registered card M1.json is not in this release')

        reference_card = load_card(card_path)
        referee = Referee(reference_card, 'P3', reference_card['id'] + '_ref',
                          Link(0, 0, 0.0, 0), len(reference_card['fleet']))
        referee.spawn()
        reference_world, _dropped = referee.run()

        card = load_card(card_path)
        world = World(card, card['id'] + '_entities')
        topology = EntityTopology(card, 'P3', world).spawn()
        world.initialize_bookings()
        step = card['step_ms']
        try:
            for index, now in enumerate(range(0, card['end_ms'] + 1, step)):
                world.advance(now)
                topology.tick(now, index)
        finally:
            receipt = topology.receipt()
            topology.close()

        self.assertEqual(digest(world.events), digest(reference_world.events),
                         'entity processes changed the mission event stream')
        self.assertGreater(receipt['cross_process_requests'], 0,
                           'the wire was never used: every decision came from the parent')


if __name__ == '__main__':
    unittest.main()
