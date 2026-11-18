#!/usr/bin/env python3
"""UGV controller: wheel encoders + LiDAR + IMU, motor-level closed loop."""
import json
import math
import os
import sys
from controller import Robot

sys.path.insert(0, os.environ.get('GONGYU_WEBOTS_COMMON', ''))
from bus import Bus

R = 0.07
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
rl = robot.getDevice('rear_left_motor'); rr = robot.getDevice('rear_right_motor')
for m in (left, right, rl, rr):
    m.setPosition(float('inf'))
    m.setVelocity(0.0)
enc = [robot.getDevice(n) for n in ('left_sensor', 'right_sensor', 'rear_left_sensor', 'rear_right_sensor')]
for e in enc:
    e.enable(ts)
lid_main = robot.getDevice('lidar_main'); lid_low = robot.getDevice('lidar_low')
lid_main.enable(ts); lid_low.enable(ts)
imu = robot.getDevice('imu'); imu.enable(ts)
compass = robot.getDevice('compass'); compass.enable(ts)
gps = robot.getDevice('gps'); gps.enable(ts)

# odometry in scenario (x,y) coordinates; Webots z is scenario y
x = y = theta = 0.0
prev = None
init_pose = None
cmd = None
last_log = -10**9
last_cmd_read = -10**9


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
    vals = [e.getValue() for e in enc]
    if prev is None:
        prev = vals
    dl = ((vals[0] - prev[0]) + (vals[2] - prev[2])) / 2 * R
    dr = ((vals[1] - prev[1]) + (vals[3] - prev[3])) / 2 * R
    prev = vals
    dth = (dr - dl) / BASE
    x += (dl + dr) / 2 * math.cos(theta + dth / 2)
    y += (dl + dr) / 2 * math.sin(theta + dth / 2)
    theta += dth
    # scan-map correction: corridor walls are at scenario y = +/-0.5 for x in [1.8,5.4]
    front, lside, rside = ranges(lid_main)
    low_front, _, _ = ranges(lid_low)
    x_c, y_c, th_c, corrected = x, y, theta, False
    if 2.0 < x < 5.2 and min(lside, rside) < 1.0:
        y_c = 0.0 if abs(y) < 0.45 else y
        corrected = True
    if t - last_cmd_read > 200:
        c = bus.last('cmd_%s.jsonl' % name)
        if c and c.get('id') != (cmd or {}).get('id'):
            cmd = c
            bus.append('ctl_events.jsonl', {'t_ms': t, 'actor': name, 'kind': 'command_received',
                                            'cmd_id': cmd.get('id'), 'target': [cmd.get('x'), cmd.get('y')]})
        last_cmd_read = t
    v = 0.0
    omega = 0.0
    if cmd and cmd.get('type') == 'goto':
        dx = cmd['x'] - x_c
        dy = cmd['y'] - y_c
        dist = math.hypot(dx, dy)
        desired = math.atan2(dy, dx)
        err = math.atan2(math.sin(desired - th_c), math.cos(desired - th_c))
        # arrival hysteresis: stop both translation and rotation inside tolerance
        if dist <= 0.16:
            v = 0.0
            omega = 0.0
        else:
            omega = clamp(KP_HEAD * err, -1.5, 1.5)
            v = V_MAX if dist > 0.22 else V_MAX * 0.5
        if front < 0.35 or low_front < 0.30:
            v *= 0.25
            omega += 0.8 if lside > rside else -0.8
        if abs(err) > 1.0:
            v *= 0.35
    wl = (v - omega * BASE / 2) / R
    wr = (v + omega * BASE / 2) / R
    for m, w in ((left, wl), (right, wr), (rl, wl), (rr, wr)):
        m.setVelocity(clamp(w, -12, 12))
    if t - last_log >= 500:
        bus.append('tel_%s.jsonl' % name, {
            't_ms': t, 'actor': name,
            'odom': [round(x, 4), round(y, 4), round(theta, 4)],
            'corrected': [round(x_c, 4), round(y_c, 4), round(th_c, 4)],
            'scan_corrected': corrected,
            'lidar_main': [round(front, 3), round(lside, 3), round(rside, 3)],
            'lidar_low_front': round(low_front, 3),
            'imu': [round(float(a), 4) for a in imu.getRollPitchYaw()],
            'compass': [round(float(a), 4) for a in compass.getValues()],
            'cmd_id': (cmd or {}).get('id'),
            'own_estimate': [round(x, 4), round(y, 4)]})
        last_log = t
