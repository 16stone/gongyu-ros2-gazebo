"""One runtime per entity, one referee for the world.

`simulate()` used to be a single loop that called every controller with the same
`World`. The loop is unchanged in order and timing, but each controller now gets
its own `EntityRuntime`: it holds the last snapshot that actually reached that
unit, and it addresses the world through `EntityScope`, which refuses reads of
any state the unit was not sent.

Three things follow, and each is measured by a test rather than asserted:

* with a zero-delay, lossless link the runtime returns the same event stream as
  the shared-object loop (the split is behaviour preserving);
* with a delayed or lossy link the same policy sees stale knowledge, and the
  effect of that staleness on on-time delivery is a number, not a caveat;
* a policy that reads a peer's state directly fails loudly instead of passing
  on information no deployment would give it.
"""
import hashlib
from types import SimpleNamespace

from .isolation import IsolationError, EntityScope
from .policies import controllers
from .world import World


class Link:
    """Cost of the channel that carries knowledge between units and referee."""

    def __init__(self, delay_ms=0, jitter_ms=0, loss_rate=0.0, seed=0):
        if delay_ms < 0 or jitter_ms < 0 or not 0.0 <= loss_rate < 1.0:
            raise ValueError('invalid link parameters')
        self.delay_ms = delay_ms
        self.jitter_ms = jitter_ms
        self.loss_rate = loss_rate
        self.seed = seed

    @property
    def ideal(self):
        return self.delay_ms == 0 and self.jitter_ms == 0 and self.loss_rate == 0.0

    def _unit(self, actor, tick, tag):
        digest = hashlib.sha256(f'{self.seed}|{tag}|{actor}|{tick}'.encode()).digest()
        return int.from_bytes(digest[:8], 'big') / 2 ** 64

    def delay_for(self, actor, tick):
        if not self.jitter_ms:
            return self.delay_ms
        return max(0, self.delay_ms + int(round(self.jitter_ms * (2 * self._unit(actor, tick, 'jitter') - 1))))

    def drops(self, actor, tick):
        return bool(self.loss_rate) and self._unit(actor, tick, 'drop') < self.loss_rate


class EntityRuntime:
    """Local knowledge plus a decision function, for exactly one unit."""

    def __init__(self, actor, controller, link=None, step_ms=1000):
        self.actor = actor
        self.controller = controller
        self.link = link
        self.step_ms = step_ms
        self.snapshots = {}          # tick -> LocalView taken just before this unit decided
        self.delivered_tick = None
        self.sent = 0
        self.dropped = 0
        self.age_samples = []
        self.scope = None

    def observe(self, world, tick):
        """Capture what the link would carry for this tick; may be dropped."""
        if self.link is None:
            return
        self.sent += 1
        if self.link.drops(self.actor, tick):
            self.dropped += 1
            return
        arrive = tick + max(1, round(self.link.delay_for(self.actor, tick) / self.step_ms)) \
            if self.link.delay_for(self.actor, tick) else tick
        self.snapshots[arrive] = world.view(self.actor)

    def knowledge(self, world, tick):
        if self.link is None:
            return world.view(self.actor)
        available = [t for t in self.snapshots if t <= tick]
        if not available:
            # Nothing has arrived yet: the unit works from the brief every unit
            # receives before the run starts, not from live truth.
            return world.view(self.actor)
        best = max(available)
        self.delivered_tick = best
        self.age_samples.append(tick - best)
        return self._merge(world, self.snapshots[best])

    def _merge(self, world, stale):
        """Only message-borne knowledge ages; own state is read off the machine.

        A unit knows where it is and what it holds from its own sensors and
        actuators, so those fields are current. Reports, teammate status,
        reservations and the inbox are what the link carries, and those are the
        parts that go stale.
        """
        from dataclasses import replace
        live = world.view(self.actor)
        return replace(stale, now_ms=live.now_ms, node=live.node,
                       inventory=live.inventory, own_tasks=live.own_tasks)

    def tick(self, world, now, tick):
        if self.scope is None:
            self.scope = EntityScope(world, self.actor, strict=self.link is not None,
                                     own_task_ids=world.local_assignments.get(self.actor, ()))
        if self.link is not None and tick == 0:
            self.snapshots[0] = world.view(self.actor)
        self.observe(world, tick)
        if self.link is None:
            self.scope._knowledge = None
        else:
            self.scope._knowledge = self.knowledge(world, tick)
        self.controller.step(self.scope)

    def report(self):
        return dict(actor=self.actor, snapshots=self.sent, dropped=self.dropped,
                    mean_age_ticks=(sum(self.age_samples) / len(self.age_samples)) if self.age_samples else 0.0,
                    max_age_ticks=max(self.age_samples) if self.age_samples else 0)


class Referee:
    """The authority: it owns the world and validates every request."""

    def __init__(self, card, run_id, policy, link=None):
        self.world = World(card, run_id)
        self.card = card
        self.policy = policy
        self.controllers = controllers(card, policy)
        self.link = link
        self.runtimes = {a: EntityRuntime(a, c, link, card['step_ms'])
                         for a, c in self.controllers.items()}

    def run(self):
        world = self.world
        world.initialize_bookings()
        started = {'backend': 'graph', 'policy': self.policy,
                   'witness_external': self.policy == 'witness'}
        if self.link is not None:
            started['knowledge_link'] = dict(delay_ms=self.link.delay_ms, jitter_ms=self.link.jitter_ms,
                                             loss_rate=self.link.loss_rate)
        world.emit('referee', 'run_started', started)
        step = self.card['step_ms']
        for index, now in enumerate(range(0, self.card['end_ms'] + 1, step)):
            world.advance(now)
            for actor in sorted(self.runtimes):
                self.runtimes[actor].tick(world, now, index)
        world.emit('referee', 'run_finished', world.metrics())
        return world

    def runtime_report(self):
        return {a: r.report() for a, r in self.runtimes.items()}


def run_episode(card, policy='P0', run_id=None, link=None):
    """Run one card. `link=None` keeps the historical shared-world topology."""
    referee = Referee(card, run_id or f'{card["id"]}_{policy}', policy, link)
    world = referee.run()
    return SimpleNamespace(events=world.events, metrics=world.metrics(),
                           trajectories=world.trajectories, decisions=world.decisions,
                           diagnostics=world.diagnostics, world=world,
                           runtimes=referee.runtime_report())


__all__ = ['Link', 'EntityRuntime', 'Referee', 'run_episode', 'IsolationError']
