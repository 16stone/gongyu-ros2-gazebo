# -*- coding: utf-8 -*-
"""One operating-system process per entity, inside the *physical* episode.

Why this module exists
---------------------
The graph model already has a process boundary: `distributed/run_episode.py`
runs one unit per process and the report measures what that costs on five link
profiles.  The full Gazebo/Nav2 round did not have it.  `ros/fleet_episode.py`
built one `PhysicalWorld` and handed it to every controller:

    for a in sorted(cs): cs[a].step(world)

so a policy could read a peer's pose, plan, actuator state or cargo without
ever receiving a message about it.  That is a property of sharing an address
space, not of the deployed system, and it is exactly what the arrival-region
mutex, the grant ledger and the release-aware layers are supposed to be blind
to.

What changes and what does not
------------------------------
The referee still owns the world.  In a simulator something has to be the
authority, and the arrival verdict has to be decided by the same code that
decides it today.  What changes is where the *decision maker* lives:

* each entity is a separate process, spawned with the ``spawn`` start method so
  it inherits no rclpy/DDS context from the driver;
* it receives only what a link would have delivered -- its own local view, its
  own actuator state, and the notices addressed to it;
* every action it takes (move, service, send, reserve, release, emit) is a
  request on a pipe, validated by the referee before it changes anything;
* reading anything else raises ``IsolationError`` inside the unit, not a
  quietly wrong number in the results.

The claim this supports is deliberately narrow: *the decisions of this episode
were made without shared memory, and the round still closed 14/14.*  It is not
a claim about real radios, cross-machine deployment or distributed consensus --
the referee is still one process, and that boundary is stated in the report.
"""
from __future__ import annotations

import multiprocessing as mp
import traceback
from types import SimpleNamespace

from gongyu.isolation import EntityScope
from gongyu.policies import controllers
from gongyu.private_card import private_card


class _LocalBusy:
    """Own actuator state; anything else would be a read of somebody's memory."""

    def __init__(self):
        self.value = None

    def get(self, actor, default=None):
        return self.value if self.value is not None else default

    def __contains__(self, actor):
        return self.value is not None

    def __getitem__(self, actor):
        return self.value

    def __iter__(self):
        return iter(())

    def keys(self):
        return []


class RemoteMission:
    """`can_load` and own cargo are questions for the referee, not shared memory."""

    def __init__(self, world):
        self._world = world

    def can_load(self, actor, cargo, now, node, can_transport=True):
        return self._world.call('mission_can_load', (actor, cargo, now, node, can_transport))

    @property
    def inventory(self):
        return self._world.call('mission_inventory', ())

    @property
    def loading(self):
        return self._world.call('mission_loading', ())

    @property
    def claimed(self):
        return self._world.call('mission_claimed', ())


class RemoteWorld:
    """What one entity process may do: read its brief, ask the referee."""

    #: names the unit may only reach through the wire
    FORWARDED = ('emit', 'send', 'start_move', 'service', 'reserve',
                 'cancel_reservation', 'release_booking', 'broadcast_reservation',
                 'retry_station_report', 'complete', 'later', 'exchange_gate',
                 'exchange_slots', 'apply_owner_swap', 'record_bilateral_commit',
                 'bilateral_recorded', 'initialize_bookings', 'slot_owners')

    def __init__(self, conn, brief):
        self._conn = conn
        self._brief = brief
        self.mission = RemoteMission(self)
        self.busy = _LocalBusy()
        self.decisions = []
        self.diagnostics = []
        self.events = []

    def __getattr__(self, name):
        # only reached when normal lookup fails: the brief is what was sent
        brief = object.__getattribute__(self, '_brief')
        if name in brief:
            return brief[name]
        raise AttributeError(
            f'entity process read {name}, which no message carries')

    def call(self, name, args, kwargs=None):
        conn = object.__getattribute__(self, '_conn')
        conn.send(('request', name, args, kwargs or {}))
        tag, value = conn.recv()
        if tag != 'reply':
            raise RuntimeError(f'unexpected referee message {tag!r}')
        if isinstance(value, tuple) and value and value[0] == '__raise__':
            raise RuntimeError(value[1])
        return value

    def _forward(self, name):
        def call(*args, **kwargs):
            return self.call(name, args, kwargs)

        return call

    def __getattribute__(self, name):
        if name in RemoteWorld.FORWARDED:
            return object.__getattribute__(self, '_forward')(name)
        return object.__getattribute__(self, name)


def _entity_main(actor, conn, brief):
    """Child process: build the controller here, never in the driver."""
    try:
        controller = controllers(brief['card'], brief['policy'])[actor]
    except Exception:                                # noqa: BLE001 - the referee must hear it
        conn.send(('failed', actor, traceback.format_exc()))
        return
    world = RemoteWorld(conn, brief)
    scope = EntityScope(world, actor, knowledge=None, strict=True,
                        own_task_ids=brief['own_task_ids'])
    scope.busy = _LocalBusy()
    decisions_seen = diagnostics_seen = 0
    while True:
        try:
            message = conn.recv()
        except EOFError:                             # the driver went away
            break
        if message[0] == 'stop':
            break
        _, now, tick, view, busy, notices, status = message
        world._brief['now'] = now
        # Status the authority broadcasts with every tick: how many releases it has
        # recomputed, and how many slots are claimed at each node.  These are
        # published facts, not reads of another unit's private table -- the first
        # entity-process round failed here, because the red route policy had been
        # reading `world.channel_release_recomputed` straight out of shared memory.
        world._brief.update(status)
        world.events.extend(notices)
        scope._knowledge = view
        scope.busy.value = busy
        try:
            controller.step(scope)
        except Exception:                            # noqa: BLE001 - the referee must hear it
            conn.send(('failed', actor, traceback.format_exc()))
            break
        # Deltas, not the whole ledger: the referee extends its own lists, and
        # re-sending the full history every tick would cost O(n^2) pickles.
        conn.send(('done', tick, world.decisions[decisions_seen:],
                   world.diagnostics[diagnostics_seen:]))
        decisions_seen, diagnostics_seen = len(world.decisions), len(world.diagnostics)
    conn.close()


class EntityTopology:
    """Parent side: spawn the units, feed them views, answer their requests."""

    def __init__(self, card, policy, world, mechanisms=None):
        self.card = card
        self.policy = policy
        self.world = world
        self.mechanisms = mechanisms
        self.connections = {}
        self.processes = {}
        self.requests = 0
        self.entity_count = 0
        self._cursor = {}
        # The referee measures the channel itself and broadcasts the result: a
        # unit's own ledger only carries notices addressed to it, so a scope that
        # scanned `events` would silently answer a different number.
        self._event_cursor = 0
        self._entered = {}
        self._last_traversal_ms = None

    # -- setup ---------------------------------------------------------------
    def _brief(self, actor):
        """Public map configuration plus this unit's own task sheet only."""
        own = sorted(self.world.local_assignments.get(actor, ()))
        network = self.world.network
        return dict(card=private_card(self.card, actor, own), own_task_ids=own,
                    policy=self.policy, now=0, run_id=self.world.run_id,
                    station=self.world.station, edges=self.world.edges,
                    geometry=self.card.get('geometry'), step_ms=self.card['step_ms'],
                    channel_impairment=self.world.channel_impairment,
                    network=SimpleNamespace(delay=getattr(network, 'delay', 0),
                                            jitter=getattr(network, 'jitter', 0),
                                            loss_rate=getattr(network, 'loss_rate', 0.0)),
                    channel_release_recomputed=getattr(self.world, 'channel_release_recomputed', 0),
                    berth_occupancy=getattr(self.world, 'berth_occupancy', {}) or {},
                    channel_last_traversal_ms=None,
                    mechanisms=self.mechanisms)

    def spawn(self):
        context = mp.get_context('spawn')
        for actor in sorted(controllers(self.card, self.policy)):
            parent, child = context.Pipe()
            process = context.Process(target=_entity_main,
                                      args=(actor, child, self._brief(actor)),
                                      name=f'entity-{actor}')
            process.start()
            self.connections[actor] = parent
            self.processes[actor] = process
            self._cursor[actor] = 0
        self.entity_count = len(self.connections)
        return self

    # -- one policy tick -----------------------------------------------------
    def dispatch(self, actor, name, args, kwargs):
        """Referee side of one request: validate against the world, reply."""
        try:
            mission = self.world.mission
            if name == 'mission_can_load':
                return mission.can_load(*args, **kwargs)
            if name == 'slot_owners':
                return self.world.slot_owners()
            if name == 'mission_inventory':
                return {actor: mission.inventory[actor]} if actor in mission.inventory else {}
            if name == 'mission_loading':
                return {actor: mission.loading[actor]} if actor in mission.loading else {}
            if name == 'mission_claimed':
                return {cargo: who for cargo, who in mission.claimed.items() if who == actor}
            bound = EntityScope(self.world, actor, strict=False)
            return getattr(bound, name)(*args, **kwargs)
        except Exception as exc:                     # noqa: BLE001 - reported to the unit
            return ('__raise__', f'{type(exc).__name__}: {exc}')

    def measure_channel(self):
        """Most recent completed traversal, measured on the authoritative ledger."""
        world = self.world
        for event in world.events[self._event_cursor:]:
            kind = getattr(event, 'kind', None)
            at = getattr(event, 't_ms', None)
            if at is None:
                continue
            if kind == 'channel_enter':
                self._entered[event.actor] = at
            elif kind == 'channel_cleared':
                start = self._entered.pop(event.actor, None)
                if start is not None and at > start:
                    self._last_traversal_ms = at - start
        self._event_cursor = len(world.events)
        return self._last_traversal_ms

    def tick(self, now, index=0):
        world = self.world
        traversal_ms = self.measure_channel()
        for actor in sorted(self.connections):
            conn = self.connections[actor]
            view = world.view(actor)
            notices = [e for e in world.events[self._cursor[actor]:]
                       if getattr(e, 'actor', None) == actor]
            self._cursor[actor] = len(world.events)
            status = dict(channel_release_recomputed=getattr(world, 'channel_release_recomputed', 0),
                          berth_occupancy=getattr(world, 'berth_occupancy', {}) or {},
                          channel_last_traversal_ms=traversal_ms)
            conn.send(('tick', now, index, view, world.busy.get(actor), notices, status))
            while True:
                message = conn.recv()
                tag = message[0]
                if tag == 'done':
                    _, _tick, decisions, diagnostics = message
                    world.decisions.extend(decisions)
                    world.diagnostics.extend(diagnostics)
                    break
                if tag == 'failed':
                    raise RuntimeError(f'entity {message[1]} failed:\n{message[2]}')
                if tag == 'request':
                    _, name, args, kwargs = message
                    self.requests += 1
                    conn.send(('reply', self.dispatch(actor, name, args, kwargs)))
                    continue
                raise RuntimeError(f'unexpected message {tag!r}')

    # -- teardown ------------------------------------------------------------
    def close(self, timeout=10.0):
        for conn in self.connections.values():
            try:
                conn.send(('stop',))
            except Exception:                        # noqa: BLE001 - the unit may be gone
                pass
        for process in self.processes.values():
            process.join(timeout=timeout)
            if process.is_alive():
                process.terminate()
        self.connections.clear()
        self.processes.clear()

    # -- reporting -----------------------------------------------------------
    def receipt(self):
        """What the round can say about its own topology, as recorded numbers."""
        return dict(topology='one process per entity', entities=self.entity_count,
                    wire='multiprocessing.Pipe (spawn)', cross_process_requests=self.requests)


__all__ = ['EntityTopology', 'RemoteWorld', 'RemoteMission']
