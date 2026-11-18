"""Run one card with one operating-system process per entity.

The in-process runtime (`gongyu/runtime.py`) already refuses cross-entity reads,
but it still shares an address space. This module removes that last convenience:
each unit is a separate process, it receives only the local view the link would
have delivered, and every request it makes -- move, service, send, reserve --
travels to the referee as a message and comes back as a reply.

The referee process still owns the world, because in a simulator something has
to be the authority. What it does *not* do is let a unit read that world.
"""
import argparse
import json
import multiprocessing as mp
import pickle
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gongyu.isolation import EntityScope, IsolationError   # noqa: E402
from gongyu.private_card import private_card               # noqa: E402
from gongyu.policies import controllers                    # noqa: E402
from gongyu.runtime import Link                            # noqa: E402
from gongyu.world import World, load_card                  # noqa: E402


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

    def __init__(self, conn, brief):
        self._conn = conn
        self._brief = brief
        self.mission = RemoteMission(self)
        self.busy = None            # replaced below by the scope's own mirror
        self.decisions = []
        self.diagnostics = []
        self.events = []            # notifications the referee pushed for this unit

    # -- published parameters --------------------------------------------------
    def __getattr__(self, name):
        if name in self._brief:
            return self._brief[name]
        raise IsolationError(f'entity process read {name}, which was never sent')

    # -- requests --------------------------------------------------------------
    def call(self, name, args, kwargs=None):
        self._conn.send(('request', name, args, kwargs or {}))
        tag, value = self._conn.recv()
        if tag != 'reply':
            raise RuntimeError(f'unexpected referee message {tag!r}')
        if isinstance(value, tuple) and value and value[0] == '__raise__':
            raise IsolationError(value[1])
        return value

    def __getattr_request(self, name):
        def call(*args, **kwargs):
            return self.call(name, args, kwargs)

        return call

    def __getattribute__(self, name):
        if name in ('emit', 'send', 'start_move', 'service', 'reserve', 'cancel_reservation',
                    'release_booking', 'broadcast_reservation', 'retry_station_report',
                    'complete', 'later', 'exchange_gate', 'exchange_slots', 'apply_owner_swap',
                    'record_bilateral_commit', 'bilateral_recorded', 'initialize_bookings',
                    'slot_owners'):
            return object.__getattribute__(self, '_RemoteWorld__getattr_request')(name)
        return object.__getattribute__(self, name)


class _LocalBusy:
    """Own actuator state; the scope would otherwise ask for a mirror."""

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


def _attach_mechanisms(brief):
    """Install the switchable layers inside the unit's own process.

    The learner and the threshold ledger are module-level state, so a mechanism
    that a card switches on has to be attached where the decisions are made --
    in the entity process, not in the referee. The brief therefore carries the
    switch, and the unit attaches it to itself before its first tick.
    """
    from gongyu import learning, thresholds
    spec = brief.get('mechanisms') or {}
    if spec.get('learner'):
        learning.attach(learning.Bandit(**spec['learner']))
    if spec.get('thresholds'):
        thresholds.attach(thresholds.Thresholds(spec['thresholds']['initial'],
                                                reinforced=spec['thresholds'].get('reinforced', True)))


def entity_main(actor, conn, brief):
    _attach_mechanisms(brief)
    controller = controllers(brief['card'], brief['policy'])[actor]
    world = RemoteWorld(conn, brief)
    scope = EntityScope(world, actor, knowledge=None, strict=True,
                        own_task_ids=brief['own_task_ids'])
    scope.busy = _LocalBusy()
    while True:
        message = conn.recv()
        if message[0] == 'stop':
            break
        _, now, tick, view, busy, notices = message
        world._brief['now'] = now
        world.events.extend(notices)
        scope._knowledge = view
        scope.busy.value = busy
        try:
            controller.step(scope)
        except Exception:                            # noqa: BLE001 - the referee must hear it
            conn.send(('failed', actor, traceback.format_exc()))
            break
        conn.send(('done', tick, world.decisions, world.diagnostics))
    conn.close()


class Referee:
    def __init__(self, card, policy, run_id, link, workers, mechanisms=None):
        self.card = card
        self.policy = policy
        self.world = World(card, run_id)
        self.link = link
        self.workers = workers
        self.mechanisms = mechanisms
        self.connections = {}
        self.processes = {}

    def _brief(self, actor):
        """Static map configuration plus only this unit's private task sheet.

        The referee owns the full card; a spawned unit receives a redacted copy,
        so a competitor's delivery deadline can never be obtained by reading
        the brief instead of receiving a message.
        """
        from types import SimpleNamespace
        own = sorted(self.world.local_assignments.get(actor, ()))
        return dict(card=private_card(self.card, actor, own),
                    own_task_ids=own, policy=self.policy, now=0, run_id=self.world.run_id,
                    station=self.world.station, edges=self.world.edges,
                    geometry=self.card.get('geometry'), step_ms=self.card['step_ms'],
                    channel_impairment=self.world.channel_impairment,
                    network=SimpleNamespace(delay=self.link.delay_ms or self.card['message_delay_ms'],
                                            jitter=self.link.jitter_ms, loss_rate=self.link.loss_rate),
                    mechanisms=self.mechanisms)

    def dispatch(self, actor, name, args, kwargs):
        """Referee side of one request: validate, apply, reply."""
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
            result = getattr(bound, name)(*args, **kwargs)
            return result
        except Exception as exc:                     # noqa: BLE001 - reported to the unit
            return ('__raise__', f'{type(exc).__name__}: {exc}')

    def spawn(self):
        context = mp.get_context('spawn')
        for actor in sorted(controllers(self.card, self.policy)):
            parent, child = context.Pipe()
            process = context.Process(target=entity_main, args=(actor, child, self._brief(actor)))
            process.start()
            self.connections[actor] = parent
            self.processes[actor] = process

    def run(self):
        try:
            return self._run()
        finally:
            for conn in self.connections.values():
                try:
                    conn.send(('stop',))
                except Exception:                     # noqa: BLE001 - the unit may be gone
                    pass
            for process in self.processes.values():
                process.join(timeout=5)
                if process.is_alive():
                    process.terminate()

    def _run(self):
        world = self.world
        controllers_now = controllers(self.card, self.policy)
        world.initialize_bookings()
        world.emit('referee', 'run_started', {'backend': 'graph', 'policy': self.policy,
                                             'topology': 'one process per entity',
                                             'knowledge_link': dict(delay_ms=self.link.delay_ms,
                                                                    jitter_ms=self.link.jitter_ms,
                                                                    loss_rate=self.link.loss_rate)})
        step = self.card['step_ms']
        history = {a: {} for a in self.connections}
        dropped = {a: 0 for a in self.connections}
        cursor = {a: 0 for a in self.connections}
        for index, now in enumerate(range(0, self.card['end_ms'] + 1, step)):
            world.advance(now)
            for actor in sorted(self.connections):
                view = world.view(actor)
                if self.link.drops(actor, index):
                    dropped[actor] += 1
                else:
                    history[actor][index] = view
                due = index - max(0, round(self.link.delay_for(actor, index) / step))
                available = [t for t in history[actor] if t <= due]
                knowledge = history[actor][max(available)] if available else view
                busy = world.busy.get(actor)
                notices = [e for e in world.events[cursor[actor]:] if e.actor == actor]
                cursor[actor] = len(world.events)
                self.connections[actor].send(('tick', now, index, knowledge, busy, notices))
                while True:
                    message = self.connections[actor].recv()
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
                        reply = self.dispatch(actor, name, args, kwargs)
                        self.connections[actor].send(('reply', reply))
                        continue
                    raise RuntimeError(f'unexpected message {tag!r}')
        for conn in self.connections.values():
            conn.send(('stop',))
        for process in self.processes.values():
            process.join(timeout=10)
        world.emit('referee', 'run_finished', world.metrics())
        return world, dropped


def run(card_path, policy='P3', out_dir=None, delay_ms=0, jitter_ms=0, loss_rate=0.0, seed=0):
    card = load_card(card_path)
    run_id = card['id'] + '_dist'
    link = Link(delay_ms, jitter_ms, loss_rate, seed)
    referee = Referee(card, policy, run_id, link, len(card['fleet']))
    referee.spawn()
    world, dropped = referee.run()
    summary = dict(card=card['id'], policy=policy, topology='one process per entity',
                   entities=len(referee.connections),
                   link=dict(delay_ms=delay_ms, jitter_ms=jitter_ms, loss_rate=loss_rate),
                   dropped_views=dropped, violations=len(world.violations),
                   tasks={k: dict(completed_ms=v['completed_ms'], on_time=v['on_time'])
                          for k, v in world.metrics()['tasks'].items()})
    if out_dir:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n',
                                                    encoding='utf-8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', required=True)
    parser.add_argument('--policy', default='P3')
    parser.add_argument('--out')
    parser.add_argument('--delay-ms', type=int, default=0)
    parser.add_argument('--jitter-ms', type=int, default=0)
    parser.add_argument('--loss', type=float, default=0.0)
    parser.add_argument('--seed', type=int, default=0)
    args = parser.parse_args()
    try:
        result = run(args.case, args.policy, args.out, args.delay_ms, args.jitter_ms, args.loss, args.seed)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
    print(json.dumps(result, indent=2, ensure_ascii=False))
