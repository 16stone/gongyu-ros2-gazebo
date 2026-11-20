#!/usr/bin/env python3
"""Check the complete multirotor/ground course run and camera evidence."""
import argparse
import hashlib
import json
from pathlib import Path
from verify_blue2_handoff import verify as verify_handoff


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def events(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def verify(run, *, handoff=False):
    carrier = "B1" if handoff else "B2"
    metrics = read_json(run / "result/metrics.json")
    shutdown = read_json(run / "shutdown.json")
    assert metrics["motion_backend"] == "motor" and not metrics["kinematic_actors"], "All eight actors must be physical"
    assert metrics["rotor_actors"] == ["B3", "R5"]
    assert shutdown["status"] == "COMPLETE" and shutdown["sim_end_ms"] == 400000
    assert (metrics["on_time"], metrics["total"]) == (14, 14)
    assert (metrics["channel_enters"], metrics["channel_releases"], metrics["violation_count"]) == (5, 5, 0)
    timeline = events(run / "bus/events.jsonl")
    flights = {}
    for actor, side, task_ids in (
            ("B3", 1, ("blue_inspect",)),
            ("R5", -1, ("red_inspect", "red_patrol", "red_return"))):
        trajectory = metrics["truth_trajectories"][actor]
        positions = [row["pos"] for row in trajectory]
        assert positions[0][2] < 0.12
        assert max(p[2] for p in positions) >= 1.70
        assert any(abs(x - 6.0) <= 0.25 and abs(y - 8.0 * side) <= 0.25 and z >= 1.70
                   for x, y, z in positions)
        assert abs(positions[-1][0] - 14.0) <= 0.25
        assert abs(positions[-1][1] - 8.0 * side) <= 0.25 and positions[-1][2] < 0.12
        motor = events(run / f"bus/rotor_{actor}.jsonl")
        assert any(all(0 < abs(speed) <= 360 for speed in row["speeds"]) for row in motor)
        assert motor[-1]["speeds"] == [0.0] * 4
        tasks = {key: metrics["task_completed"][key] for key in task_ids}
        assert all(value["actor"] == actor and value["on_time"] for value in tasks.values())
        landed, = [row for row in timeline if row["kind"] == "rotor_landed" and row["actor"] == actor]
        flights[actor] = {"tasks": tasks, "landed_ms": landed["t_ms"],
                          "max_altitude_m": max(p[2] for p in positions)}

    authorized, = [row for row in timeline if row["kind"] == "observation_authorized"]
    assert authorized["actor"] == carrier and authorized["task_id"] == "blue2"
    observation = authorized["payload"]
    photo, = [row for row in events(run / "bus/observation_B3.jsonl")
              if row["t_ms"] == observation["sample_t_ms"]]
    assert photo["sender"] == "B3"
    assert photo["marker_pixels"] >= 40 and photo["image_signature"] == observation["image_signature"]
    image = (run / "evidence" / photo["frame"]).read_bytes()
    header = b"P6\n96 72\n255\n"
    assert image.startswith(header) and len(image) == len(header) + 96 * 72 * 3
    pixels = image[len(header):]
    digest = hashlib.sha256(pixels).hexdigest()
    assert digest == photo["rgb_sha256"] and int(digest[:8], 16) == observation["image_signature"]
    counted = sum(r >= 100 and b >= 100 and min(r, b) - g >= 50 for r, g, b in
                  zip(pixels[0::3], pixels[1::3], pixels[2::3]))
    assert counted == photo["marker_pixels"]
    requested, = [row for row in timeline if row["kind"] == "observation_requested"]
    assert requested["t_ms"] <= photo["t_ms"] < authorized["t_ms"] < flights["B3"]["landed_ms"]
    assert 0 < observation["age_ms"] <= observation["max_age_ms"]
    blue2 = metrics["task_completed"]["blue2"]
    assert blue2["actor"] == carrier and blue2["on_time"] and blue2["t_ms"] > authorized["t_ms"]
    result = {"flights": flights, "authorized_ms": authorized["t_ms"], "camera_sample_ms": photo["t_ms"],
              "marker_pixels": photo["marker_pixels"], "camera_age_ms": observation["age_ms"],
              "blue2": blue2}
    if handoff:
        result["handoff"] = verify_handoff(run, motion_backend="motor")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--handoff", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(args.run, handoff=args.handoff), indent=2))
