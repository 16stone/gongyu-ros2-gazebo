"""Execute and independently judge physical logistics matrix cases."""

from itertools import combinations
import json
from math import dist, hypot
import os
from pathlib import Path
import sys

from controller import Supervisor

sys.path.insert(0, os.environ["GONGYU_WEBOTS_COMMON"])
from bus import Bus
from course_matrix import (DELIVERY, LONG_ROUTE, NOMINAL_CLEAR_MS, PROVIDER_DEADLINE_MS,
                           PROVIDER_HOME, STARTS, choose_support, dispatch_due)
from physical_corridor import HULL_RADIUS, occupies_corridor

run = Path(os.environ["GONGYU_RUN_DIR"])
bus = Bus(str(run / "bus"))
scene = os.environ["GONGYU_SCENE"]
if os.environ.get("GONGYU_PHYS") != "1":
    raise ValueError("The matrix cases require GONGYU_PHYS=1")

supervisor = Supervisor()
step_ms = int(supervisor.getBasicTimeStep())
robots = {actor: supervisor.getFromDef(actor) for actor in STARTS[scene]}
routes = {}
current = {}
settled_since = {}
finished = {}
occupied = set()
clear_b1 = False
destination_reserved = False
wait_logged = False
holds_release_until = 0
channel_case = scene in {"web_long", "web_medium_exit"}
following_goal = (6.4, 0.0)
paths_m = dict.fromkeys(robots, 0.0)
previous = {actor: robot.getPosition()[:2] for actor, robot in robots.items()}
minimum_separation = float("inf")
min_lane_margin = None
overlap_samples = 0
vehicle_overlap_samples = 0
now = 0
last_sample = -1000


def event(kind, actor=None, **fields):
    bus.append("events.jsonl", {"t_ms": now, "kind": kind, "actor": actor, **fields})


def send_next(actor):
    goal, task = routes[actor].pop(0)
    command = {
        "id": f"{actor}-{now}", "type": "goto", "x": goal[0], "y": goal[1],
        "t_ms": now, "task_id": task, "node": task or "via",
    }
    bus.append(f"cmd_{actor}.jsonl", command)
    current[actor] = (goal, task)
    event("dispatch", actor, goal=goal, task_id=task)


if scene == "web_long":
    rule = {"phase111": False, "release": True}[os.environ["GONGYU_MECH"]]
    routes = {
        "B1": [((7.6, 0.0), "first_delivery")],
        "B2": [(following_goal, "following_delivery")],
        "R1": [(point, None) for point in LONG_ROUTE[:-1]] + [(LONG_ROUTE[-1], "long_delivery")],
    }
    deadlines = {"first_delivery": 30000, "following_delivery": 65000, "long_delivery": 135000}
    settings = {"early_release": rule, "nominal_clear_ms": NOMINAL_CLEAR_MS}
    end_ms = 140000
    send_next("B1")
    send_next("R1")
elif scene == "web_medium_exit":
    check_destination = {"off": False, "on": True}[os.environ["GONGYU_MATRIX_EXIT_CHECK"]]
    routes = {"B1": [(following_goal, None), ((7.6, 0.0), "first_delivery")],
              "B2": [(following_goal, "following_delivery")]}
    deadlines = {"first_delivery": 55000, "following_delivery": 65000}
    settings = {"early_release": True, "exit_check": check_destination, "berth": following_goal}
    rule = True
    end_ms = 65000
    destination_reserved = True
    holds_release_until = 28000
    send_next("B1")
else:
    cost = os.environ["GONGYU_COST"]
    provider_deadline = PROVIDER_DEADLINE_MS[cost]
    settings = {"cost": cost, **choose_support(provider_deadline)}
    carrier = settings["carrier"]
    deadlines = {"delivery": 42000, "provider_return": provider_deadline}
    end_ms = 60000
    routes = {"B1": [], "B2": [(PROVIDER_HOME, "provider_return")]}
    routes[carrier].insert(0, (DELIVERY, "delivery"))
    event("opportunity_cost_decision", carrier, **settings)
    if routes["B1"]:
        send_next("B1")
    send_next("B2")

while supervisor.step(step_ms) != -1:
    now = round(1000 * supervisor.getTime())
    positions = {actor: robot.getPosition() for actor, robot in robots.items()}
    separation = min(dist(a[:2], b[:2]) for a, b in combinations(positions.values(), 2))
    minimum_separation = min(minimum_separation, separation)
    vehicle_overlap_samples += separation < 2 * HULL_RADIUS
    for actor, position in positions.items():
        paths_m[actor] += dist(previous[actor], position[:2])
        previous[actor] = position[:2]
    if channel_case:
        inside_now = {actor for actor, (x, y, _) in positions.items() if occupies_corridor(x, y)}
        for actor in sorted(inside_now - occupied):
            event("channel_enter", actor)
        for actor in sorted(occupied - inside_now):
            event("channel_clear", actor)
            if actor == "B1":
                clear_b1 = True
        occupied = inside_now
        overlap_samples += len(occupied) > 1
        for x, y, _ in positions.values():
            if 1.90 <= x <= 5.10 and abs(y) < 0.55:
                margin = 0.51 - abs(y) - HULL_RADIUS
                min_lane_margin = margin if min_lane_margin is None else min(margin, min_lane_margin)
        if (destination_reserved and current.get("B1", (following_goal, None))[0] != following_goal
                and dist(positions["B1"][:2], following_goal) >= 0.70):
            destination_reserved = False
            event("destination_cleared", "B1", goal=following_goal, position=positions["B1"])
        destination_clear = not settings.get("exit_check", False) or not destination_reserved
        entrance_clear = clear_b1 and not occupied
        if routes["B2"] and dispatch_due(
                now, rule, entrance_clear, destination_clear=destination_clear):
            send_next("B2")
        elif routes["B2"] and entrance_clear and not destination_clear and not wait_logged:
            wait_logged = True
            event("dispatch_held_for_destination", "B2", goal=following_goal)
    for actor, (goal, task) in list(current.items()):
        speed = hypot(*robots[actor].getVelocity()[:2])
        if dist(positions[actor][:2], goal) > 0.10 or speed > 0.10:
            settled_since.pop(actor, None)
            continue
        if now - settled_since.setdefault(actor, now) < 800:
            continue
        if actor == "B1" and goal == following_goal and now < holds_release_until:
            continue
        settled_since.pop(actor)
        del current[actor]
        event("goal_dwell", actor, goal=goal, position=positions[actor], task_id=task)
        if task is not None:
            finished[task] = {"actor": actor, "t_ms": now, "deadline_ms": deadlines[task],
                              "on_time": now <= deadlines[task]}
            event("task_completed", **finished[task], task_id=task)
        if routes[actor]:
            send_next(actor)
    if now - last_sample >= 256:
        last_sample = now
        bus.append("poses.jsonl", {"t_ms": now, "positions": positions})
    if now >= end_ms:
        break

metrics = {
    "scene": scene, "motion_backend": "ugv_wheel_motors", "settings": settings,
    "task_completed": finished, "total": len(deadlines), "deadlines_ms": deadlines,
    "on_time": sum(result["on_time"] for result in finished.values()),
    "full_window": now >= end_ms, "sim_end_ms": now,
    "channel_overlap_samples": overlap_samples,
    "vehicle_envelope_overlap_samples": vehicle_overlap_samples,
    "violation_count": overlap_samples + vehicle_overlap_samples,
    "min_vehicle_separation_m": minimum_separation,
    "min_lane_envelope_margin_m": min_lane_margin,
    "paths_m": paths_m,
}
(run / "result" / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
(run / "shutdown.json").write_text(json.dumps({"status": "COMPLETE", "sim_end_ms": now}) + "\n",
                                   encoding="utf-8")
supervisor.simulationQuit(0)
