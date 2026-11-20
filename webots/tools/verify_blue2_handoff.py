#!/usr/bin/env python3
"""Verify a closed blue2 handoff episode using the bus and referee receipts."""

import json
from pathlib import Path
import sys


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_events(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def verify(run):
    metrics = read_json(run / "result/metrics.json")
    shutdown = read_json(run / "shutdown.json")
    events = read_events(run / "bus/events.jsonl")
    assert shutdown["status"] == "COMPLETE" and shutdown["sim_end_ms"] >= 400000
    assert metrics["motion_backend"] == "hybrid"
    assert (metrics["on_time"], metrics["total"], metrics["violation_count"]) == (14, 14, 0)
    assert (metrics["channel_enters"], metrics["channel_releases"]) == (5, 5)
    assert not metrics["occupied_at_close"]
    assert all(key in metrics["truth_trajectories"] for key in ("B1", "B2"))

    def event(kind, actor, task="blue2"):
        matches = [row for row in events if
                   (row["kind"], row["actor"], row["task_id"]) == (kind, actor, task)]
        assert len(matches) == 1, f"Expected one {kind} from {actor} for {task}, found {len(matches)}"
        return matches[0]

    release = event("task_released", "B2")
    offer = event("handoff_offered", "B1")
    accepted = event("handoff_accepted", "B1")
    reassigned = event("reservations_reassigned", "B1")
    authorized = event("observation_authorized", "B1")
    pickup = event("handoff_pickup", "B1")
    done = event("task_completed", "B1")
    ack, = read_events(run / "bus/handoff_B1.jsonl")
    assert ack["offer_id"] == offer["payload"]["offer_id"] == accepted["payload"]["offer_id"]
    assert ack["actor"] == "B1" and ack["task_id"] == "blue2"
    assert reassigned["payload"] == {
        "previous_owner": "B2", "new_owner": "B1",
        "carrier_turn": 3, "channel_direction": "east_to_west", "destination": "blue_return",
    }
    crossed = [e for e in events if e["actor"] == "B1" and e["kind"] == "channel_enter"
               and pickup["t_ms"] < e["t_ms"] < done["t_ms"]]
    cleared = [e for e in events if e["actor"] == "B1" and e["kind"] == "channel_cleared"
               and pickup["t_ms"] < e["t_ms"] < done["t_ms"]]
    assert len(crossed) == len(cleared) == 1
    blue1 = event("task_completed", "B1", "blue1")
    assert (blue1["t_ms"] < release["t_ms"] <= offer["t_ms"] <= ack["t_ms"]
            <= accepted["t_ms"] <= reassigned["t_ms"] < authorized["t_ms"]
            < pickup["t_ms"] < crossed[0]["t_ms"] < cleared[0]["t_ms"] < done["t_ms"])
    assert len([row for row in events if row["kind"] == "task_completed"
                and row["task_id"] == "blue2"]) == 1
    result = metrics["task_completed"]["blue2"]
    assert result == {"actor": "B1", "t_ms": done["t_ms"],
                      "deadline_ms": 350000, "on_time": True}
    assert result["t_ms"] <= result["deadline_ms"]
    return {"completed": result, "release_ms": release["t_ms"],
            "accept_ms": accepted["t_ms"], "controller_ack_ms": ack["t_ms"],
            "reservations_ms": reassigned["t_ms"], "pickup_ms": pickup["t_ms"],
            "channel_enter_ms": crossed[0]["t_ms"], "channel_clear_ms": cleared[0]["t_ms"]}


if __name__ == "__main__":
    print(json.dumps(verify(Path(sys.argv[1])), indent=2))
