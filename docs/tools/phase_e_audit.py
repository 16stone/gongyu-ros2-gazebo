"""Recompute Phase E graph results, archived Gazebo holds and sampled lane occupancy."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def file_hash(path):
    with path.open("rb") as stream:
        digest = sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def timeline(events, card, metrics):
    active = None
    grants = {}
    arrived = {(actor, spec["node"]): 0 for actor, spec in card["fleet"].items()}
    holds, releases = [], []
    waits = defaultdict(list)
    for event in events:
        kind, actor, t = (event[key] for key in ("kind", "actor", "t_ms"))
        p = event["payload"]
        if kind in {"reservation_granted", "reservation_expired", "reservation_cancelled"}:
            grants[p["slot_id"]] = p.copy()
        elif kind == "arrived":
            arrived[actor, p["node"]] = t
        elif kind == "channel_enter":
            assert active is None
            direction = [p["from"], p["to"]]
            matched = [r for r in grants.values()
                       if r["actor"] == actor and r.get("direction") == direction
                       and not r["used"] and r.get("cancelled_at") is None
                       and r["start"] <= t]
            assert len(matched) == 1, (actor, t, matched)
            grant = matched[0]
            grant["used"] = True
            at_entrance = arrived.get((actor, p["from"]))
            active = dict(actor=actor, direction=direction, held_ms=t,
                          slot_id=grant["slot_id"], nominal_end_ms=grant["end"],
                          effective_end_ms=grant["end"], nominal_start_ms=grant["start"],
                          recorded_entrance_arrival_ms=at_entrance,
                          entrance_arrival_to_hold_ms=t-at_entrance if at_entrance is not None else None)
        elif kind == "channel_cleared":
            assert active is not None and active["actor"] == actor
            active.update(cleared_ms=t, hold_duration_ms=t-active["held_ms"],
                          physical_gap_ends_ms=t+card["channel_gap_ms"])
            holds.append(active)
            active = None
        elif kind == "channel_release_recomputed":
            hold = holds[-1]
            assert (p["slot_id"], p["actor"], t) == (hold["slot_id"], hold["actor"], hold["cleared_ms"])
            assert p["nominal_end_ms"] - p["effective_end_ms"] == p["released_early_ms"] > 0
            assert p["measured_occupancy_ms"] == hold["hold_duration_ms"]
            hold["effective_end_ms"] = p["effective_end_ms"]
            releases.append(p)
        elif kind in {"berth_hold", "physical_arrival_held", "physical_departure_held"}:
            key = kind, actor, p.get("peer"), p.get("region", p.get("node"))
            waits[key].append(t)
    assert active is None
    assert all(b["held_ms"] >= a["physical_gap_ends_ms"] for a, b in zip(holds, holds[1:]))
    for hold in holds:
        hold["grant_and_gap_end_ms"] = max(hold["cleared_ms"], hold["effective_end_ms"]) + card["channel_gap_ms"]
    tasks = {task: dict(row, slack_ms=None if row["completed_ms"] is None
                        else row["deadline_ms"]-row["completed_ms"]) for task, row in metrics["tasks"].items()}
    return dict(tasks=tasks, teams=metrics["teams"], holds=holds, releases=releases,
                total_reclaimed_ms=sum(row["released_early_ms"] for row in releases),
                violations=metrics["constraint_violations"],
                wait_event_spans=[dict(kind=k, actor=a, peer=p, region=r,
                                       count=len(v), first_ms=v[0], last_ms=v[-1])
                                  for (k, a, p, r), v in waits.items()])


def sampled_lane_occupancy(path, card, origin_ms, holds):
    west, east = sorted(card["nodes"][n][0] for n in ("E", "W"))
    # prepare_mission_world.py stops the walls 0.35 m inside the E/W centers.
    west, east = west + 0.35, east - 0.35
    axis = card["nodes"]["E"][1]
    half_width = card["physical_channel_clear_width_m"] / 2
    samples = defaultdict(list)
    for row in rows(path):
        actor = row["actor"]
        t = round(row["t_s"] * 1000) - origin_ms
        if 0 <= t <= card["end_ms"] and card["fleet"][actor]["mode"] == "ground":
            x, y, _ = row["xyz"]
            if west <= x <= east and abs(y-axis) <= half_width:
                samples[t].append(actor)
    assert samples and all(len(actors) == 1 for actors in samples.values())
    for hold in holds:
        times = [t for t, actors in samples.items()
                 if hold["held_ms"] <= t <= hold["cleared_ms"] and hold["actor"] in actors]
        assert times
        hold.update(first_lane_center_sample_ms=min(times), last_lane_center_sample_ms=max(times),
                    lane_center_samples=len(times))
    assert sum(h["lane_center_samples"] for h in holds) == len(samples)
    return dict(bounds_m=[west, east, axis-half_width, axis+half_width],
                occupied_timestamps=len(samples), cooccupied_exact_timestamps=0,
                scope="Ground vehicle center positions within the walled interior at sampled times.")


def graph_run(path):
    card, manifest = (read(path / f) for f in ("scenario.json", "manifest.json"))
    result = timeline(rows(path / "events.jsonl"), card, read(path / "metrics.json"))
    result.update(inputs={k: manifest[k] for k in ("card_file_sha256", "policy", "seed",
                                                    "code_revision", "code_dirty", "code_sha256")})
    return result


def archive_run(path, card_path, mechanism):
    m = read(path / "result/metrics.json")
    close = read(path / "result_launch/shutdown.json")
    assert m["ended"] == "full_window" and close["status"] == "COMPLETE"
    card = read(card_path)
    result = timeline(rows(path / "result/events.jsonl"), card, m["mission"])
    result["sampled_lane"] = sampled_lane_occupancy(
        path / "result/independent_truth.jsonl", card, m["origin_ms"], result["holds"])
    result.update(mechanism=mechanism, scene=close["scene"], policy=close["policy"],
                  feedback=close["feedback_mode"], sources=close["source"]["sha256"],
                  archived_card_sha256=file_hash(card_path),
                  input_sha256={p: file_hash(path/p) for p in (
                      "result/events.jsonl", "result/metrics.json", "result/independent_truth.jsonl",
                      "result_launch/shutdown.json", "result_launch/live_run.json")})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph_root", type=Path)
    parser.add_argument("archived_runs", type=Path)
    parser.add_argument("archived_scenes", type=Path)
    args = parser.parse_args()
    mechanisms = ("phase111", "release", "rolling", "joint")
    cases = ("medium_independent", "medium_adversarial", "long_independent",
             "long_adversarial", "shifted_independent")
    graph = {scene: {level: graph_run(args.graph_root / f"{scene}-{level}")
                     for level in mechanisms} for scene in cases}
    for arms in graph.values():
        baseline = arms["phase111"]
        for result in arms.values():
            assert baseline["inputs"] == result["inputs"]
            assert result["tasks"] == baseline["tasks"]
            assert not result["violations"] and not result["releases"]
            assert len(result["holds"]) == 5 and all(h["hold_duration_ms"] == 48000 for h in result["holds"])
    for layout in ("medium", "long"):
        c = [read(args.graph_root / f"{layout}_{mode}-phase111/scenario.json")
             for mode in ("independent", "adversarial")]
        assert {k for k in c[0] if c[0][k] != c[1][k]} == {"id", "target_mode"}

    archive = {}
    for run, scene, level in (
            ("fs-mechoff-ind-01", "medium_independent", "phase111"),
            ("fs-mechon-ind-01", "medium_independent", "joint"),
            ("fs-hold-long-ind-01", "long_independent", "joint")):
        archive[run] = archive_run(args.archived_runs/run,
                                   args.archived_scenes/f"scene_{scene}"/"scenario.json", level)
    off, on = (archive[n] for n in ("fs-mechoff-ind-01", "fs-mechon-ind-01"))
    assert all(off[k] == on[k] for k in ("sources", "scene", "archived_card_sha256", "policy", "feedback"))
    assert off["total_reclaimed_ms"] == 0 and on["total_reclaimed_ms"] == 114930
    entries = [next(h["held_ms"] for h in arm["holds"] if h["actor"] == "B2") for arm in (off, on)]
    assert entries[1] - entries[0] == -6612
    assert on["tasks"]["blue2"]["completed_ms"] - off["tasks"]["blue2"]["completed_ms"] == -3076
    print(json.dumps(dict(graph=graph, gazebos=archive,
                          medium_pair_delta_ms=dict(B2_hold_start=entries[1]-entries[0],
                                                   blue2_delivery=-3076)), indent=2))


if __name__ == "__main__":
    main()
