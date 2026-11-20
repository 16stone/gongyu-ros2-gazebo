"""B1's measured local replan during the optional eight-entity low-box trial."""
import math

from b1_experiment import CARD, GRID_M, ORIGIN_X, ORIGIN_Y, low_scan_bypass, world_point

SCENE = "web_medium_phys_lowbox"


def near_front_range(scan):
    return min((distance for x, y, _ in scan if x > 0
                and abs(math.atan2(y, x)) <= math.radians(CARD["front_angle_deg"])
                if (distance := math.hypot(x, y)) <= CARD["stop_range_m"]), default=None)


def east_apron_bypass(pose, goal, scan):
    # The apron bounds are known; the low box is estimated from the new returns.
    def cell(point):
        return tuple(round((value - origin) / GRID_M)
                     for value, origin in zip(point, (ORIGIN_X, ORIGIN_Y)))

    start_i, start_j = cell((6.25, 1.65))
    end_i, end_j = cell((8.60, 3.30))
    free = set()
    for i in range(start_i, end_i + 1):
        for j in range(start_j, end_j + 1):
            x, y = world_point((i, j))
            if x < 7.0 or y >= 2.04:
                free.add((i, j))
    returns = [p for p in scan if math.hypot(*p[:2]) <= CARD["stop_range_m"] + 0.20]
    return low_scan_bypass(free, cell(goal), "astar", pose, returns, depth_m=0.30)
