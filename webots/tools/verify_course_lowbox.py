#!/usr/bin/env python3
"""Cross-check B1's eight-entity low-box follow-up with independent receipts."""
import json
from pathlib import Path
import sys

from verify_b1_followup import read_json, records, source_hash


def verify(run):
    shutdown = read_json(run / "shutdown.json")
    metrics = read_json(run / "result/metrics.json")
    events = records(run / "bus/events.jsonl")
    ctl = records(run / "bus/ctl_events.jsonl")
    assert shutdown["status"] == "COMPLETE" and shutdown["sim_end_ms"] == 400000
    assert shutdown["scene"] == "web_medium_phys_lowbox" and "webots_exit=0" in (run / "environment.txt").read_text()
    assert metrics["physical_actuation"] and metrics["kinematic_actors"] == ["B3", "R5"]
    assert metrics["full_window"]
    assert metrics["on_time"] == metrics["total"] == 14 and metrics["violation_count"] == 0
    assert (metrics["channel_enters"], metrics["channel_releases"], metrics["occupied_at_close"]) == (5, 5, [])
    assert not metrics["low_box"]["contacts"] and metrics["low_box"]["minimum_clearance_m"]["B1"] > 0
    stop, = [event for event in ctl if event["kind"] == "apron_scan_stop"]
    replan, = [event for event in ctl if event["kind"] == "apron_replanned"]
    assert stop["source"] == "low" and stop["return_m"] <= 0.42
    assert replan["targets"][-1] == [8.0, 2.4] and any(y > 2.6 for _, y in replan["targets"])
    assert all(event["actor"] == "B1" and event["task_id"] == "blue1" for event in (stop, replan))
    waypoints = [event for event in ctl if event["kind"] == "apron_waypoint"]
    assert [event["target"] for event in waypoints] == replan["targets"]
    clear, = [event for event in events if event["actor"] == "B1" and event["kind"] == "channel_cleared"]
    delivery, = [event for event in events if event["actor"] == "B1" and
                event["kind"] == "task_completed" and event["task_id"] == "blue1"]
    assert clear["t_ms"] < stop["t_ms"] < replan["t_ms"] < waypoints[-1]["t_ms"] < delivery["t_ms"]
    assert metrics["task_completed"]["blue1"]["actor"] == "B1"
    assert delivery["t_ms"] == metrics["task_completed"]["blue1"]["t_ms"]
    stage = [event for event in events if event["kind"] == "apron_preposition"]
    assert stage and all(event["actor"] == "R1" and event["t_ms"] < delivery["t_ms"] for event in stage)
    assert [event["payload"]["node"] for event in stage] == ["east_south_start", "east_gate", "east_straight"]
    r1_enter, = [event for event in events if event["kind"] == "channel_enter" and event["actor"] == "R1"]
    assert delivery["t_ms"] < r1_enter["t_ms"]
    separation = metrics["low_box"]["minimum_preposition_separation_m"]
    assert separation > 0.56
    assert min(metrics["low_box"]["minimum_clearance_m"].values()) > 0
    commit = (run / "source.commit").read_text().strip()
    for manifest in ("source.sha256", "scene.sha256"):
        for line in (run / manifest).read_text().splitlines():
            digest, source = line.split(maxsplit=1)
            if manifest == "scene.sha256" and "/webots/" in source:
                source = "webots/" + source.split("/webots/", 1)[1]
            assert source_hash(commit, source) == digest, source
    return {
        "source_commit": commit, "full_window_ms": shutdown["sim_end_ms"], "tasks_on_time": metrics["on_time"],
        "channel_enters": metrics["channel_enters"], "channel_releases": metrics["channel_releases"],
        "stop": stop, "replan": replan, "waypoints": waypoints, "delivery": delivery,
        "clearance_cm": 100 * metrics["low_box"]["minimum_clearance_m"]["B1"],
        "r1_preposition": stage, "r1_channel_enter": r1_enter, "minimum_preposition_separation_m": separation,
        "red1": metrics["task_completed"]["red1"],
    }


if __name__ == "__main__":
    print(json.dumps(verify(Path(sys.argv[1])), indent=2))
