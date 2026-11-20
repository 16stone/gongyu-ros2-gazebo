"""Shared scene geometry, paired graph search and B1 experiment math."""
import heapq
import json
import math
from pathlib import Path

CARD = json.loads((Path(__file__).resolve().parents[1] / "config" / "b1_experiment.json").read_text())
GRID_M = CARD["grid_m"]
ORIGIN_X, _, ORIGIN_Y, _ = CARD["bounds"]
DIAGONAL = math.sqrt(2)
MOTIONS = ((1, 0), (0, 1), (0, -1), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1))


def wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


def world_point(cell):
    return [round(origin + i * GRID_M, 8) for origin, i in zip((ORIGIN_X, ORIGIN_Y), cell)]


def grid_spec(layout):
    x0, x1, y0, y1 = CARD["bounds"]
    obstacles = [] if layout in ("lowobs", "coverage") else CARD["layouts"][layout]
    inflation = CARD["inflation_m"]
    free = set()
    for i in range(round((x1 - x0) / GRID_M) + 1):
        for j in range(round((y1 - y0) / GRID_M) + 1):
            x, y = world_point((i, j))
            if all(math.hypot(max(a - x, 0, x - b), max(c - y, 0, y - d)) > inflation
                   for _, a, b, c, d, _ in obstacles):
                free.add((i, j))
    start, goal = (tuple(round((v - o) / GRID_M) for v, o in zip(point, (x0, y0)))
                   for point in (CARD["start"], CARD["goal"]))
    return free, start, goal


def grid_search(free, start, goal, algorithm):
    if algorithm not in ("dijkstra", "astar"):
        raise ValueError(f"unknown planner: {algorithm}")
    if start not in free or goal not in free:
        raise ValueError("occupied start or goal")

    def heuristic(cell):
        if algorithm == "dijkstra":
            return 0.0
        dx, dy = sorted(abs(a - b) for a, b in zip(cell, goal))
        return dx * DIAGONAL + dy - dx

    frontier = [(heuristic(start), 0.0, start)]
    distance = {start: 0.0}
    parent = {}
    settled = set()
    while frontier:
        _, cost, cell = heapq.heappop(frontier)
        if cell in settled:
            continue
        settled.add(cell)
        if cell == goal:
            path = [goal]
            while path[-1] != start:
                path.append(parent[path[-1]])
            return path[::-1], cost * GRID_M, len(settled)
        x, y = cell
        for dx, dy in MOTIONS:
            nxt = x + dx, y + dy
            if nxt not in free or (x + dx, y) not in free or (x, y + dy) not in free:
                continue
            value = cost + (DIAGONAL if dx and dy else 1)
            if value + 1e-9 < distance.get(nxt, math.inf):
                distance[nxt] = value
                parent[nxt] = cell
                heapq.heappush(frontier, (value + heuristic(nxt), value, nxt))
    raise ValueError("no grid path")


def tracking_targets(path, free):
    """Simplify the cell path only where a segment stays inside free cells."""
    def visible(a, b):
        steps = 2 * max(abs(b[0] - a[0]), abs(b[1] - a[1]))
        previous = a
        for i in range(1, steps + 1):
            here = tuple(round(x + i * (y - x) / steps) for x, y in zip(a, b))
            if (here not in free or (previous[0], here[1]) not in free
                    or (here[0], previous[1]) not in free):
                return False
            previous = here
        return True

    waypoints = []
    index = 0
    while index < len(path) - 1:
        furthest = next(i for i in range(len(path) - 1, index, -1)
                        if visible(path[index], path[i]))
        waypoints.append(world_point(path[furthest]))
        index = furthest
    return waypoints


def low_scan_bypass(free, goal, algorithm, pose, scan):
    # shortcut: a single static box is bounded from its observed facade in this fixture;
    # replace with a fused local occupancy map when validating arbitrary obstacle geometry.
    x, y, yaw = pose
    cosine, sine = math.cos(yaw), math.sin(yaw)
    offset = CARD["sensors"]["low"]["x_m"]
    returns = [(x + cosine * (px + offset) - sine * py,
                y + sine * (px + offset) + cosine * py)
               for px, py, _ in (point for point in scan if point)
               if px > 0 and math.hypot(px, py) <= 1.0]
    if len(returns) < 3:
        raise ValueError("insufficient low scan returns for bypass")
    observed_x, observed_y = zip(*returns)
    bounds = min(observed_x), max(observed_x) + 0.45, min(observed_y) - 0.07, max(observed_y) + 0.07
    a, b, c, d = bounds
    margin = max(CARD["inflation_m"], CARD["model"]["footprint_radius_m"] +
                 CARD["target_tolerance_m"] + GRID_M)
    replanned_free = set()
    for cell in free:
        wx, wy = world_point(cell)
        if math.hypot(max(a - wx, 0, wx - b), max(c - wy, 0, wy - d)) > margin:
            replanned_free.add(cell)
    start = tuple(round((value - origin) / GRID_M)
                  for value, origin in zip((x, y), (ORIGIN_X, ORIGIN_Y)))
    path, _, _ = grid_search(replanned_free, start, goal, algorithm)
    return tracking_targets(path, replanned_free), bounds


def wheel_predict(pose, right_rad, left_rad):
    """The right wheel is named left_motor in this Webots model."""
    x, y, yaw = pose
    radius = CARD["model"]["wheel_radius_m"]
    step = radius * (right_rad + left_rad) / 2
    turn = radius * (right_rad - left_rad) / CARD["model"]["wheel_track_m"]
    return x + step * math.cos(yaw + turn / 2), y + step * math.sin(yaw + turn / 2), wrap(yaw + turn)


def drive(pose, target, stop):
    if stop or target is None:
        return 0.0, 0.0
    dx, dy = target[0] - pose[0], target[1] - pose[1]
    error = wrap(math.atan2(dy, dx) - pose[2])
    speed = min(0.50, max(0.08, 0.75 * math.hypot(dx, dy))) if abs(error) <= 0.42 else 0.0
    omega = max(-0.8, min(0.8, 2.2 * error))
    radius = CARD["model"]["wheel_radius_m"]
    half_track = CARD["model"]["wheel_track_m"] / 2
    return tuple(max(-6, min(6, v / radius))
                 for v in (speed + omega * half_track, speed - omega * half_track))


def ray_box(origin, angle, box):
    x, y = origin
    near, far = 0.0, math.inf
    for p, v, a, b in ((x, math.cos(angle), box[0], box[1]), (y, math.sin(angle), box[2], box[3])):
        if abs(v) < 1e-10:
            if not a <= p <= b:
                return None
        else:
            entry, exit_ = sorted(((a - p) / v, (b - p) / v))
            near, far = max(near, entry), min(far, exit_)
    return near if near <= far else None
