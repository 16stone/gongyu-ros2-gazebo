"""Verify recorded matrix events and summarize independent Webots restarts."""

import json
from pathlib import Path
import sys


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def summarize(run):
    metrics = load(run / "result/metrics.json")
    shutdown = load(run / "shutdown.json")
    events = [json.loads(line) for line in (run / "bus/events.jsonl").read_text(
        encoding="utf-8").splitlines()]
    scene = metrics["scene"]
    settings = metrics["settings"]
    tasks = metrics["task_completed"]

    def event(kind, actor, *, task=None):
        matches = [item for item in events if item["kind"] == kind and item["actor"] == actor
                   and (task is None or item.get("task_id") == task)]
        assert len(matches) == 1, (run.name, kind, actor, task, len(matches))
        return matches[0]["t_ms"]

    assert shutdown["status"] == "COMPLETE" and metrics["full_window"]
    assert metrics["motion_backend"] == "ugv_wheel_motors"
    assert "webots_exit=0" in (run / "environment.txt").read_text(encoding="utf-8")
    assert shutdown["sim_end_ms"] == metrics["sim_end_ms"]
    assert metrics["channel_overlap_samples"] == 0
    assert len(tasks) == metrics["total"] and tasks.keys() == metrics["deadlines_ms"].keys()
    for name, task in tasks.items():
        assert event("task_completed", task["actor"], task=name) == task["t_ms"]
        assert event("goal_dwell", task["actor"], task=name) == task["t_ms"]
        assert task["on_time"] == (task["t_ms"] <= metrics["deadlines_ms"][name])
    assert metrics["on_time"] == sum(task["on_time"] for task in tasks.values())
    row = {
        "run_id": run.name, "scene": scene,
        "source_commit": (run / "source.commit").read_text(encoding="utf-8").strip(), "settings": settings, "on_time": metrics["on_time"],
        "total": metrics["total"], "sim_end_ms": metrics["sim_end_ms"], "task_completed": tasks,
        "min_vehicle_separation_m": metrics["min_vehicle_separation_m"],
        "vehicle_envelope_overlap_samples": metrics["vehicle_envelope_overlap_samples"],
        "min_lane_envelope_margin_m": metrics["min_lane_envelope_margin_m"],
        "paths_m": metrics["paths_m"],
    }
    if scene == "web_cost":
        carrier = "B2" if settings["cost"] == "low" else "B1"
        assert tasks["delivery"]["actor"] == settings["carrier"] == carrier
        assert tasks["provider_return"]["actor"] == "B2"
        assert event("opportunity_cost_decision", carrier) == event("dispatch", carrier, task="delivery")
        assert metrics["on_time"] == 2 and metrics["vehicle_envelope_overlap_samples"] == 0
    else:
        clear = event("channel_clear", "B1")
        dispatch = event("dispatch", "B2")
        enters = event("channel_enter", "B2")
        assert clear <= dispatch < enters < event("channel_clear", "B2")
        row.update(b1_clear_ms=clear, b2_dispatch_ms=dispatch, b2_enter_ms=enters)
        if scene == "web_long":
            assert dispatch == (clear if settings["early_release"] else settings["nominal_clear_ms"])
            vias = [item["goal"] for item in events if item["actor"] == "R1"
                    and item["kind"] == "goal_dwell"]
            assert vias == [[1.0, -12.6], [6.0, -12.6], [6.0, -1.1]], vias
            assert metrics["vehicle_envelope_overlap_samples"] == 0
        else:
            destination_clear = event("destination_cleared", "B1")
            row["destination_clear_ms"] = destination_clear
            if settings["exit_check"]:
                assert event("dispatch_held_for_destination", "B2") == clear
                assert dispatch == destination_clear
                assert metrics["vehicle_envelope_overlap_samples"] == 0
            else:
                assert dispatch == clear < destination_clear
                assert metrics["vehicle_envelope_overlap_samples"] > 0
            assert metrics["on_time"] == 2
    return row


if __name__ == "__main__":
    root = Path(sys.argv[1])
    arms = ("cost-low", "cost-high", "long-release", "long-phase111", "exit-on", "exit-off")
    rows = [summarize(root / f"web-{arm}-{repeat:02d}")
            for arm in arms for repeat in range(1, 4)]
    for scene in {row["scene"] for row in rows}:
        commits = {row["source_commit"] for row in rows if row["scene"] == scene}
        assert len(commits) == 1, (scene, commits)
    print(json.dumps(rows, indent=2))
