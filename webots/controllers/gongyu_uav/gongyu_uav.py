#!/usr/bin/env python3
"""UAV controller: declared GPS/IMU/gyro feedback driving four propeller motors."""
import json
import math
import os
import sys
from controller import Robot

sys.path.insert(0, os.environ.get('GONGYU_WEBOTS_COMMON', ''))
from bus import Bus
from adversary import ReplayAttacker, sign_frame

robot = Robot()
name = robot.getName()
ts = int(robot.getBasicTimeStep())
run_dir = os.environ.get('GONGYU_RUN_DIR', '/tmp/gongyu_default')
mode = os.environ.get('GONGYU_FEEDBACK_MODE', 'sensor')
aerial_kinematic = set(os.environ.get('GONGYU_AERIAL', '').split(','))
physical_actuation = os.environ.get('GONGYU_PHYS', '0') == '1' and name not in aerial_kinematic
ADVERSARY = set(filter(None, os.environ.get('GONGYU_ADVERSARY', '').split(',')))
DEFENSE = set(filter(None, os.environ.get('GONGYU_DEFENSE', '').split(',')))
BLUE_KEY = os.environ.get('GONGYU_BLUE_KEY', '')
attacker = (ReplayAttacker(intercept_range_m=8.0, inject_range_m=10.0, min_age_ms=20000)
            if name == 'R5' and 'spoof' in ADVERSARY else None)
bus = Bus(os.path.join(run_dir, 'bus'))

gps = robot.getDevice('gps'); gps.enable(ts)
imu = robot.getDevice('inertial unit'); imu.enable(ts)
gyro = robot.getDevice('gyro'); gyro.enable(ts)
cam = robot.getDevice('camera'); cam.enable(4 * ts)
motors = [robot.getDevice(n) for n in ('front left propeller', 'front right propeller',
                                       'rear left propeller', 'rear right propeller')]
for m in motors:
    m.setPosition(float('inf'))
    m.setVelocity(1.0)

# gains adapted from the Webots Mavic2Pro reference controller
K_T = 68.5
K_O = 0.6
K_V = 3.0
K_ROLL = 50.0
K_PITCH = 30.0
K_YAW = 0.4
cmd = None
last_read = -10**9
last_log = -10**9
last_obs = -10**9


def clamp(v, a, b):
    return max(a, min(b, v))


while robot.step(ts) != -1:
    t = int(robot.getTime() * 1000)
    g = gps.getValues()
    a = imu.getRollPitchYaw()
    w = gyro.getValues()
    # feedback source: sensor mode uses declared devices; reference mode is labelled
    px, pz = g[0], g[1]
    if t - last_read > 200:
        c = bus.last('cmd_%s.jsonl' % name)
        if c and c.get('id') != (cmd or {}).get('id'):
            cmd = c
            bus.append('ctl_events.jsonl', {'t_ms': t, 'actor': name, 'kind': 'command_received',
                                            'cmd_id': cmd.get('id'), 'target': [cmd.get('x'), cmd.get('y')],
                                            'feedback_mode': mode})
        last_read = t
    tx, ty, tz = (cmd or {}).get('x', px), 2.5, (cmd or {}).get('y', pz)
    roll, pitch = a[0], a[1]
    yaw_rate = w[1]
    dx, dz = tx - px, tz - pz
    # body-frame desired acceleration from world-frame error
    ax = clamp(dx * 0.6, -3, 3)
    az = clamp(dz * 0.6, -3, 3)
    target_roll = clamp(az, -0.5, 0.5)
    target_pitch = clamp(-ax, -0.5, 0.5)
    vertical = K_T + K_V * (ty - g[2] - K_O)
    fl = vertical + K_ROLL * (target_roll - roll) + K_YAW * yaw_rate
    fr = vertical - K_ROLL * (target_roll - roll) - K_YAW * yaw_rate
    rl = vertical + K_PITCH * (target_pitch - pitch) - K_YAW * yaw_rate
    rr = vertical - K_PITCH * (target_pitch - pitch) + K_YAW * yaw_rate
    if physical_actuation:
        for m, v in zip(motors, (fl, fr, rl, rr)):
            m.setVelocity(clamp(v, 0, 1200))
    else:
        # kinematics-driven: chassis motion applied by independent referee model
        for m in motors:
            m.setVelocity(0.0)
    if t - last_log >= 500:
        bus.append('tel_%s.jsonl' % name, {
            't_ms': t, 'actor': name, 'feedback_mode': mode, 'actuation': 'motor' if physical_actuation else 'kinematic',
            'sensor_pose': [round(px, 4), round(pz, 4), round(g[2], 4), round(float(a[2]), 4)],
            'gps': [round(float(v), 4) for v in g],
            'imu': [round(float(v), 4) for v in a],
            'gyro': [round(float(v), 4) for v in w],
            'cmd_id': (cmd or {}).get('id')})
        last_log = t
    if attacker is not None:
        obs = bus.last('observation_B3.jsonl')
        if obs:
            attacker.observe((px, pz), obs)
        req = bus.last('observation_request_B3.jsonl')
        if req:
            res = attacker.forge(t, (px, pz), req, req.get('requester_xy', (8.0, 1.6)))
            if res is not None:
                forged, original = res
                bus.append('observation_B3.jsonl', forged)
                bus.append('red_injections.jsonl', {
                    't_ms': t, 'forged_t_ms': forged['t_ms'],
                    'original_t_ms': original['t_ms'],
                    'request_id': req.get('request_id'),
                    'r5_xy': [round(px, 3), round(pz, 3)]})
    if t - last_obs >= 1000:
        img = cam.getImage()
        # Image-derived signature: no global object label is taken from the referee.
        sig = 0
        if img:
            for i in range(0, min(len(img), 160 * 120 * 4), 397):
                sig = (sig * 31 + img[i]) % 1000003
        rec = {
            't_ms': t, 'actor': name, 'camera_bytes': len(img) if img else 0,
            'image_signature': sig, 'sensor_pose': [round(px, 3), round(pz, 3)]}
        if name == 'B3' and 'auth' in DEFENSE and BLUE_KEY:
            rec = sign_frame(BLUE_KEY, rec)
        bus.append('observation_%s.jsonl' % name, rec)
        last_obs = t
