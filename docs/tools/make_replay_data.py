#!/usr/bin/env python3
"""Rebuild the demo replay payload from the referee's independent truth.

The first version took `odom` from each controller's telemetry.  That is fine for the
ground chassis but the aerial controllers in this backend do not propagate odometry, so
B3 and R5 were drawn at the origin.  The referee's `truth_trajectories` is both complete
and authoritative, so the demo now plots exactly what the referee scored.
"""
import json, math, os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNS = os.environ.get('GONGYU_RUNS_ROOT', os.path.join(os.path.expanduser('~'),
                                                       'pandaoxi', 'gongyu-webots-runs'))
RUN = os.path.join(RUNS, 'f-webots-full-01')
EV = os.path.join(REPO, 'evidence', 'webots', 'f-webots-full-01')
OUT = os.path.join(REPO, 'docs', 'demo', 'webots_replay_data.json')

m = json.load(open(EV + '/metrics.json', encoding='utf-8'))
scen = json.load(open(os.path.join(REPO, 'webots', 'config', 'scenario_medium.json'),
                      encoding='utf-8'))

# per-actor controller heading, used only to orient the heading tick
head = {}
for nm in m['truth_trajectories']:
    p = os.path.join(RUN, 'bus', 'tel_%s.jsonl' % nm)
    rows = []
    if os.path.exists(p):
        for line in open(p, encoding='utf-8'):
            r = json.loads(line)
            o = r.get('odom') or [0, 0, 0]
            rows.append((int(r['t_ms']), o[2]))
    head[nm] = rows

def heading_at(nm, t, fallback):
    rows = head.get(nm) or []
    if not rows:
        return fallback
    best = None
    for tt, th in rows:
        if tt <= t:
            best = th
        else:
            break
    return best if best is not None else rows[0][1]

trajs = {}
for nm, samples in m['truth_trajectories'].items():
    out, prev = [], None
    for s in samples:
        x, y = s['pos'][0], s['pos'][1]
        if prev and math.hypot(x - prev[0], y - prev[1]) > 0.03:
            th = math.atan2(y - prev[1], x - prev[0])
        else:
            th = heading_at(nm, s['t_ms'], 0.0)
        out.append([s['t_ms'], round(x, 3), round(y, 3), round(th, 3)])
        prev = (x, y)
    # forward-fill headings over stationary stretches so the tick does not snap to 0
    for i in range(1, len(out)):
        if abs(out[i][1] - out[i - 1][1]) < 1e-6 and abs(out[i][2] - out[i - 1][2]) < 1e-6:
            out[i][3] = out[i - 1][3]
    trajs[nm] = out

events = []
for line in open(RUN + '/bus/events.jsonl', encoding='utf-8'):
    e = json.loads(line)
    events.append({'t': e['t_ms'], 'actor': e.get('actor'), 'kind': e['kind'],
                   'task': e.get('task_id'), 'payload': e.get('payload')})
events.sort(key=lambda e: e['t'])

nodes = {}
for k, v in (scen.get('nodes') or {}).items():
    nodes[k] = [v[0], v[1]] if len(v) >= 2 else list(v[0])

payload = {
    'run': 'f-webots-full-01',
    'scene': 'web_medium',
    'source': "amax Webots R2025a CPU / f-webots-full-01 / referee truth_trajectories",
    'sample_period_ms': 500,
    'trajectories': trajs,
    'events': events,
    'metrics': {'on_time': m['on_time'], 'total': m['total'],
                'violation_count': m['violation_count'],
                'channel_enters': m['channel_enters'],
                'channel_releases': m['channel_releases'],
                'accepted_reports': len(m['accepted_reports']),
                'expired_reports': len(m['expired_reports']),
                'wall_seconds': m['wall_seconds']},
    'nodes': nodes,
}
json.dump(payload, open(OUT, 'w', encoding='utf-8'), separators=(',', ':'))
print('actors', len(trajs), 'events', len(events), 'nodes', len(nodes))
for nm in sorted(trajs):
    r = trajs[nm]
    print('  %-3s n=%-3d %s -> %s' % (nm, len(r), r[0][1:3] if r else None,
                                      r[-1][1:3] if r else None))
print('bytes', os.path.getsize(OUT))
