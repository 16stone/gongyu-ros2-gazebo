#!/usr/bin/env python3
"""Read-only simulated truth and independent arrival/contact checks."""
import json
import math
import os
from pathlib import Path
import sys

from controller import Supervisor

sys.path.insert(0, os.environ["GONGYU_WEBOTS_COMMON"])
from b1_experiment import CARD
from bus import Bus

run = Path(os.environ["GONGYU_RUN_DIR"])
bus = Bus(str(run / "bus"))
layout = os.environ["GONGYU_SCENE"].removeprefix("web_b1_phaseb_")
sup = Supervisor()
step = int(sup.getBasicTimeStep())
b1 = sup.getFromDef("B1")
goal = CARD["goal"]
boxes = CARD["layouts"][layout]
start_service = None
clearance = math.inf
first_contact = None
arrived = None
entered = None
exited = None
travel = 0.0
previous = None
status = "time_limit"
limit = 1024 if layout == "coverage" else CARD["limit_ms"]
while sup.step(step) != -1:
    ts = round(sup.getTime() * 1000)
    x, y, z = b1.getPosition()
    orientation = b1.getOrientation()
    yaw = math.atan2(orientation[3], orientation[0])
    if previous is not None:
        travel += math.dist(previous, (x, y))
    previous = (x, y)
    clearance = min(clearance, *(math.hypot(max(x0 - x, 0, x - x1), max(y0 - y, 0, y - y1))
                                  - CARD["model"]["footprint_radius_m"]
                                  for _, x0, x1, y0, y1, _ in boxes)) if boxes else math.inf
    # Floor/wheel support is near z=0; match other points against a configured obstacle.
    for point in b1.getContactPoints(True):
        px, py, pz = point.getPoint()
        for name, x0, x1, y0, y1, h in boxes:
            if x0 - 0.012 <= px <= x1 + 0.012 and y0 - 0.012 <= py <= y1 + 0.012 and 0.025 < pz <= h + 0.012:
                if first_contact is None:
                    first_contact = {"t_ms": ts, "object": name, "xyz": [px, py, pz], "node_id": point.getNodeId()}
                    bus.append("events.jsonl", {"kind": "obstacle_contact", **first_contact})
    if layout == "narrow":
        if entered is None and x >= 2.4:
            entered = {"t_ms": ts, "xy": [x, y], "yaw_rad": yaw}
            bus.append("events.jsonl", {"kind": "center_passed_entrance", **entered})
        if entered is not None and exited is None and x - CARD["model"]["footprint_radius_m"] >= 5.2:
            exited = {"t_ms": ts, "xy": [x, y], "yaw_rad": yaw}
            bus.append("events.jsonl", {"kind": "footprint_cleared_exit", **exited})
    bus.append("truth_B1.jsonl", {"t_ms": ts, "position": [x, y, z], "yaw_rad": yaw,
                                  "rotation": orientation})
    if math.dist((x, y), goal) <= 0.12:
        if start_service is None:
            start_service = ts
        if ts - start_service >= CARD["service_dwell_ms"]:
            arrived = ts
            status = "serviced"
            bus.append("events.jsonl", {"kind": "service_completed", "t_ms": ts, "goal": goal})
            break
    else:
        start_service = None
    if first_contact is not None and ts - first_contact["t_ms"] >= 512:
        status = "obstacle_contact"
        break
    recent_ctl = bus.last("ctl_events.jsonl")
    if recent_ctl and recent_ctl["kind"] == "scan_stop_latched" and ts - recent_ctl["t_ms"] >= 1024:
        status = "scan_safe_stop" if first_contact is None else "obstacle_contact"
        break
    if ts >= limit:
        if layout == "coverage":
            status = "stationary_sample_complete"
        break

(run / "result" / "metrics.json").write_text(json.dumps({
    "layout": layout, "end_reason": status, "t_end_ms": ts,
    "actual_path_m": travel, "minimum_clearance_circle_m": clearance if math.isfinite(clearance) else None,
    "first_obstacle_contact": first_contact, "entered": entered, "cleared": exited,
    "service_ms": arrived, "on_time": int(arrived is not None),
    "total": int(layout != "coverage"), "full_window": None,
    "violation_count": int(first_contact is not None)
}, indent=2))
(run / "shutdown.json").write_text(json.dumps({"status": "COMPLETE", "t_ms": ts, "end_reason": status}))
sup.simulationQuit(0)
