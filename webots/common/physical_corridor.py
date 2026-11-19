"""Staging and footprint checks for Webots' motor-driven transport routes."""

from math import hypot

# The generated rails actually extend from x=1.9 to x=5.1.
RAIL_WEST, RAIL_EAST = 1.90, 5.10
LANE_HALF_WIDTH = 0.55
# Conservative enclosing radius for the 0.40 x 0.34 chassis, wheels and casters.
HULL_RADIUS = 0.28
STAGING = {
    "west_gate": (1.45, 0.00),
    "east_gate": (5.60, 0.00),
    "west_turn": (1.34, -0.85),
    "west_pickup": (1.20, -1.85),
    "west_park": (1.34, 0.88),
    "east_north_start": (5.60, 0.95),
    "east_south_start": (5.60, -0.95),
    "east_straight": (6.50, 0.00),
    "east_north": (6.50, 1.80),
    "east_north_upper": (6.50, 2.95),
    "east_park": (6.05, 0.78),
    "blue_source": (0.50, 0.00),
    "blue_relay": (8.00, 1.60),
    "blue_delivery": (8.00, 2.40),
    "red_turnaround": (8.00, 2.95),
    "blue_return": (0.97, 0.00),
}

# Serve the early red delivery first. The two blue tasks and the later red
# delivery share the narrow approaches as well as the corridor itself.
CARRIER_ORDER = ("R2", "B1", "B2", "R1")
TRANSPORT_ROUTES = {
    "R2": (("east_north_start", None), ("east_gate", None), ("west_gate", None),
           ("west_pickup", None),
           ("west_gate", None), ("east_gate", None), ("east_straight", None),
           ("east_park", "red2")),
    "B1": (("blue_source", None), ("west_gate", None), ("east_gate", None),
           ("east_straight", None), ("east_north", None), ("blue_delivery", "blue1")),
    "B2": (("blue_relay", None), ("east_north", None), ("east_straight", None),
           ("east_gate", None), ("west_gate", None), ("blue_return", "blue2")),
    "R1": (("east_south_start", None), ("east_gate", None), ("east_straight", None),
           ("east_north", None), ("east_north_upper", None), ("red_turnaround", None),
           ("east_north_upper", None), ("east_north", None), ("east_straight", None),
           ("east_gate", None), ("west_gate", None), ("west_park", "red1")),
}


def occupies_corridor(x, y):
    dx = max(RAIL_WEST - x, 0.0, x - RAIL_EAST)
    dy = max(0.0, abs(y) - LANE_HALF_WIDTH)
    return hypot(dx, dy) <= HULL_RADIUS
