"""Frozen physical logistics cases for the remaining Webots matrix rows."""

from math import dist

NOMINAL_CLEAR_MS = 32000
LONG_ROUTE = ((1.0, -12.6), (6.0, -12.6), (6.0, -1.1))
STARTS = {
    "web_long": {"B1": (1.43, 0.0), "B2": (0.50, 0.0), "R1": (1.0, -1.1)},
    "web_cost": {"B1": (0.0, -1.5), "B2": (5.5, -1.5)},
}
DELIVERY = (8.0, -1.5)
PROVIDER_HOME = (3.0, -4.0)
PROVIDER_DEADLINE_MS = {"low": 50000, "high": 23000}


def dispatch_due(now, early_release, cleared):
    return cleared and (early_release or now >= NOMINAL_CLEAR_MS)


def choose_support(provider_deadline_ms):
    requester, provider = STARTS["web_cost"].values()
    # This is an explicit forecast, evaluated separately from physical arrivals.
    def travel_ms(a, b):
        return round(1000 * dist(a, b) / 0.40)

    requester_leg = travel_ms(requester, DELIVERY)
    support_leg = travel_ms(provider, DELIVERY)
    return_leg = travel_ms(DELIVERY, PROVIDER_HOME)
    direct_leg = travel_ms(provider, PROVIDER_HOME)
    stop_allowance_ms = 4000
    direct_return_ms = direct_leg + stop_allowance_ms
    support_return_ms = support_leg + return_leg + 2 * stop_allowance_ms
    delivery_gain_ms = requester_leg - support_leg
    extra_work_ms = support_leg + return_leg - direct_leg
    accepted = support_return_ms <= provider_deadline_ms and delivery_gain_ms > extra_work_ms
    return {
        "carrier": "B2" if accepted else "B1",
        "decision": "accept" if accepted else "reject",
        "provider_deadline_ms": provider_deadline_ms,
        "direct_return_ms": direct_return_ms,
        "support_return_ms": support_return_ms,
        "delivery_gain_ms": delivery_gain_ms,
        "extra_work_ms": extra_work_ms,
    }
