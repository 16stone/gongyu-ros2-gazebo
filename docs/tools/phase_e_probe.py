"""Exercise the existing physical admission rules with controlled feedback samples."""
import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from gongyu.physical_world import PhysicalWorld
from gongyu.world import load_card


def cell(card_path, mechanism, downstream_busy):
    card = load_card(card_path)
    card["fleet"]["B1"]["node"] = "W"
    card["fleet"]["B2"]["node"] = "E"
    card["fleet"]["R1"]["node"] = "L"
    dispatched = []
    downstream_releases = []

    def release_arrival(actor, goal):
        downstream_releases.append([actor, goal])
        return True

    with patch.dict(os.environ, {"GONGYU_MECH": mechanism}):
        world = PhysicalWorld(card, "phase_e_feedback_fixture",
                              lambda actor, goal, points, **kw: dispatched.append(
                                  {"actor": actor, "goal": goal, "t_ms": world.now, **kw}),
                              release_arrival)

        def pose(actor, node, t_ms, goal=None):
            world.advance(t_ms)
            world.receive_pose(actor, world.reference_position(actor, node),
                               0.0, 0.0, t_ms, goal, goal is not None)
            world.advance(t_ms)

        def dwell(actor, node, first, last):
            for t_ms in range(first, last + 1, 100):
                pose(actor, node, t_ms, world.moves[actor]["token"])

        pose("R2", "E", 0)
        assert world.start_move("R2", "W")
        grant = world.reservations[0]
        assert grant["end"] == 48000
        if not downstream_busy:
            pose("B1", "W", 100)
            assert world.start_move("B1", "D")
            dwell("B1", "D", 1000, 2000)
        dwell("R2", "W", 4000, 5000)
        assert world.channel.occupant is None
        assert world.channel.clear_at == 5000
        predecessor_end = grant["end"]

        if downstream_busy:
            pose("B1", "W", 7100)
            assert world.start_move("B1", "D")

        pose("B2", "E", 7200)
        entered_at_probe = world.start_move("B2", "W")
        if downstream_busy:
            assert not entered_at_probe and world.channel.occupant is None
            assert any(event.kind == "physical_arrival_held" and event.actor == "B2"
                       for event in world.events)
            dwell("B1", "D", 14000, 15000)
            assert downstream_releases == [["B1", 1]]

        expected_entry = 50000 if mechanism == "phase111" else 15000 if downstream_busy else 7200
        if not entered_at_probe:
            pose("B2", "E", expected_entry)
            assert world.start_move("B2", "W")
        assert world.channel.occupant == "B2" and world.now == expected_entry
        assert predecessor_end == (48000 if mechanism == "phase111" else 5000)

        return {
            "mechanism": mechanism,
            "downstream_busy_at_probe": downstream_busy,
            "probe_t_ms": 7200,
            "entered_at_probe": entered_at_probe,
            "predecessor_clear_ms": 5000,
            "predecessor_effective_grant_end_ms": predecessor_end,
            "minimum_clearance_gap_ms": world.channel.gap,
            "follower_entry_ms": expected_entry,
            "downstream_releases": downstream_releases,
            "dispatches": dispatched,
            "events": [asdict(event) for event in world.events if event.kind in {
                "physical_arrival_held", "channel_enter", "channel_cleared",
                "channel_release_recomputed", "reservation_granted",
                "physical_completion_confirmed"}],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prepared_card", type=Path)
    args = parser.parse_args()
    print(json.dumps({
        "backend": "PhysicalWorld with deterministic pose and goal-success fixtures",
        "card": str(args.prepared_card),
        "cases": [
            cell(args.prepared_card, "phase111", False),
            cell(args.prepared_card, "release", False),
            cell(args.prepared_card, "release", True),
            cell(args.prepared_card, "joint", True),
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
