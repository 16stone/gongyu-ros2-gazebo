"""Switchable release-aware scheduling layers (phase112 architecture).

The switch is an environment variable, not a scene-card key, so every cell of a
frozen comparison can use byte-identical scenario files.  The active level is
recorded in every decision event and in the run receipt.

    GONGYU_MECH = phase111 | release | scoring | rolling | joint

    phase111  all layers off: behaviour is byte-identical to phase111_coupled_source
    release   + truncate a *used* channel grant to its measured physical clearance
    scoring   + the adversarial pressure proxy uses effective, not nominal, occupancy
    rolling   + re-plan a red route decision when a channel release is recomputed
    joint     + rank candidates jointly by blue marginal delay, red deadline margin,
                movement budget and berth availability

Nothing here changes task deadlines, the quota, the observation permissions, the
movement budget, the fleet geometry or the referee's on_time verdict.  Layers only
change what a decision maker is allowed to know and how it orders legal candidates.
"""
from __future__ import annotations

import os

LEVELS = ("phase111", "release", "scoring", "rolling", "joint")
_ORDER = {name: i for i, name in enumerate(LEVELS)}


def mechanism() -> str:
    """Read on every call so a graph-model screening loop can switch levels in-process."""
    value = os.environ.get("GONGYU_MECH", "phase111").strip().lower()
    if value not in _ORDER:
        raise ValueError("unknown GONGYU_MECH %r; expected one of %s" % (value, LEVELS))
    return value


def enabled(layer: str, mech: str | None = None) -> bool:
    if layer not in _ORDER:
        raise ValueError("unknown layer " + repr(layer))
    return _ORDER[mech or mechanism()] >= _ORDER[layer]


def measured_occupancy_ms(world) -> int | None:
    """Duration of the most recent *completed* physical channel traversal.

    `channel_enter` / `channel_cleared` are referee events from the execution layer,
    not declarations from a planner.  A grant that has not been entered contributes
    nothing.  Returns None before the first completed traversal.
    """
    # A scope answers with the value its referee broadcast, because the event
    # ledger a unit holds is filtered to its own notices.  A shared world has no
    # such attribute and falls through to the scan below.
    published = getattr(world, "channel_last_traversal_ms", None)
    if published is not None:
        return int(published)
    events = getattr(world, "events", None)
    if not events:
        return None
    entered: dict[str, int] = {}
    durations: list[int] = []
    for event in events:
        kind = getattr(event, "kind", None)
        actor = getattr(event, "actor", None)
        at = getattr(event, "t_ms", None)
        if at is None:
            continue
        if kind == "channel_enter":
            entered[actor] = at
        elif kind == "channel_cleared":
            start = entered.pop(actor, None)
            if start is not None and at > start:
                durations.append(at - start)
    return durations[-1] if durations else None


def effective_occupancy_ms(world, nominal_ms: int, gap_ms: int = 0) -> int:
    """Pressure is bounded by the real traversal, never by the nominal 48 s window."""
    measured = measured_occupancy_ms(world)
    if measured is None:
        return nominal_ms
    return min(nominal_ms, measured + gap_ms)


def berth_free(world, node: str) -> bool:
    """Whether a physical parking slot is free at `node`; graph-only worlds have no berths.

    `berth_occupancy` is the published form of the same fact (a count per node).
    An entity scope answers it from the status its referee broadcasts; a shared
    world answers it from the claims table.  Reading the table directly is only
    the fallback for worlds that predate the published count.
    """
    layout = (getattr(world, "card", {}) or {}).get("physical_berths", {}) or {}
    capacity = len(layout.get(node, []))
    if not capacity:
        return True
    occupancy = getattr(world, "berth_occupancy", None)
    if occupancy is not None:
        return int((occupancy or {}).get(node, 0)) < capacity
    berths = getattr(world, "berths", None)
    if berths is None:
        return True
    claims = getattr(berths, "claims", {}) or {}
    used = sum(1 for (actor, at) in claims if at == node)
    return used < capacity


def joint_rank_key(blue_delay_ms: int, red_margin_ms: int,
                   active_ms: int, berth_ok: bool) -> tuple:
    """Lexicographic: pressure first, then own deadline safety, then cost, then berth."""
    return (int(blue_delay_ms), int(red_margin_ms), -int(active_ms), int(bool(berth_ok)))


def describe() -> dict:
    mech = mechanism()
    return {
        "mechanism": mech,
        "levels": {k: enabled(k, mech) for k in LEVELS if k != "phase111"},
        "off_receipt": ("phase111" if mech == "phase111" else None),
        "note": "With GONGYU_MECH=phase111 every layer is off and the event stream must "
                "match phase111_coupled_source byte-for-byte on the registered cards.",
    }
