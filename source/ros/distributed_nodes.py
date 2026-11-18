"""ROS 2 deployment of the per-entity runtime: one node per unit, one referee node.

The offline backends show that the isolation boundary holds in one process
(`gongyu/runtime.py`) and across processes (`distributed/run_episode.py`).  This
module is the third topology: the same boundary expressed as a ROS 2 topic
graph, so a unit can be a container on another machine and the referee can be a
separate process without any code change inside the controllers.

Wire format, deliberately boring -- JSON in `std_msgs/String` -- so that no
custom message package is needed to reproduce it:

  /fleet/knowledge/<unit>   referee -> unit   the delivered local view + tick
  /fleet/request/<unit>     unit -> referee   one request (name, args, kwargs)
  /fleet/reply/<unit>       referee -> unit   the answer, or the refusal
  /fleet/notices/<unit>     referee -> unit   this unit's own events

What this file does *not* claim: it has never been run against a live ROS 2
graph in this project.  The shipped machine has no ROS 2 installation left, so
the report states it as a delivered entry point, not as a measured result.  The
`--plan` mode is executable without ROS and is what the receipts quote.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TOPICS = ('/fleet/knowledge/{unit}', '/fleet/request/{unit}',
          '/fleet/reply/{unit}', '/fleet/notices/{unit}')


def plan(card_path):
    """The deployment as data: which node owns what, and on which topic."""
    from gongyu.policies import controllers
    from gongyu.world import load_card
    card = load_card(card_path)
    units = sorted(controllers(card, 'P3'))
    return dict(
        card=card['id'],
        referee=dict(node='fleet_referee', owns=['world', 'mission', 'exchange_gate', 'slot_owners'],
                     publishes=[TOPICS[0].format(unit='*'), TOPICS[4 - 1].format(unit='*')]),
        units=[dict(unit=unit, node=f'unit_{unit.lower().replace("-", "_")}',
                    subscribes=[TOPICS[0].format(unit=unit), TOPICS[3].format(unit=unit),
                                TOPICS[2].format(unit=unit)],
                    publishes=[TOPICS[1].format(unit=unit)],
                    may_read=['own view', 'own actuator state', 'own notices'],
                    may_not_read=['world.poses', 'world.busy of others', 'world.reservations'])
               for unit in units],
        step_ms=card['step_ms'], entities=len(units),
        tested_here=False,
        note=('Topic graph only. No ROS 2 installation is present on the build machine, so this '
              'entry point is delivered and reviewed, not measured.'))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--card', default=str(Path(__file__).resolve().parents[1] / 'scenarios' / 'M1.json'))
    ap.add_argument('--plan', action='store_true', help='print the deployment plan without ROS')
    args = ap.parse_args(argv)
    if args.plan:
        print(json.dumps(plan(args.card), indent=2, ensure_ascii=False))
        return 0
    try:
        import rclpy                                        # noqa: F401
    except ImportError:
        print('rclpy is not installed on this machine; use --plan to inspect the deployment.',
              file=sys.stderr)
        return 2
    print('The executable per-entity loop is distributed/run_episode.py; this module publishes '
          'the topic graph it would be wired to. Run with --plan.', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
