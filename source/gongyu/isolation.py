"""Entity-scoped access to the mission world.

The delivered design ran every controller against the one authoritative World
object, so a policy could look up any peer's position, actuator state or cargo
without ever receiving a message about it. That is a convenience of sharing an
address space, not a property a deployed system has.

This module makes the boundary explicit. `EntityScope` is everything one entity
may touch:

* its own pose, node, cargo and task list;
* the reports and status messages that actually arrived on its link;
* the reservation table as this entity last heard it;
* requests to the authority (move, service, send), each of which the referee
  validates before it changes anything.

Everything else raises `IsolationError`. The error is the measurement: a policy
that only passes because it could read the truth will fail here instead of
quietly producing a number that no deployment could reproduce.
"""
from .model import LocalView
from .private_card import private_card


class IsolationError(RuntimeError):
    """An entity reached for state it could only have by sharing memory."""


class MissionMirror:
    """The mission book as one entity can see it: own cargo only."""

    def __init__(self, scope):
        self._scope = scope
        self._mission = scope._world.mission

    @property
    def inventory(self):
        actor = self._scope.actor
        return {actor: self._mission.inventory[actor]} if actor in self._mission.inventory else {}

    @property
    def loading(self):
        actor = self._scope.actor
        return {actor: self._mission.loading[actor]} if actor in self._mission.loading else {}

    @property
    def claimed(self):
        actor = self._scope.actor
        return {cargo: who for cargo, who in self._mission.claimed.items() if who == actor}

    @property
    def delivered(self):
        # Another unit's delivery is news, not state: it arrives as a message.
        return []

    def can_load(self, actor, cargo, now, node, can_transport=True):
        if actor != self._scope.actor:
            raise IsolationError(f'{self._scope.actor} asked whether {actor} may load')
        return self._mission.can_load(actor, cargo, now, node, can_transport)


class BusyMirror:
    """Own actuator state. A peer's is only known from its status messages."""

    def __init__(self, scope):
        self._scope = scope

    def get(self, actor, default=None):
        if actor != self._scope.actor:
            raise IsolationError(f'{self._scope.actor} read busy state of {actor}')
        return self._scope._world.busy.get(actor, default)

    def __contains__(self, actor):
        return self.get(actor) is not None

    def __getitem__(self, actor):
        value = self.get(actor)
        if value is None:
            raise KeyError(actor)
        return value

    def __iter__(self):
        if self._scope.actor in self._scope._world.busy:
            yield self._scope.actor

    def __len__(self):
        return 1 if self._scope.actor in self._scope._world.busy else 0

    def keys(self):
        return list(iter(self))

    def items(self):
        return [(a, self._scope._world.busy[a]) for a in self]


class LinkFacts:
    """Link parameters are configuration, not observations, so they may be read."""

    def __init__(self, network):
        self._network = network

    @property
    def delay(self):
        return self._network.delay

    @property
    def jitter(self):
        return getattr(self._network, 'jitter', 0)

    @property
    def loss_rate(self):
        return getattr(self._network, 'loss_rate', 0.0)


class EntityScope:
    """What one entity is allowed to see and ask for."""

    #: attributes that describe the world's published parameters, not live state.
    #: `card` is deliberately absent: it is served by the `card` property below,
    #: which strips the other team's private deadlines before the unit sees it.
    READABLE = ('now', 'run_id', 'station', 'edges', 'channel_impairment',
                'geometry', 'step_ms', 'm2', 'violations',
                # Published status, not shared memory: the referee broadcasts how
                # many releases it recomputed and how many slots are claimed at
                # each node, and every unit may read that broadcast.
                'channel_release_recomputed', 'berth_occupancy',
                'channel_last_traversal_ms')
    #: calls the authority validates on the entity's behalf, and the position of
    #: the actor argument so the scope can refuse to drive somebody else
    FORWARDED = {'emit': 0, 'send': 0, 'start_move': 0, 'service': 0, 'reserve': 0,
                 'cancel_reservation': 0, 'release_booking': 0, 'broadcast_reservation': 0,
                 'retry_station_report': 0, 'complete': 0, 'later': 1,
                 'exchange_gate': None, 'exchange_slots': None, 'apply_owner_swap': None,
                 'slot_owners': None,
                 'record_bilateral_commit': None, 'bilateral_recorded': None,
                 'initialize_bookings': None}

    def __init__(self, world, actor, knowledge=None, strict=True, own_task_ids=None):
        object.__setattr__(self, '_world', world)
        object.__setattr__(self, 'actor', actor)
        object.__setattr__(self, 'strict', strict)
        object.__setattr__(self, 'mission', MissionMirror(self) if strict else world.mission)
        object.__setattr__(self, 'busy', BusyMirror(self) if strict else world.busy)
        object.__setattr__(self, 'network', LinkFacts(world.network) if strict else world.network)
        object.__setattr__(self, '_knowledge', knowledge)
        object.__setattr__(self, 'decisions', world.decisions)
        object.__setattr__(self, 'diagnostics', world.diagnostics)
        if strict:
            if own_task_ids is None:
                try:
                    own_task_ids = world.local_assignments.get(actor, ())
                except (AttributeError, IsolationError):
                    own_task_ids = ()
            brief = private_card(world.card, actor, own_task_ids)
        else:
            brief = world.card
        object.__setattr__(self, '_private_card', brief)

    # -- the unit's own copy of the scene brief --------------------------------
    @property
    def card(self):
        """Public map configuration plus this unit's own task deadlines.

        In the historical shared-world topology (`strict=False`) the original
        card is returned, so the registered-card event streams stay identical.
        In every isolated topology the other team's deadlines are absent.
        """
        return object.__getattribute__(self, '_private_card')

    # -- the entity's own event ledger ----------------------------------------
    @property
    def events(self):
        """Events addressed to this unit, not the fleet log.

        In a deployment these are the notifications that arrive on its link; the
        authority filters them and the runtime hands them over, so a unit never
        reads what happened to somebody else.
        """
        trail = self._world.events
        return trail if not object.__getattribute__(self, 'strict') \
            else [e for e in trail if getattr(e, 'actor', None) == self.actor]

    # -- reads -----------------------------------------------------------------
    def __getattr__(self, name):
        if name in self.READABLE:
            return getattr(self._world, name)
        if not object.__getattribute__(self, 'strict'):
            return getattr(self._world, name)
        raise IsolationError(f'{self.actor} read world.{name}, which no message carries')

    def view(self, actor):
        if not object.__getattribute__(self, 'strict'):
            return self._world.view(actor)
        if actor != self.actor:
            raise IsolationError(f'{self.actor} asked for the local view of {actor}')
        if self._knowledge is not None:
            return self._knowledge
        return self._world.view(actor)

    # -- requests to the authority --------------------------------------------
    def __getattr_forwarded(self, name):
        target = getattr(self._world, name)
        position = EntityScope.FORWARDED[name]

        def call(*args, **kwargs):
            if position is not None and len(args) > position:
                if isinstance(args[position], str) and args[position] != self.actor:
                    raise IsolationError(f'{self.actor} tried to drive {args[position]} through {name}')
            return target(*args, **kwargs)

        return call

    def __getattribute__(self, name):
        if name in EntityScope.FORWARDED:
            return object.__getattribute__(self, '_EntityScope__getattr_forwarded')(name)
        return object.__getattribute__(self, name)


def publish(world, actor):
    """Snapshot the local view the way the link would deliver it."""
    return world.view(actor)


__all__ = ['IsolationError', 'MissionMirror', 'BusyMirror', 'LinkFacts', 'EntityScope', 'publish']
