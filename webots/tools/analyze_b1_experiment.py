#!/usr/bin/env python3
"""Recalculate Phase B planner, coverage, feedback and localization evidence."""
import argparse
import csv
from hashlib import sha256
import json
import math
from pathlib import Path
import platform
import statistics
import sys
from time import perf_counter_ns

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
from b1_experiment import CARD, grid_search, grid_spec, ray_box, wheel_predict, wrap


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def read_json(path):
    return json.loads(path.read_text())


def write_csv(path, rows):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def benchmark(out, repetitions):
    rows = []
    summary = {}
    for layout in ("open", "narrow"):
        free, start, goal = grid_spec(layout)
        digest = sha256(json.dumps(sorted(free), separators=(",", ":")).encode()).hexdigest()
        summary[layout] = {"free_cells": len(free), "free_grid_sha256": digest, "start_cell": start,
                           "goal_cell": goal, "algorithms": {}}
        for i in range(repetitions + 2):
            for algorithm in (("dijkstra", "astar") if i % 2 == 0 else ("astar", "dijkstra")):
                ts = perf_counter_ns()
                _, length, expanded = grid_search(free, start, goal, algorithm)
                elapsed = perf_counter_ns() - ts
                if i >= 2:
                    rows.append({"layout": layout, "trial": i - 1, "algorithm": algorithm,
                                 "ns": elapsed, "path_m": length, "expanded_nodes": expanded,
                                 "free_grid_sha256": digest})
        for algorithm in ("dijkstra", "astar"):
            subset = [row for row in rows if row["layout"] == layout and row["algorithm"] == algorithm]
            summary[layout]["algorithms"][algorithm] = {
                "n": len(subset), "p50_ms": statistics.median(row["ns"] for row in subset) / 1e6,
                "range_ms": [fn(row["ns"] for row in subset) / 1e6 for fn in (min, max)],
                "path_m": subset[0]["path_m"], "expanded_nodes": subset[0]["expanded_nodes"]}
    write_csv(out / "plan_timing.csv", rows)
    return {"python": platform.python_version(), "host": platform.node(), "layouts": summary}


def transform(point, truth, sensor):
    local = (point[0] + sensor["x_m"], point[1], point[2] + sensor["z_local_m"])
    rotation = truth["rotation"]
    return tuple(truth["position"][i] + sum(a*b for a, b in zip(local, rotation[3*i:3*i+3]))
                 for i in range(3))


def target_returns(row, truth, mode, box):
    _, x0, x1, y0, y1, top = box
    sensor = CARD["sensors"][mode]
    origin = transform((0, 0, 0), truth, sensor)
    desired = math.atan2((y0+y1)/2 - origin[1], (x0+x1)/2 - origin[0])
    results = []
    for point in row[f"{mode}_xyz"]:
        if point is None:
            continue
        x, y, z = transform(point, truth, sensor)
        if not (x0 - 0.035 <= x <= x1 + 0.035 and y0 - 0.035 <= y <= y1 + 0.035
                and 0 <= z <= top + 0.015):
            continue
        beam_angle = math.atan2(y-origin[1], x-origin[0])
        expected = ray_box(origin[:2], beam_angle, (x0, x1, y0, y1))
        if expected is None:
            continue
        measured = math.hypot(x-origin[0], y-origin[1])
        angle_error = abs(wrap(beam_angle - desired))
        results.append({"t_ms": row["t_ms"], "range_m": measured, "box_range_on_ray_m": expected,
                        "range_error_m": measured - expected,
                        "bearing_deg": math.degrees(wrap(beam_angle-truth["yaw_rad"])),
                        "centroid_bearing_deg": math.degrees(wrap(desired-truth["yaw_rad"])),
                        "bearing_offset_deg": math.degrees(angle_error)})
    return results


def run_results(run):
    plan = read_json(run / "result/plan.json")
    metrics = read_json(run / "result/metrics.json")
    shutdown = read_json(run / "shutdown.json")
    assert shutdown["status"] == "COMPLETE", run
    telemetry = records(run / "bus/tel_B1.jsonl")
    truth = {row["t_ms"]: row for row in records(run / "bus/truth_B1.jsonl")}
    assert all(row["t_ms"] in truth for row in telemetry), run
    ctl_path = run / "bus/ctl_events.jsonl"
    ctl = records(ctl_path) if ctl_path.exists() else []
    plan_keys = ("layout", "algorithm", "low_scan_used", "grid_path_m", "expanded_nodes", "targets")
    result = {"id": run.name, **{key: plan[key] for key in plan_keys}, **metrics,
              "timestamps_matched": len(telemetry), "lidars": plan["lidars"],
              "scan_stop_latched": next((event for event in ctl if event["kind"] == "scan_stop_latched"), None)}
    if plan["layout"] in ("coverage", "lowobs"):
        returns = {}
        for box in CARD["layouts"][plan["layout"]]:
            returns[box[0]] = {}
            for mode in ("main", "low"):
                if plan["layout"] == "coverage":
                    row = telemetry[len(telemetry) // 2]
                    hits = target_returns(row, truth[row["t_ms"]], mode, box)
                else:
                    hits = []
                    for row in telemetry:
                        hits = target_returns(row, truth[row["t_ms"]], mode, box)
                        if hits:
                            break
                returns[box[0]][mode] = min(hits, key=lambda p: p["bearing_offset_deg"], default=None)
        result["target_returns"] = returns
    return result, telemetry, truth


def solve_3(matrix, rhs):
    data = [row[:] + [v] for row, v in zip(matrix, rhs)]
    for k in range(3):
        pivot = max(range(k, 3), key=lambda i: abs(data[i][k]))
        data[k], data[pivot] = data[pivot], data[k]
        scale = data[k][k]
        data[k] = [v/scale for v in data[k]]
        for i in range(3):
            if i != k:
                scale = data[i][k]
                data[i] = [a-scale*b for a, b in zip(data[i], data[k])]
    return [row[3] for row in data]


def scan_correct(prior, cloud):
    """Bounded point-to-wall fit with wheel prior; parallel faces cannot fix longitudinal drift."""
    faces = []
    for _, a, b, c, d, _ in CARD["layouts"]["narrow"]:
        faces.extend(((0, a, c, d), (0, b, c, d), (1, c, a, b), (1, d, a, b)))
    points = [(p[0] + CARD["sensors"]["main"]["x_m"], p[1])
              for p in cloud[::2] if p is not None]
    estimate = prior
    associations = 0
    for _ in range(4):
        x, y, yaw = estimate
        cos_yaw, sin_yaw = math.cos(yaw), math.sin(yaw)
        penalty = (4.0, 4.0, 9.0)
        lhs = [[penalty[i] if i == j else 0.0 for j in range(3)] for i in range(3)]
        rhs = [v * (a - b) for v, a, b in zip(penalty, prior, estimate)]
        rhs[2] = penalty[2] * wrap(prior[2] - yaw)
        associations = 0
        for u, v in points:
            rx, ry = cos_yaw*u - sin_yaw*v, sin_yaw*u + cos_yaw*v
            point = (x + rx, y + ry)
            candidates = [(abs(point[axis] - coord), point[axis] - coord, axis)
                          for axis, coord, lo, hi in faces
                          if lo + 0.015 <= point[1-axis] <= hi - 0.015]
            if not candidates:
                continue
            abs_r, residual, axis = min(candidates)
            if abs_r > 0.15:
                continue
            associations += 1
            weight = min(1.0, 0.045 / max(abs_r, 1e-6))
            derivative = (1, 0, -ry) if axis == 0 else (0, 1, rx)
            for i in range(3):
                rhs[i] -= weight * derivative[i] * residual
                for j in range(3):
                    lhs[i][j] += weight * derivative[i] * derivative[j]
        if associations < 6:
            return prior, 0
        dx, dy, dyaw = solve_3(lhs, rhs)
        estimate = x + max(-0.045, min(0.045, dx)), y + max(-0.045, min(0.045, dy)), wrap(yaw + max(-0.05, min(0.05, dyaw)))
    return estimate, associations


def localization(telemetry, truth):
    odom = fused = tuple(CARD["start"])
    enc_last = telemetry[0]["encoders_rad"]
    result = []
    for reading in telemetry:
        ts = reading["t_ms"]
        current = reading["encoders_rad"]
        dr, dl = (b - a for a, b in zip(enc_last, current))
        enc_last = current
        odom = wheel_predict(odom, dr, dl)
        fused, matches = scan_correct(wheel_predict(fused, dr, dl), reading["main_xyz"])
        target = truth[ts]
        xy = target["position"][:2]
        yaw = target["yaw_rad"]
        segment = ("approach" if xy[0] < 2.4 else "aisle" if xy[0] < 5.2 else "exit_turn")
        result.append({"t_ms": ts, "segment": segment, "truth_x": xy[0], "truth_y": xy[1],
                       "truth_yaw": yaw, "odom_x": odom[0], "odom_y": odom[1], "odom_yaw": odom[2],
                       "fused_x": fused[0], "fused_y": fused[1], "fused_yaw": fused[2],
                       "odom_xy_err_m": math.dist(odom[:2], xy), "fused_xy_err_m": math.dist(fused[:2], xy),
                       "odom_yaw_err_deg": math.degrees(abs(wrap(odom[2] - yaw))),
                       "fused_yaw_err_deg": math.degrees(abs(wrap(fused[2] - yaw))), "wall_matches": matches})
    summary = {}
    for segment in ("all", "approach", "aisle", "exit_turn"):
        data = [row for row in result if segment == "all" or row["segment"] == segment]
        if not data:
            continue
        metrics = ("odom_xy_err_m", "fused_xy_err_m", "odom_yaw_err_deg", "fused_yaw_err_deg")
        summary[segment] = {"n": len(data), "with_wall_matches": sum(row["wall_matches"] > 0 for row in data),
                            **{key: math.sqrt(statistics.mean(row[key]**2 for row in data)) for key in metrics}}
    return result, summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    parser.add_argument("--repetitions", type=int, default=31)
    parser.add_argument("--run", type=Path, action="append", default=[])
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    assert args.repetitions > 0
    summary = {"planner": benchmark(args.out, args.repetitions), "runs": [], "localization": {}}
    for run in args.run:
        result, telemetry, truth = run_results(run)
        summary["runs"].append(result)
        if result["layout"] == "narrow" and result["service_ms"] is not None:
            data, metrics = localization(telemetry, truth)
            write_csv(args.out / f"loc_{run.name}.csv", data)
            summary["localization"][run.name] = metrics
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
