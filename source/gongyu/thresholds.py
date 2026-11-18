"""Response-threshold role selection: who takes a support role, decided without an assignment.

The division-of-labour models this project borrows from (Bonabeau et al. 1999; Jeanson et al. 2005)
have no coordinator naming a worker. An individual responds to a task when the stimulus it
perceives for that task reaches its own threshold, and performing the task lowers that threshold
while going without it raises it, so roles consolidate through use rather than through orders.

The relay role in `gongyu.patrol` is the one place in this model with a real pool of candidates --
R3 and R4 can both forward R5's inspection report, and each pays for it out of its own return
budget -- so that is where the rule is implemented. The threshold is internal state that lives
*between* episodes on purpose: inside one mission a relay unit forwards at most one report, so
there is nothing for reinforcement to consolidate until several missions have run.

What is deliberately not here: the negative-feedback term of the biological model, in which the
stimulus shrinks because other workers are already engaged. A relay unit cannot observe a peer's
engagement -- the offers travel to R5, not between providers -- so implementing it would mean
handing the model information no agent has. The stimulus is therefore the requester's own deadline
pressure, which the request itself carries.
"""
from __future__ import annotations

ACTIVE = None

FLOOR = 0.05
CAP = 0.95
REINFORCE_DOWN = 0.15
REINFORCE_UP = 0.10


def attach(state):
    """Install the threshold ledger the controllers consult, or take it away again."""
    global ACTIVE
    ACTIVE = state
    return state


def stimulus(now_ms, deadline_ms):
    """How much of the requester's own deadline it has already spent, in [0, 1].

    The requester knows its deadline and the provider does not, so the request carries the pair and
    the provider forms the stimulus from it. Before the request there is no stimulus to sense, which
    is why threshold mode answers requests instead of advertising.
    """
    if deadline_ms is None or deadline_ms <= 0:
        return 0.0
    return min(1.0, max(0.0, now_ms / deadline_ms))


class Thresholds:
    """Per-unit thresholds, optionally reinforced by what the unit actually did."""

    def __init__(self, initial, reinforced=True):
        self.value = dict(initial)
        self.reinforced = bool(reinforced)
        self.served = {actor: 0 for actor in initial}
        self.withheld = {actor: 0 for actor in initial}
        self.log = []

    def threshold(self, actor):
        return self.value.setdefault(actor, 0.5)

    def volunteers(self, actor, stimulus_value):
        before = self.threshold(actor)
        answers = stimulus_value >= before
        if not answers and self.reinforced:
            self.value[actor] = min(CAP, before + REINFORCE_UP)
            self.withheld[actor] += 1
        self.log.append({'actor': actor, 'stimulus': round(stimulus_value, 4),
                         'threshold_before': round(before, 4),
                         'threshold_after': round(self.threshold(actor), 4), 'answers': answers})
        return answers

    def record_service(self, actor):
        if self.reinforced:
            self.value[actor] = max(FLOOR, self.threshold(actor) - REINFORCE_DOWN)
        self.served[actor] += 1

    def snapshot(self):
        return {'thresholds': {a: round(v, 4) for a, v in sorted(self.value.items())},
                'served': dict(sorted(self.served.items())),
                'withheld': dict(sorted(self.withheld.items())),
                'reinforced': self.reinforced}
