"""Observe two motor-driven robots and compare two corridor release rules."""

import json
import os
import sys
from pathlib import Path

from controller import Supervisor

sys.path.insert(0, os.environ['GONGYU_WEBOTS_COMMON'])
from bus import Bus
from physical_corridor import occupies_corridor

run = Path(os.environ['GONGYU_RUN_DIR'])
bus = Bus(str(run / 'bus'))
early_release = os.environ['GONGYU_COURSE_EARLY_RELEASE'] == '1'
supervisor = Supervisor()
step_ms = int(supervisor.getBasicTimeStep())
robots = {name: supervisor.getFromDef(name) for name in ('B1', 'B2')}
destination = {'B1': 7.6, 'B2': 6.4}
nominal_clear_ms = 32000
events = []
inside = set()
settled = {}
sent = set()
cleared = set()
overlap_samples = 0

def record(now, actor, kind):
    row = {'t_ms': now, 'actor': actor, 'kind': kind}
    events.append(row)
    bus.append('events.jsonl', row)

def send(now, actor):
    bus.append(f'cmd_{actor}.jsonl', {'id': 'travel-' + actor, 'type': 'goto',
               'x': destination[actor], 'y': 0, 't_ms': now, 'node': 'exit',
               'task_id': actor})
    sent.add(actor)
    record(now, actor, 'dispatch')

send(0, 'B1')
while supervisor.step(step_ms) != -1:
    now = round(1000 * supervisor.getTime())
    for name, robot in robots.items():
        x, y, z = robot.getPosition()
        occupied = occupies_corridor(x, y)
        if occupied and name not in inside:
            inside.add(name)
            record(now, name, 'enter')
        if not occupied and name in inside:
            inside.remove(name)
            cleared.add(name)
            record(now, name, 'clear')
        velocity = robot.getVelocity()
        if (name in sent and abs(x - destination[name]) <= 0.10 and abs(y) <= 0.10
                and velocity[0] ** 2 + velocity[1] ** 2 < 0.10 ** 2):
            settled.setdefault(name, now)
        if now % (16 * step_ms) == 0:
            bus.append('poses.jsonl', {'t_ms': now, 'actor': name, 'position': [x,y,z]})
    overlap_samples += len(inside) > 1
    release_due = early_release or now >= nominal_clear_ms
    if 'B2' not in sent and 'B1' in cleared and not inside and release_due:
        send(now, 'B2')
    if now >= 60000:
        break

summary = {
    'early_release': early_release, 'nominal_clear_ms': nominal_clear_ms,
    'events': events, 'arrived_at_ms': settled, 'total': 2, 'on_time': len(settled),
    'full_window': now >= 60000, 'violation_count': overlap_samples,
}
(run / 'result' / 'metrics.json').write_text(json.dumps(summary, indent=2))
(run / 'shutdown.json').write_text(json.dumps({'status':'COMPLETE','sim_end_ms':now}))
supervisor.simulationQuit(0)
