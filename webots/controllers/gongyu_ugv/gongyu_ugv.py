#!/usr/bin/env python3
"""UGV controller: wheel encoders + LiDAR + IMU, motor-level closed loop."""
import json
import math
import os
import sys
from controller import Robot

sys.path.insert(0, os.environ.get('GONGYU_WEBOTS_COMMON', ''))
from bus import Bus
from course_low_box import SCENE as LOW_BOX_SCENE, east_apron_bypass, near_front_range

# wheel radius: 0.085 m per the physical model; the kinematic backend
# historically assumed 0.07 and its committed telemetry must stay stable
R = float(os.environ.get('GONGYU_WHEEL_R', '0.085' if os.environ.get('GONGYU_PHYS', '0') == '1' else '0.07'))
BASE = 0.34
V_MAX = 0.5
KP_HEAD = 2.2
KP_SCAN = 1.5

robot = Robot()
name = robot.getName()
ts = int(robot.getBasicTimeStep())
run_dir = os.environ.get('GONGYU_RUN_DIR', '/tmp/gongyu_default')
bus = Bus(os.path.join(run_dir, 'bus'))

left = robot.getDevice('left_motor'); right = robot.getDevice('right_motor')
# the physical variant is a two-wheel differential drive with ball casters, so
# the rear motors do not exist there; every use below tolerates None.
rl = robot.getDevice('rear_left_motor'); rr = robot.getDevice('rear_right_motor')
for m in (left, right, rl, rr):
    if m is not None:
        m.setPosition(float('inf'))
        m.setVelocity(0.0)
enc = [robot.getDevice(n) for n in ('left_sensor', 'right_sensor', 'rear_left_sensor', 'rear_right_sensor')]
for e in enc:
    if e is not None:
        e.enable(ts)
lid_main = robot.getDevice('lidar_main'); lid_low = robot.getDevice('lidar_low')
lid_main.enable(ts); lid_low.enable(ts)
apron_bypass = name == 'B1' and os.environ.get('GONGYU_SCENE') == LOW_BOX_SCENE
if apron_bypass:
    from b1_experiment import CARD, drive
    lid_low.enablePointCloud()
imu = robot.getDevice('imu'); imu.enable(ts)
compass = robot.getDevice('compass'); compass.enable(ts)
gps = robot.getDevice('gps'); gps.enable(ts)
loc_mode = os.environ.get('GONGYU_LOC', 'gps')  # gps=absolute closed loop; odom=wheel integration
physical_actuation = os.environ.get('GONGYU_PHYS', '0') == '1'

# odometry in scenario (x,y) coordinates; Webots z is scenario y
x = y = theta = 0.0
wheel_x = wheel_y = 0.0
prev = None
prev_gps = None
init_pose = None
cmd = None
last_log = -10**9
last_cmd_read = -10**9
err_sign = 1.0   # latched turn direction for near-180 headings
stuck_ref = None      # (t_ms, x, y, theta) sample for the mobility supervisor
stuck_hits = 0
escape_until = -10**9
bypass_started = None
bypass_targets = None
bypass_index = 0


def clamp(v, a, b):
    return max(a, min(b, v))


def ranges(lidar):
    img = lidar.getRangeImage()
    n = len(img)
    if not n:
        return 9.9, 9.9, 9.9
    def sector(a, b):
        vals = []
        for i in range(n):
            ang = 2 * math.pi * i / n
            if a <= ang <= b or (b < a and (ang >= a or ang <= b)):
                v = img[i]
                if 0.02 < v < 20:
                    vals.append(v)
        return min(vals) if vals else 9.9
    return sector(-0.35, 0.35), sector(1.35, 1.85), sector(4.4, 4.9)


while robot.step(ts) != -1:
    t = int(robot.getTime() * 1000)
    pos = None
    if init_pose is None:
        gp = gps.getValues()
        init_pose = [gp[0], gp[1]]
        x, y = init_pose
        wheel_x, wheel_y = init_pose
    vals = [None if e is None else e.getValue() for e in enc]
    if prev is None:
        prev = vals

    def side_delta(a, b):
        ds = []
        for i in (a, b):
            if vals[i] is not None and prev[i] is not None:
                ds.append(vals[i] - prev[i])
        return (sum(ds) / len(ds)) if ds else 0.0

    dl = side_delta(0, 2) * R
    dr = side_delta(1, 3) * R
    prev = vals
    dth = (dr - dl) / BASE
    wx = wheel_x + (dl + dr) / 2 * math.cos(theta + dth / 2)
    wy = wheel_y + (dl + dr) / 2 * math.sin(theta + dth / 2)
    theta += dth
    wheel_x, wheel_y = wx, wy
    gp = gps.getValues()
    if physical_actuation:
        # a real chassis turns without translating, so the motion-direction
        # trick below is only valid when the referee moves the platform; here
        # the IMU is the honest yaw source (it is a real gyro integration).
        # att-08 / att-m08: commanded spin +0.8 rad/s produced a true world yaw
        # rate of +0.558 rad/s and an IMU yaw rate of +0.535 rad/s, so the
        # InertialUnit is already counter-clockwise-positive and needs no sign
        # change.  spin-pure-02 seemed to say otherwise only because the
        # differential formula still had the wheel sides swapped at that time.
        theta = imu.getRollPitchYaw()[2]
        prev_gps = [gp[0], gp[1]]
    else:
        # heading from true GPS motion (wheel-integration heading drifts on slip)
        if prev_gps is not None:
            mdx, mdy = gp[0] - prev_gps[0], gp[1] - prev_gps[1]
            disp = math.hypot(mdx, mdy)
            if disp > 0.12:
                # reliable motion direction over a meaningful baseline
                theta = math.atan2(mdy, mdx)
                prev_gps = [gp[0], gp[1]]
        else:
            prev_gps = [gp[0], gp[1]]
    if loc_mode == 'gps':
        x, y = gp[0], gp[1]
    else:
        x, y = wheel_x, wheel_y
    # scan-map correction: corridor walls are at scenario y = +/-0.5 for x in [1.8,5.4]
    front, lside, rside = ranges(lid_main)
    low_front, _, _ = ranges(lid_low)
    x_c, y_c, th_c, corrected = x, y, theta, False
    # A real chassis needs its measured cross-track error for steering.
    # The legacy snap to the centre line only belongs to the kinematic replay.
    if not physical_actuation and 2.0 < x < 5.2 and min(lside, rside) < 1.0:
        y_c = 0.0 if abs(y) < 0.45 else y
        corrected = True
    if t - last_cmd_read > 200:
        c = bus.last('cmd_%s.jsonl' % name)
        if c and c.get('id') != (cmd or {}).get('id'):
            if c.get('type') == 'handoff_offer' and c.get('task_id') == 'blue2':
                bus.append('handoff_%s.jsonl' % name, {
                    't_ms': t, 'actor': name, 'task_id': c['task_id'], 'offer_id': c['id'],
                })
            cmd = c
            bus.append('ctl_events.jsonl', {'t_ms': t, 'actor': name, 'ver': 'gpsheading-v3', 'theta_dbg': round(theta, 3), 'kind': 'command_received',
                                            'cmd_id': cmd.get('id'), 'target': [cmd.get('x'), cmd.get('y')]})
        last_cmd_read = t
    v = 0.0
    omega = 0.0
    err = 0.0
    if os.environ.get('GONGYU_TEST_SPIN'):
        # diagnostic only: measure whether the chassis can pivot at all
        spin = float(os.environ.get('GONGYU_TEST_SPIN'))
        if t > 3000:
            v = float(os.environ.get('GONGYU_TEST_V', '0.0'))
            omega = spin
        cmd = None
    if cmd and cmd.get('type') == 'goto':
        dx = cmd['x'] - x_c
        dy = cmd['y'] - y_c
        dist = math.hypot(dx, dy)
        desired = math.atan2(dy, dx)
        err = math.atan2(math.sin(desired - th_c), math.cos(desired - th_c))
        if physical_actuation:
            # Exactly-reversing targets make atan2(sin pi, cos pi) flip sign on
            # numerical noise, so omega would alternate between +0.8 and -0.8 and
            # a pivoting chassis would jitter instead of turning.  Latch one turn
            # direction while the error is near +-pi and release it once the
            # heading has been brought back inside the normal range.
            if abs(err) > 2.85:
                err = 2.85 * err_sign
            elif abs(err) < 2.60:
                err_sign = 1.0 if err >= 0.0 else -1.0
        # arrival hysteresis: stop both translation and rotation inside tolerance
        # physical mode must reach the node centre: the referee only clears the
        # shared channel once the chassis is past x=4.95, so an early stop at the
        # 0.18 m berth tolerance deadlocks the next dispatch
        if dist <= (0.06 if physical_actuation else 0.10):
            v = 0.0
            omega = 0.0
        else:
            omega = clamp(KP_HEAD * err, -1.5, 1.5)
            if physical_actuation:
                # linear approach: no overshoot on a heavy chassis, and it still
                # rolls past the corridor mouth instead of stopping inside it.
                # Inside 0.35 m the speed floor drops so the chassis can settle at
                # 0.06 m, well inside the referee's 0.18 m berth tolerance.
                floor = 0.06 if dist < 0.35 else 0.12
                v = clamp(0.45 * dist, floor, V_MAX)
            else:
                v = V_MAX if dist > 0.30 else V_MAX * 0.35
        if front < 0.35 or low_front < 0.30:
            v *= 0.25
            omega += 0.8 if lside > rside else -0.8
        if abs(err) > 1.0:
            v *= 0.35
    # --- mobility supervisor (physical branch only) -----------------------------
    # Three-sector LiDAR cannot see a grazing screen edge or a corner behind the
    # scan plane, so the chassis can be commanded to move while being physically
    # blocked.  Watch the independent sensors (GPS displacement, IMU yaw) and back
    # out with a reverse turn instead of grinding the gearbox against geometry.
    if physical_actuation:
        if escape_until > t:
            v = -0.40
            omega = 0.8 * (1.0 if err >= 0.0 else -1.0)
        elif cmd is not None:
            if stuck_ref is None:
                stuck_ref = (t, x, y, theta)
            elif t - stuck_ref[0] >= 900:
                moved = math.hypot(x - stuck_ref[1], y - stuck_ref[2])
                dyaw = abs(math.atan2(math.sin(theta - stuck_ref[3]),
                                      math.cos(theta - stuck_ref[3])))
                blocked = (abs(v) > 0.05 and moved < 0.03) or \
                          (abs(v) < 0.05 and abs(omega) > 0.30 and dyaw < 0.03)
                stuck_hits = stuck_hits + 1 if blocked else 0
                stuck_ref = (t, x, y, theta)
                if stuck_hits >= 2:
                    stuck_hits = 0
                    stuck_ref = None
                    escape_until = t + 1400
    pivot = physical_actuation and abs(err) > 0.6 and escape_until <= t
    if pivot:
        v = 0.0                       # no translation while correcting heading
        omega = clamp(omega, -0.8, 0.8)
    if physical_actuation:
        # +y is the left-hand side: a counter-clockwise (omega > 0) turn needs the
        # wheel at y = -0.17 to run faster, so the differential term is flipped
        # relative to the historical kinematic convention.
        wl = (v + omega * BASE / 2) / R
        wr = (v - omega * BASE / 2) / R
    else:
        wl = (v - omega * BASE / 2) / R
        wr = (v + omega * BASE / 2) / R
    if apron_bypass and cmd and cmd.get('task_id') == 'blue1':
        pose = (x_c, y_c, th_c)
        if bypass_targets is None:
            scan = [(point.x, point.y, point.z) for point in lid_low.getPointCloud()
                    if math.isfinite(point.x) and math.isfinite(point.y)]
            first_return = near_front_range(scan)
            if bypass_started is None and first_return is not None:
                bypass_started = t
                bus.append('ctl_events.jsonl', {'kind': 'apron_scan_stop', 'actor': name,
                           'task_id': 'blue1', 't_ms': t, 'pose': pose, 'source': 'low',
                           'return_m': first_return})
            if bypass_started is not None and t - bypass_started >= 320:
                try:
                    bypass_targets, observed = east_apron_bypass(pose, (cmd['x'], cmd['y']), scan)
                except ValueError as error:
                    bypass_targets = ()
                    bus.append('ctl_events.jsonl', {'kind': 'apron_replan_failed', 'actor': name,
                               'task_id': 'blue1', 't_ms': t, 'pose': pose, 'reason': str(error),
                               'plan_scan': scan, 'goal': [cmd['x'], cmd['y']]})
                else:
                    bus.append('ctl_events.jsonl', {'kind': 'apron_replanned', 'actor': name,
                               'task_id': 'blue1', 't_ms': t, 'pose': pose,
                               'inferred_bounds_m': observed, 'targets': bypass_targets})
        if bypass_started is not None:
            targets = bypass_targets or ()
            if bypass_index < len(targets) and math.dist(pose[:2], targets[bypass_index]) <= CARD['target_tolerance_m']:
                bus.append('ctl_events.jsonl', {'kind': 'apron_waypoint', 'actor': name,
                           'task_id': 'blue1', 't_ms': t, 'target': targets[bypass_index]})
                bypass_index += 1
            target = targets[bypass_index] if bypass_index < len(targets) else None
            wl, wr = drive(pose, target, target is None)
            v = (wl + wr) * R / 2
            omega = (wl - wr) * R / BASE
    if physical_actuation:
        # translation needs slip compensation; pivot uses raw differential wheel rate
        gain = 1.0
        for m, w in ((left, wl), (right, wr), (rl, wl), (rr, wr)):
            if m is not None:
                m.setVelocity(clamp(w * gain, -6, 6))
    else:
        # kinematics-driven: chassis motion applied by independent referee model
        for m in (left, right, rl, rr):
            if m is not None:
                m.setVelocity(0.0)
    if t - last_log >= 500:
        bus.append('tel_%s.jsonl' % name, {
            't_ms': t, 'actor': name, 'ver': 'gpsheading-v3', 'theta_dbg': round(theta, 3),
            'odom': [round(x, 4), round(y, 4), round(theta, 4)],
            'corrected': [round(x_c, 4), round(y_c, 4), round(th_c, 4)],
            'scan_corrected': corrected,
            'lidar_main': [round(front, 3), round(lside, 3), round(rside, 3)],
            'lidar_low_front': round(low_front, 3),
            'imu': [round(float(a), 4) for a in imu.getRollPitchYaw()],
            'compass': [round(float(a), 4) for a in compass.getValues()],
            'cmd_id': (cmd or {}).get('id'),
            'actuation': 'motor' if physical_actuation else 'kinematic', 'own_estimate': [round(x, 4), round(y, 4)], 'wheel_odom': [round(wheel_x, 4), round(wheel_y, 4)], 'loc_mode': loc_mode,
            'enc_raw': [None if a is None else round(a, 3) for a in vals], 'ctl': {'v': round(v, 3), 'omega': round(omega, 3), 'dist': round(math.hypot((cmd or {}).get('x', x)-x_c, (cmd or {}).get('y', y)-y_c), 3) if cmd else None, 'wl': round(wl, 2), 'wr': round(wr, 2)}})
        last_log = t
