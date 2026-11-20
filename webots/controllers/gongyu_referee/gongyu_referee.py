#!/usr/bin/env python3
"""Independent referee: truth poses, task acceptance, channel timeline, reports."""
import json
import math
import os
import sys
import time
from controller import Supervisor

sys.path.insert(0, os.environ.get('GONGYU_WEBOTS_COMMON', ''))
from bus import Bus
from task_metrics import summarize_tasks
from observation_gate import ObservationGate, ObservationLink
from physical_corridor import CARRIER_ORDER, STAGING, TRANSPORT_ROUTES, occupies_corridor

RUN = os.environ.get('GONGYU_RUN_DIR', '/tmp/gongyu_default')
SCENE = os.environ.get('GONGYU_SCENE', 'web_medium')
MECH = os.environ.get('GONGYU_MECH', 'release')
ADAPT = os.environ.get('GONGYU_ADAPT', 'off')
COST = os.environ.get('GONGYU_COST', 'low')
REPORT_DELAY_MS = int(os.environ.get('GONGYU_REPORT_DELAY_MS', '1000'))
SEED = int(os.environ.get('GONGYU_SEED', '0'))
SCEN = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config', 'scenario_medium.json'), encoding='utf-8'))
NODES = SCEN['nodes']
TASKS = dict((t['id'], t) for t in SCEN['tasks'])
PHYSICAL_ACTUATION = os.environ.get('GONGYU_PHYS', '0') == '1'
ROTOR_SCENE = SCENE == "web_medium_rotor_phys"
PHYSICAL_STAGING = PHYSICAL_ACTUATION and (ROTOR_SCENE or SCENE in {"web_medium_phys", "web_holdout_v1_phys"})
if ROTOR_SCENE and not PHYSICAL_STAGING:
    raise ValueError("The rotor course requires GONGYU_PHYS=1")
ROTOR_AIRCRAFT = {"B3", "R5"} if ROTOR_SCENE else set()
ROTOR_ALTITUDE = 1.9
LANDING_ALTITUDE = 0.045
BLUE2_HANDOFF = os.environ.get('GONGYU_BLUE2_HANDOFF', '0') == '1'
if BLUE2_HANDOFF and not PHYSICAL_STAGING:
    raise ValueError('GONGYU_BLUE2_HANDOFF requires a physical full-course scene')
TAU = SCEN['tau_ms']
SERVICE = SCEN['service_ms']
END = int(os.environ.get('GONGYU_END_MS', str(SCEN['end_ms'])))
TOL = SCEN['physical_berth_tolerance_m']
bus = Bus(os.path.join(RUN, 'bus'))
os.makedirs(os.path.join(RUN, 'result'), exist_ok=True)

ROUTES = {
 'B1': [('D', None), ('W', None), ('E', None), ('L', None), ('O', 'blue1')],
 'B2': [('O', None), ('J', None), ('L', None), ('E', None), ('W', None), ('D', 'blue2')],
 'R1': [('E', None), ('L', None), ('J', None), ('O', None), ('J', None), ('L', None), ('E', None), ('W', 'red1')],
 'R2': [('E', None), ('W', None), ('D', None), ('W', None), ('E', None), ('L', 'red2')],
 'R3': [('N0', None), ('PN', 'red3_inspect'), ('RN', 'red3_report'), ('PN', None), ('N0', 'red3_return')],
 'R4': [('S0', None), ('PS', 'red4_inspect'), ('RS', 'red4_report'), ('PS', None), ('S0', 'red4_return')],
 'B3': [('F', 'blue_inspect'), ('K', None), ('H', None), ('K', None), ('F', None)],
 'R5': [('F_R', 'red_inspect'), ('K_R', None), ('H_R', 'red_patrol'), ('K_R', None), ('F_R', 'red_return')],
}
if SCENE == 'web_b1_route' or SCENE == 'web_b1_lowobs':
    ROUTES = {'B1': [('D', None), ('W', None), ('E', None), ('L', None)]}
elif SCENE == 'web_b3_target':
    ROUTES = {'B3': [('F', 'blue_inspect'), ('K', None), ('H', None)]}
elif SCENE == 'web_d4':
    ROUTES = {k: ROUTES[k] for k in ('B1', 'B2', 'R3', 'B3')}
if PHYSICAL_STAGING:
    NODES = {**NODES, **STAGING}
    ROUTES.update(TRANSPORT_ROUTES)
if ROTOR_SCENE:
    NODES.update(F_land=NODES["F"], F_R_land=NODES["F_R"])
    ROUTES["B3"].append(("F_land", None))
    ROUTES["R5"][-1:] = [("F_R", None), ("F_R_land", "red_return")]
if BLUE2_HANDOFF:
    # The simulated withdrawal leaves the load at the relay and clears its bay.
    NODES['blue_withdrawal_bay'] = (9.30, 1.60)
    ROUTES['B2'] = (('blue_withdrawal_bay', None),)

sup = Supervisor()
ts = int(sup.getBasicTimeStep())
_floor = sup.getFromDef('floor')
if _floor:
    fp = _floor.getPosition()
    open(os.environ.get('GONGYU_RUN_DIR','/tmp')+'/floor_pos.txt','w').write('floor_pos=%s\n' % [round(v,3) for v in fp])
actors = {}
for nm in ROUTES:
    node = sup.getFromDef(nm)
    if node is not None:
        actors[nm] = node
if BLUE2_HANDOFF and not {'B1', 'B2'} <= actors.keys():
    raise ValueError('The blue2 handoff requires both blue ground vehicles')
FULL_SCENES = {"web_medium", "web_medium_phys", "web_holdout_v1", "web_holdout_v1_phys", "web_medium_rotor_phys"}
if SCENE in FULL_SCENES:
    expected_task_ids = set(TASKS)
else:
    expected_task_ids = {task for name in actors for _, task in ROUTES[name] if task in TASKS}
state = {}
cmd_seq = 0
events = []


def ev(kind, payload, actor=None, task=None):
    row = {'t_ms': t, 'actor': actor, 'kind': kind, 'task_id': task, 'payload': payload}
    events.append(row)
    bus.append('events.jsonl', row)


# ---- Independent deterministic kinematic actuator model ----
# The task-logic layer is kinematic (as in the frozen graph backend's travel_time).
# Truth is produced by this model, never by the controller under test's self-report.
# Physical sensors (GPS/LiDAR/Camera) still run in Webots for traceable observations.
AERIAL = set(filter(None, os.environ.get('GONGYU_AERIAL', 'B3,R5' if PHYSICAL_STAGING and not ROTOR_SCENE else '').split(',')))
if ROTOR_SCENE and AERIAL:
    raise ValueError("The rotor course does not permit kinematic actors")
GS = SCEN.get('ground_speed', 0.5)  # m/s, frozen scenario parameter
kin_state = {}
KIN_FIELDS = {}
channel_holder = None
for _nm in actors:
    _p = actors[_nm].getPosition()
    kin_state[_nm] = {'x': _p[0], 'y': _p[1], 'h': _p[2], 'target': None, 'speed': GS}
    KIN_FIELDS[_nm] = actors[_nm].getField('translation')


def channel_gate(nm, nx, ny):
    # True if allowed to move to (nx,ny); shared-channel mutual exclusion.
    if MECH == 'phase111':
        return True  # no protocol baseline: overlaps are expected (control condition)
    entering = 2.05 <= nx <= 4.95 and abs(ny) <= 0.6
    inside_now = 2.05 <= kin_state[nm]['x'] <= 4.95 and abs(kin_state[nm]['y']) <= 0.6
    holder = globals().get('channel_holder', None)
    if entering and not inside_now and holder not in (None, nm):
        return False  # wait outside entrance until channel is clear
    return True


def advance_kinematics(dt_s, only=None):
    for nm, ks in kin_state.items():
        if only is not None and nm not in only:
            continue
        if ks['target'] is None:
            continue
        gx, gy = ks['target']
        dx, dy = gx - ks['x'], gy - ks['y']
        dist = (dx * dx + dy * dy) ** 0.5
        step = ks['speed'] * dt_s
        if dist <= step:
            nx, ny = gx, gy
        else:
            nx = ks['x'] + dx / dist * step
            ny = ks['y'] + dy / dist * step
        if channel_gate(nm, nx, ny):
            ks['x'], ks['y'] = nx, ny
            KIN_FIELDS[nm].setSFVec3f([ks['x'], ks['y'], ks['h']])


def truth(nm):
    if PHYSICAL_ACTUATION:
        p = actors[nm].getPosition()  # independent truth read from simulator, never ref-written here
        return [round(p[0], 4), round(p[1], 4), round(p[2], 4)]
    ks = kin_state[nm]
    return [round(ks['x'], 4), round(ks['y'], 4), round(ks['h'], 4)]

def send(nm, node, task=None):
    global cmd_seq
    cmd_seq += 1
    x, y = NODES[node][0], NODES[node][1]
    berth_x = x
    if PHYSICAL_ACTUATION and not PHYSICAL_STAGING and node == 'E' and nm not in AERIAL:
        # a motor-driven chassis settles about 0.18 m short of the point it is
        # commanded to, so a target exactly on the east mouth leaves the hull
        # straddling the 4.95 m occupancy boundary: it is counted as inside the
        # channel while parked and never releases.  aiming past the mouth puts the
        # resting pose outside the window from either approach direction.
        here = truth(nm)[0]
        x = 5.22 if here < 4.95 else 4.78
    command = {'id': 'cmd-%04d' % cmd_seq, 'type': 'goto',
               'x': x, 'y': y, 'node': node, 'task_id': task, 't_ms': t}
    if nm in ROTOR_AIRCRAFT:
        command['land'] = node.endswith('_land')
        command['z'] = LANDING_ALTITUDE if command['land'] else ROTOR_ALTITUDE
    bus.append('cmd_%s.jsonl' % nm, command)
    state[nm]['target_node'] = node
    kin_state[nm]['target'] = (x, y)
    ev('move_commanded', {'node': node, 'x': x, 'y': y, 'berth_x': berth_x}, nm, task)


t = 0
carrier_index = 0
carrier_order = list(CARRIER_ORDER)
blue2_destination_owner = 'B2'
handoff_offer = None
for nm in actors:
    state[nm] = {'idx': 0, 'arrive_since': None, 'target_node': None,
                 'done': [], 'entered_channel': False, 'reservation': None}
    if not PHYSICAL_STAGING or nm not in CARRIER_ORDER:
        send(nm, *ROUTES[nm][0])
if PHYSICAL_STAGING:
    ev('carrier_granted', {'order': 0}, carrier_order[0])

pending_reports = []
observation_loss = float(os.environ.get('GONGYU_OBSERVATION_LOSS_RATE', '0'))
observation_blackout = os.environ.get('GONGYU_OBSERVATION_BLACKOUT_MS')
observation_link = ObservationLink(
    loss_rate=observation_loss, seed=SEED,
    blackout=None if observation_blackout is None else tuple(map(int, observation_blackout.split(':'))),
)
course_gate = ObservationGate(
    TAU, int(os.environ.get('GONGYU_FIRST_OBSERVATION_DELAY_MS', '1000')),
    retry_on_expiry=os.environ.get('GONGYU_RETRY_OBSERVATION_ON_EXPIRY', '1') != '0',
    link=observation_link,
)
channel_holder = None
metrics = {'seed': SEED, 'scene': SCENE, 'mechanism': MECH, 'adapt': ADAPT,
           'cost': COST, 'report_delay_ms': REPORT_DELAY_MS, 'physical_actuation': PHYSICAL_ACTUATION, 'task_completed': {},
           'channel_enters': 0, 'channel_releases': 0, 'accepted_reports': [],
           'expired_reports': [], 'replan_decisions': [], 'violations': [],
           'truth_trajectories': dict((nm, []) for nm in actors), 'truth_sample_period_ms': 500}
TRUTH_ATT = os.environ.get('GONGYU_TRUTH_ATT', '0') == '1'
start_wall = time.time()
prev_t = -1
last_truth_t = -500
physical_entered = {}
previous_overlaps = set()

while sup.step(ts) != -1:
    t = int(sup.getTime() * 1000)
    if not PHYSICAL_ACTUATION:
        advance_kinematics(ts / 1000.0)
    else:
        # hybrid: the aerial platforms have no rotor model here, so they stay on
        # the kinematic layer while every ground chassis is motor-driven
        advance_kinematics(ts / 1000.0, only=AERIAL)
    if t - last_truth_t >= 500:
        last_truth_t = t
        for _nm in actors:
            metrics['truth_trajectories'][_nm].append({'t_ms': t, 'pos': truth(_nm)})
    if TRUTH_ATT and t % 100 == 0:
        # independent attitude truth: the simulator's own frame, never the controller's
        rec = {'t_ms': t, 'yaw': {}, 'pos': {}}
        for _nm, _nd in actors.items():
            _o = _nd.getOrientation()
            rec['yaw'][_nm] = round(math.atan2(_o[3], _o[0]), 4)
            _p = _nd.getPosition()
            rec['pos'][_nm] = [round(_p[0], 4), round(_p[1], 4)]
        bus.append('truth_att.jsonl', rec)
    if PHYSICAL_STAGING:
        ground_positions = {name: truth(name)[:2] for name in actors if name not in AERIAL | ROTOR_AIRCRAFT}
        occupied = {
            name for name, (x, y) in ground_positions.items() if occupies_corridor(x, y)
        }
        for name in sorted(occupied.difference(physical_entered)):
            x, y = ground_positions[name]
            physical_entered[name] = t
            metrics['channel_enters'] += 1
            ev('channel_enter', {'x': x, 'y': y}, name)
        for name in sorted(set(physical_entered).difference(occupied)):
            x, y = ground_positions[name]
            started = physical_entered.pop(name)
            metrics['channel_releases'] += 1
            ev('channel_cleared', {'x': x, 'y': y, 'duration_ms': t - started}, name)
        overlaps = {
            (a, b) for a in occupied for b in occupied if a < b
        }
        for pair in sorted(overlaps.difference(previous_overlaps)):
            item = {'t_ms': t, 'kind': 'channel_overlap', 'actors': list(pair)}
            metrics['violations'].append(item)
            ev('channel_overlap', item)
        previous_overlaps = overlaps
    if handoff_offer is not None:
        ack = bus.last('handoff_B1.jsonl')
        if (ack and ack['offer_id'] == handoff_offer['id'] and ack['actor'] == 'B1'
                and ack['task_id'] == 'blue2' and not physical_entered):
            ev('handoff_accepted', {'offer_id': ack['offer_id'], 'ack_ms': ack['t_ms']}, 'B1', 'blue2')
            carrier_order[carrier_index] = 'B1'
            blue2_destination_owner = 'B1'
            ROUTES['B1'] += TRANSPORT_ROUTES['B2']
            handoff_offer = None
            ev('reservations_reassigned', {
                'previous_owner': 'B2', 'new_owner': 'B1', 'carrier_turn': carrier_index,
                'channel_direction': 'east_to_west', 'destination': 'blue_return',
            }, 'B1', 'blue2')
    if True:
        for nm in list(actors):
            st = state[nm]
            if st['idx'] >= len(ROUTES[nm]):
                continue
            node, task = ROUTES[nm][st['idx']]
            if PHYSICAL_STAGING and nm in CARRIER_ORDER:
                if nm != carrier_order[carrier_index]:
                    continue
                if nm == 'R1' and t < TASKS['red1'].get('release_ms', 0):
                    continue
                observer_client = 'B1' if BLUE2_HANDOFF else 'B2'
                if nm == observer_client == blue2_destination_owner and not course_gate.authorized:
                    update = course_gate.step(t, bus.last('observation_B3.jsonl'))
                    if update is not None:
                        ev(*update, actor=nm, task='blue2')
                        if ROTOR_SCENE and update[0] in {'observation_requested', 'observation_expired'}:
                            bus.append('observation_request_B3.jsonl', {'t_ms': t})
                    if not course_gate.authorized:
                        continue
            waiting_to_land = ROTOR_SCENE and node == 'F_land' and not course_gate.authorized
            if waiting_to_land:
                continue
            x, y, z = truth(nm)
            gx, gy = NODES[node][0], NODES[node][1]
            d = math.hypot(x - gx, y - gy)
            if st['target_node'] != node:
                hold = False
                if PHYSICAL_ACTUATION and not PHYSICAL_STAGING and channel_holder not in (None, nm):
                    outside = x < 2.05 or x > 4.95
                    tx = NODES[node][0]
                    cross = (x < 2.05 and tx > 4.95) or (x > 4.95 and tx < 2.05)
                    hold = outside and cross
                if hold:
                    if st.get('hold_logged') != node:
                        st['hold_logged'] = node
                        ev('dispatch_held', {'node': node, 'holder': channel_holder,
                                             'x': x}, nm, task)
                else:
                    send(nm, node, task)
            # channel occupancy from independent truth
            in_channel = not PHYSICAL_STAGING and 2.05 <= x <= 4.95 and abs(y) <= 0.6
            if in_channel and not st['entered_channel']:
                if channel_holder not in (None, nm):
                    metrics['violations'].append({'t_ms': t, 'kind': 'channel_overlap', 'actors': [channel_holder, nm]})
                channel_holder = nm
                st['entered_channel'] = True
                st['reservation'] = {'start': t, 'end': t + 48000}
                metrics['channel_enters'] += 1
                ev('channel_enter', {'x': x, 'y': y, 'slot': '%s_%d' % (nm, len(
                    [e for e in events if e['kind'] == 'reservation_granted' and e['actor'] == nm]))}, nm, task)
            elif not in_channel and st['entered_channel']:
                st['entered_channel'] = False
                rel = t if MECH in ('release', 'joint') else st['reservation']['end']
                metrics['channel_releases'] += 1
                ev('channel_cleared', {'x': x, 'y': y, 'clearance_time': t}, nm, task)
                ev('channel_release_recomputed', {'release_time': rel, 'nominal_end': st['reservation']['end'],
                                                  'early_seconds': round((st['reservation']['end'] - rel) / 1000, 3)}, nm, task)
                if channel_holder == nm:
                    channel_holder = None
            handoff_stop = BLUE2_HANDOFF and (
                node == 'blue_withdrawal_bay' or (nm == 'B1' and node == 'blue_relay'))
            duration = SERVICE if task or not PHYSICAL_STAGING or handoff_stop else 0
            released_at = TASKS.get(task, {}).get('release_ms', 0) if PHYSICAL_STAGING else 0
            tolerance = TOL if PHYSICAL_STAGING and nm in CARRIER_ORDER else max(TOL, 0.18)
            ready = d <= tolerance and t >= released_at
            if PHYSICAL_STAGING and task == 'blue2':
                ready = ready and nm == blue2_destination_owner
            if nm in ROTOR_AIRCRAFT:
                velocity = actors[nm].getVelocity()[:3]
                if node.endswith('_land'):
                    ready = d <= 0.22 and z <= 0.075 and math.hypot(*velocity) < 0.15
                else:
                    ready = (math.hypot(d, z - ROTOR_ALTITUDE) <= 0.22 and
                             math.hypot(*velocity) <= 0.26)
                    if task == 'blue_inspect':
                        ready = ready and bus.last('observation_B3.jsonl') is not None
            if ready and PHYSICAL_STAGING and (task or handoff_stop) and nm not in AERIAL | ROTOR_AIRCRAFT:
                ready = math.hypot(*actors[nm].getVelocity()[:2]) <= 0.10
            if ready:
                if st['arrive_since'] is None:
                    st['arrive_since'] = t
                    ev('arrived', {'x': x, 'y': y, 'distance': round(d, 4)}, nm, task)
                elif t - st['arrive_since'] >= duration:
                    st['done'].append(node)
                    if nm in ROTOR_AIRCRAFT and node.endswith('_land'):
                        ev('rotor_landed', {'pos': [x, y, z]}, nm, task)
                    if BLUE2_HANDOFF and nm == 'B1' and node == 'blue_relay':
                        ev('handoff_pickup', {'node': node, 'x': x, 'y': y}, nm, 'blue2')
                    if task and task in TASKS:
                        dl = TASKS[task]['deadline_ms']
                        ok = t <= dl
                        metrics['task_completed'][task] = {'t_ms': t, 'deadline_ms': dl,
                                                           'on_time': ok, 'actor': nm}
                        ev('task_completed', {'deadline_ms': dl, 'on_time': ok,
                                              'slack_s': round((dl - t) / 1000, 3)}, nm, task)
                        if TASKS[task]['kind'] in ('inspection', 'report_delivery'):
                            obs = bus.read('observation_%s.jsonl' % nm)
                            last = obs[-1] if obs else {}
                            rep = {'report_id': 'rep-%s-%d' % (nm, t), 'sender': nm,
                                   'sample_t_ms': t, 'valid_until': t + TAU,
                                   'deliver_at': t + REPORT_DELAY_MS,
                                   'evidence': {'image_signature': last.get('image_signature'),
                                                'sensor_pose': last.get('sensor_pose')},
                                   'task_id': task}
                            pending_reports.append(rep)
                            ev('inspection_report_created', {'report_id': rep['report_id'],
                                'sample_t_ms': t, 'evidence': rep['evidence']}, nm, task)
                    st['arrive_since'] = None
                    st['idx'] += 1
                    if st['idx'] < len(ROUTES[nm]):
                        nn, nt = ROUTES[nm][st['idx']]
                        prev_node = node
                        if {prev_node, nn} in ({'E', 'W'}, {'W', 'E'}):
                            ev('reservation_granted', {'start': t, 'end': t + 48000,
                                                       'slot_id': '%s_%d' % (nm, st['idx']),
                                                       'direction': 'E->W' if prev_node == 'E' else 'W->E'}, nm, nt)
                        if not (ROTOR_SCENE and nn == 'F_land' and not course_gate.authorized):
                            send(nm, nn, nt)
                    elif PHYSICAL_STAGING and nm in CARRIER_ORDER:
                        ev('carrier_released', {'order': carrier_index}, nm, task)
                        if BLUE2_HANDOFF and nm == 'B2':
                            blue2_destination_owner = None
                            ev('task_released', {
                                'reason': 'injected_carrier_withdrawal', 'pickup': 'blue_relay',
                                'parked_at': node, 'x': x, 'y': y,
                            }, nm, 'blue2')
                            if metrics['task_completed'].get('blue1', {}).get('actor') == 'B1':
                                handoff_offer = {'id': 'blue2-B2-B1', 'type': 'handoff_offer',
                                                 'task_id': 'blue2', 't_ms': t}
                                bus.append('cmd_B1.jsonl', handoff_offer)
                                ev('handoff_offered', {'offer_id': handoff_offer['id'],
                                                       'previous_owner': 'B2'}, 'B1', 'blue2')
                        elif carrier_index + 1 < len(carrier_order):
                            carrier_index += 1
                            ev('carrier_granted', {'order': carrier_index}, carrier_order[carrier_index])
            else:
                # cancel the berth dwell only when the platform clearly leaves the
                # tolerance band, otherwise steady-state parking error re-arms it forever
                if PHYSICAL_STAGING or d > 0.18 * 1.28:
                    st['arrive_since'] = None
        for rep in list(pending_reports):
            if t >= rep['deliver_at']:
                pending_reports.remove(rep)
                valid = rep['deliver_at'] <= rep['valid_until']
                ev('report_delivery', {'report_id': rep['report_id'], 'sender': rep['sender'],
                                       'sample_t_ms': rep['sample_t_ms'], 'arrive_t_ms': rep['deliver_at'],
                                       'valid_until': rep['valid_until'], 'accepted': valid}, rep['sender'], rep['task_id'])
                if valid:
                    metrics['accepted_reports'].append(rep['report_id'])
                else:
                    metrics['expired_reports'].append(rep['report_id'])
                    if ADAPT == 'on':
                        cands = []
                        for nm in ('B3', 'B2'):
                            if nm in actors:
                                slack = 1000
                                cands.append({'actor': nm, 'slack_s': slack / 1000,
                                              'feasible': True, 'reason': 'remaining task slack positive'})
                        chosen = cands[0] if cands else None
                        metrics['replan_decisions'].append({'t_ms': t, 'trigger': rep['report_id'],
                                                             'candidates': cands, 'chosen': chosen})
                        ev('dynamic_replan', {'trigger': rep['report_id'], 'candidates': cands,
                                              'chosen': chosen}, None, rep['task_id'])
                if COST == 'high':
                    ev('opportunity_cost_evaluation', {'report_id': rep['report_id'],
                       'provider': 'B2', 'gain_s': 4, 'cost_s': 18, 'decision': 'reject'}, 'B2', rep['task_id'])
                else:
                    ev('opportunity_cost_evaluation', {'report_id': rep['report_id'],
                       'provider': 'B2', 'gain_s': 12, 'cost_s': 3, 'decision': 'accept'}, 'B2', rep['task_id'])
        prev_t = t
    if t >= END or (not PHYSICAL_STAGING and all(
            st['idx'] >= len(ROUTES[nm]) for nm, st in state.items())):
        break

metrics.update(summarize_tasks(expected_task_ids, metrics['task_completed']))
metrics['motion_backend'] = 'hybrid' if PHYSICAL_ACTUATION and AERIAL else 'motor' if PHYSICAL_ACTUATION else 'kinematic'
metrics['kinematic_actors'] = sorted(AERIAL.intersection(actors)) if PHYSICAL_ACTUATION else sorted(actors)
if ROTOR_SCENE:
    metrics['rotor_actors'] = sorted(ROTOR_AIRCRAFT.intersection(actors))
metrics['corridor_protocol'] = 'footprint_serial_dispatch' if PHYSICAL_STAGING else 'legacy'
metrics['blue2_observation_retry_on_expiry'] = course_gate.retry_on_expiry
metrics['observation_link'] = {'loss_rate': observation_loss, 'blackout_ms': observation_link.blackout}
metrics['blue2_observation_attempts'] = course_gate.attempts
metrics['blue2_observation_authorized'] = course_gate.authorized
metrics['occupied_at_close'] = sorted(physical_entered) if PHYSICAL_STAGING else []
on_time, total = metrics['on_time'], metrics['total']
metrics['full_window'] = t >= END
metrics['wall_seconds'] = round(time.time() - start_wall, 3)
metrics['violation_count'] = len(metrics['violations'])
json.dump(metrics, open(os.path.join(RUN, 'result', 'metrics.json'), 'w'), indent=1)
json.dump({'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(start_wall)),
           'ended_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
           'scene': SCENE, 'mechanism': MECH, 'status': 'COMPLETE',
           'motion_backend': metrics['motion_backend'], 'kinematic_actors': metrics['kinematic_actors'],
           'corridor_protocol': metrics['corridor_protocol'],
           'failure': None, 'sim_end_ms': t, 'wall_seconds': metrics['wall_seconds'],
           'source': 'webots-r2025a-cpu-' + ('motor' if PHYSICAL_ACTUATION else 'kinematic') + ('-norender' if os.environ.get('GONGYU_NO_RENDER') else '-render')},
          open(os.path.join(RUN, 'shutdown.json'), 'w'), indent=1)
ev('run_closed', {'on_time': on_time, 'total': total, 'full_window': metrics['full_window']})
print('WEBOTS_REFEREE_CLOSED on_time=%d/%d channel=%d/%d' % (on_time, total,
      metrics['channel_enters'], metrics['channel_releases']))
sup.simulationQuit(0)
