#!/usr/bin/env python3
"""B1 experiment controller. Pose feedback is the simulated GPS and IMU."""
import json
import math
import os
from pathlib import Path
import sys
from time import perf_counter_ns

from controller import Robot

sys.path.insert(0, os.environ["GONGYU_WEBOTS_COMMON"])
from b1_experiment import (CARD, drive, experiment_layout, grid_search, grid_spec, low_scan_bypass,
                           segment_distance, tracking_targets, world_point)
from bus import Bus

run = Path(os.environ["GONGYU_RUN_DIR"])
bus = Bus(str(run / "bus"))
layout = experiment_layout(os.environ["GONGYU_SCENE"])
algorithm = os.environ.get("GONGYU_B1_PLANNER", "astar")
use_low = os.environ.get("GONGYU_B1_LOW", "1") == "1"
bypass = os.environ.get("GONGYU_B1_BYPASS", "0") == "1"

robot = Robot()
step = int(robot.getBasicTimeStep())
gps, imu, left, right = [robot.getDevice(key) for key in ("gps", "imu", "left_sensor", "right_sensor")]
main, low = [robot.getDevice(key) for key in ("lidar_main", "lidar_low")]
motors = [robot.getDevice(key) for key in ("left_motor", "right_motor")]
for dev in (gps, imu, left, right, main, low):
    dev.enable(step)
for lidar in (main, low):
    lidar.enablePointCloud()
for motor in motors:
    motor.setPosition(float("inf"))
    motor.setVelocity(0.0)

free, start, goal = grid_spec(layout)
started = perf_counter_ns()
path, length, expanded = grid_search(free, start, goal, algorithm)
elapsed = perf_counter_ns() - started
targets = tracking_targets(path, free) if layout != "coverage" else []
(run / "result" / "plan.json").write_text(json.dumps({
    "layout": layout, "algorithm": algorithm, "low_scan_used": use_low, "bypass_enabled": bypass,
    "search_ns": elapsed, "grid_path_m": length, "expanded_nodes": expanded,
    "path": [world_point(cell) for cell in path], "targets": targets,
    "lidars": [{"count": lidar.getNumberOfPoints(), "fov": lidar.getFov(),
                "min_m": lidar.getMinRange(), "max_m": lidar.getMaxRange(),
                "sampling_ms": lidar.getSamplingPeriod()} for lidar in (main, low)]
}, indent=2))


def points(lidar):
    return [[round(p.x, 5), round(p.y, 5), round(p.z, 5)]
            if all(math.isfinite(a) for a in (p.x, p.y, p.z)) else None
            for p in lidar.getPointCloud()]


def front_return(cloud):
    half_angle = math.radians(CARD["front_angle_deg"])
    returns = [(math.hypot(x, y), math.atan2(y, x)) for x, y, _ in (p for p in cloud if p)
               if x > 0 and abs(math.atan2(y, x)) <= half_angle]
    return min(returns, default=(None, None))


index = 0
blocked = False
replan_at = None
replanned = False
gate_ready = layout != "gate"
while robot.step(step) != -1:
    t = round(robot.getTime() * 1000)
    x, y, _ = gps.getValues()
    pose = x, y, imu.getRollPitchYaw()[2]
    scan_main, scan_low = points(main), points(low)
    front_main, angle_main = front_return(scan_main)
    front_low, angle_low = front_return(scan_low)

    guard = [(front_main, "main"), (front_low, "low")] if use_low else [(front_main, "main")]
    if layout == "lowobs" and not blocked and not replanned:
        triggered = [(distance, source) for distance, source in guard
                     if distance is not None and distance <= CARD["stop_range_m"]]
        if triggered:
            blocked = True
            distance, source = min(triggered)
            bus.append("ctl_events.jsonl", {"kind": "scan_stop_latched", "t_ms": t, "source": source,
                                           "distance_m": distance, "low_scan_used": use_low})
            if bypass and source == "low":
                replan_at = t + 320
    if replan_at is not None and t >= replan_at:
        replan_at = None
        try:
            targets, observed_bounds = low_scan_bypass(free, goal, algorithm, pose, scan_low)
        except ValueError as error:
            bus.append("ctl_events.jsonl", {"kind": "scan_replan_failed", "t_ms": t, "reason": str(error)})
        else:
            index = 0
            blocked = False
            replanned = True
            bus.append("ctl_events.jsonl", {"kind": "scan_replan_applied", "t_ms": t,
                                           "inferred_bounds_m": observed_bounds, "targets": targets})
    if not gate_ready:
        grant = bus.last("gate_grant.jsonl")
        if grant is not None:
            point = CARD["gate"]["alignment_m"]
            distance = segment_distance(point, grant["peer_origin_m"], grant["peer_target_m"])
            enabled = os.environ.get("GONGYU_B1_GATE_ALIGN", "0") == "1"
            use_alignment = enabled and distance >= CARD["gate"]["min_peer_path_clearance_m"]
            if use_alignment:
                targets.insert(0, point)
            bus.append("ctl_events.jsonl", {"kind": "gate_alignment_checked", "t_ms": t,
                       "granted": True, "peer_path_clearance_m": distance,
                       "alignment_enabled": enabled, "alignment_selected": use_alignment,
                       "alignment_target": point if use_alignment else None})
            gate_ready = True
    if gate_ready and index < len(targets) and math.dist(pose[:2], targets[index]) <= CARD["target_tolerance_m"]:
        bus.append("ctl_events.jsonl", {"kind": "tracked_waypoint", "t_ms": t, "target": targets[index]})
        index += 1
    target = targets[index] if gate_ready and index < len(targets) else None
    commands = drive(pose, target, blocked)
    for motor, v in zip(motors, commands):
        motor.setVelocity(v)
    if t % (4 * step) == 0:
        bus.append("tel_B1.jsonl", {"t_ms": t, "pose_feedback": pose, "encoders_rad": [left.getValue(), right.getValue()],
                                  "main_xyz": scan_main, "low_xyz": scan_low,
                                  "front_main": [front_main, angle_main], "front_low": [front_low, angle_low],
                                  "motor_velocity_rad_s": commands, "target": target, "scan_stop_latched": blocked})
