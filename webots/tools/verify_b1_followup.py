#!/usr/bin/env python3
"""Check and summarize the 21 B1 follow-up Webots receipts and raw traces."""
from functools import lru_cache
from hashlib import sha256
import json
import math
from pathlib import Path
import subprocess
import sys

from analyze_b1_experiment import CARD, read_json, records, target_returns

REPO = Path(__file__).resolve().parents[2]


@lru_cache
def source_hash(commit, path):
    blob = subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=REPO)
    return sha256(blob).hexdigest()


def inspect(path):
    shutdown = read_json(path / "shutdown.json")
    metrics = read_json(path / "result/metrics.json")
    plan = read_json(path / "result/plan.json")
    assert shutdown["status"] == "COMPLETE" and shutdown["t_ms"] == metrics["t_end_ms"], path
    assert "webots_exit=0" in (path / "environment.txt").read_text(), path
    assert "seed=0" in (path / "environment.txt").read_text(), path
    assert metrics["first_obstacle_contact"] is None and metrics["violation_count"] == 0, path
    commit = (path / "source.commit").read_text().strip()
    for manifest in ("scene.sha256", "source.sha256"):
        for line in (path / manifest).read_text().splitlines():
            digest, source = line.split(maxsplit=1)
            if manifest == "scene.sha256":
                source = "webots/" + source.split("/webots/", 1)[1]
            assert source_hash(commit, source) == digest, (path, source)
    ctl_log = path / "bus/ctl_events.jsonl"
    return metrics, plan, records(ctl_log) if ctl_log.exists() else [], commit


def check_pair(root, control, treatment):
    results = []
    plans = []
    for bypass, identifier in ((False, control), (True, treatment)):
        base = root / identifier
        metrics, plan, ctl, commit = inspect(base)
        plans.append(plan)
        stopped, = [entry for entry in ctl if entry["kind"] == "scan_stop_latched"]
        assert stopped["source"] == "low" and stopped["distance_m"] <= CARD["stop_range_m"]
        assert plan["bypass_enabled"] == bypass and metrics["on_time"] == int(bypass)
        assert metrics["minimum_clearance_circle_m"] > 0 and metrics["total"] == 1
        replans = [entry for entry in ctl if entry["kind"] == "scan_replan_applied"]
        if bypass:
            replan, = replans
            assert stopped["t_ms"] < replan["t_ms"] < metrics["service_ms"] <= CARD["limit_ms"]
            assert replan["targets"][-1] == CARD["goal"]
            served, = [event for event in records(base / "bus/events.jsonl")
                       if event["kind"] == "service_completed"]
            assert served["t_ms"] == metrics["service_ms"]
        else:
            assert not replans and metrics["end_reason"] == "scan_safe_stop"
        results.append({"run_id": identifier, "source_commit": commit,
                        "first_stop": stopped, "replan": next(iter(replans), None), **metrics})
    assert plans[0]["path"] == plans[1]["path"] and plans[0]["algorithm"] == plans[1]["algorithm"] == "astar"
    assert results[0]["first_stop"] == results[1]["first_stop"]
    return results


def check_gate(root, arm, index):
    identifier = f"b1-gate-{arm}-20261120-{index:02d}"
    path = root / identifier
    metrics, _, ctl, commit = inspect(path)
    gate, = [entry for entry in ctl if entry["kind"] == "gate_alignment_checked"]
    assert gate["granted"] and gate["alignment_enabled"] == (arm != "direct")
    assert gate["alignment_selected"] == (arm == "clear")
    assert (gate["peer_path_clearance_m"] >= CARD["gate"]["min_peer_path_clearance_m"]) == (arm != "conflict")
    traversed = [event for event in ctl if event["kind"] == "tracked_waypoint" and
                 event["target"] == CARD["gate"]["alignment_m"]]
    assert bool(traversed) == (arm == "clear")
    if traversed:
        assert gate["t_ms"] < traversed[0]["t_ms"] < metrics["entered"]["t_ms"]
    assert metrics["on_time"] == metrics["total"] == 1
    assert gate["t_ms"] < metrics["entered"]["t_ms"] < metrics["cleared"]["t_ms"] < metrics["service_ms"]
    peer = {x["t_ms"]: x["position"][:2] for x in records(path / "bus/truth_B2.jsonl")}
    separation = min(math.dist(x["position"][:2], peer[x["t_ms"]])
                     for x in records(path / "bus/truth_B1.jsonl"))
    assert math.isclose(separation - 2 * CARD["model"]["footprint_radius_m"],
                        metrics["minimum_peer_clearance_circle_m"])
    assert metrics["minimum_peer_clearance_circle_m"] > 0 and metrics["peer_displacement_m"] > 0.5
    grant, = records(path / "bus/gate_grant.jsonl")
    assert math.dist(peer[max(peer)], grant["peer_target_m"]) <= 0.12
    return {"run_id": identifier, "source_commit": commit, "gate_check": gate, **metrics}


def check_height(root, height, expects):
    identifier = f"b1-height-{height}-20261120-01"
    path = root / identifier
    metrics, _, _, commit = inspect(path)
    assert metrics["end_reason"] == "stationary_sample_complete" and metrics["t_end_ms"] == 1024
    truth = {entry["t_ms"]: entry for entry in records(path / "bus/truth_B1.jsonl")}
    samples = records(path / "bus/tel_B1.jsonl")
    boxes = CARD["layouts"][metrics["layout"]]
    assert len(samples) == 16
    hits = {box[0]: {channel: sum(bool(target_returns(sample, truth[sample["t_ms"]], channel, box))
                                  for sample in samples) for channel in ("main", "low")} for box in boxes}
    assert hits["target"] == dict(zip(("main", "low"), expects)), hits
    if height == "occluded":
        assert hits["occluder"] == {"main": 16, "low": 16}
    return {"run_id": identifier, "source_commit": commit, "frames": len(samples), "hits_by_object": hits}


def verify(root):
    return {
        "initial_pair": check_pair(root, "b1-stop-20261120-01", "b1-bypass-20261120-01"),
        "unmapped_restarts": [check_pair(root, f"b1-unmapped-stop-20261120-{i:02d}",
                                         f"b1-unmapped-bypass-20261120-{i:02d}") for i in (1, 2, 3)],
        "gate_restarts": {arm: [check_gate(root, arm, i) for i in (1, 2, 3)]
                          for arm in ("direct", "clear", "conflict")},
        "stationary_lidar": [check_height(root, label, expects) for label, expects in
                             (("low", (0, 16)), ("mid", (16, 16)), ("high", (16, 16)), ("occluded", (0, 0)))],
    }


if __name__ == "__main__":
    print(json.dumps(verify(Path(sys.argv[1])), indent=2))
