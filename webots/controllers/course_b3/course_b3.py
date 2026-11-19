"""Fly one ENU worksite route using Webots motor thrust and onboard feedback."""
import hashlib
import json
import math
import os
from pathlib import Path
import sys

from controller import Robot

sys.path.insert(0, os.environ["GONGYU_WEBOTS_COMMON"])
from bus import Bus

MODE = os.environ.get("GONGYU_FEEDBACK_MODE", "sensor")
DROP_GPS = os.environ.get("GONGYU_UAV_DROPOUT", "0") == "1"
RUN = Path(os.environ["GONGYU_RUN_DIR"])
ROUTE = [(0.0, 0.0, 1.9), (2.2, 0.8, 1.9), (2.2, 0.8, 1.9), (0.0, 0.0, 1.9), (0.0, 0.0, 0.045)]
STAGES = ["takeoff_reached", "waypoint_reached", "hover_complete", "home_reached", "landed"]
MOTORS = ("front left propeller", "front right propeller", "rear left propeller", "rear right propeller")
GP_MS = 32
FRAME_MS = 160
MAX_POSITION_AGE_MS = 96


def limit(value, lower, upper):
    return max(lower, min(upper, value))


def motor_command(target, p, v, rpy, gyro, hold):
    roll, pitch, yaw = rpy
    c, s = math.cos(yaw), math.sin(yaw)
    ax, ay = [limit(1.4 * (goal - pos) - 1.7 * vel, -2.0, 2.0)
              for goal, pos, vel in zip(target[:2], p[:2], v[:2])]
    desired_roll = (s * ax - c * ay) / 9.81
    desired_pitch = (c * ax + s * ay) / 9.81
    if hold:
        desired_roll = desired_pitch = 0.0
    attitude = [desired_roll, desired_pitch, 0.0]
    yaw_error = math.atan2(math.sin(-yaw), math.cos(-yaw))
    tx = limit(0.18 * (desired_roll - roll) - 0.042 * gyro[0], -0.16, 0.16)
    ty = limit(0.18 * (desired_pitch - pitch) - 0.042 * gyro[1], -0.16, 0.16)
    tz = limit(0.025 * yaw_error - 0.015 * gyro[2], -0.028, 0.028)
    az = limit(3.6 * (target[2] - p[2]) - 3.1 * v[2], -2.2, 3.5)
    tilt = max(0.75, math.cos(roll) * math.cos(pitch))
    thrust = 0.42 * (9.81 + az) / tilt
    speeds = []
    for x, y in [(1, 1), (1, -1), (-1, 1), (-1, -1)]:
        spin = x * y
        force = (thrust + y * tx / 0.15 - x * ty / 0.15 - spin * tz / 0.018) / 4
        speeds.append(spin * math.sqrt(limit(force, 0.0, 0.000030 * 360**2) / 0.000030))
    return speeds, attitude


def sample_camera(camera, timestamp, bus):
    frame = camera.getImage()
    width, height = camera.getWidth(), camera.getHeight()
    if frame is None or len(frame) != width * height * 4:
        return None
    blue, green, red = frame[0::4], frame[1::4], frame[2::4]
    rgb = bytearray(width * height * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = red, green, blue
    filename = f"worksite_{timestamp:05d}.ppm"
    (RUN / "evidence" / filename).write_bytes(f"P6\n{width} {height}\n255\n".encode() + rgb)
    pixels = sum(r >= 100 and b >= 100 and min(r, b) - g >= 50 for r, g, b in zip(red, green, blue))
    record = {
        "t_ms": timestamp, "camera_bytes": len(frame), "marker_pixels": pixels,
        "frame": filename, "rgb_sha256": hashlib.sha256(rgb).hexdigest(),
    }
    bus.append("uav_frames.jsonl", record)
    return record


def run():
    robot = Robot()
    dt = int(robot.getBasicTimeStep())
    bus = Bus(RUN / "bus")
    gps, imu, gyro, cam, rx = [robot.getDevice(name) for name in ("gps", "inertial unit", "gyro", "camera", "reference receiver")]
    for device, period in [(gps, GP_MS), (imu, dt), (gyro, dt), (cam, FRAME_MS)]:
        device.enable(period)
    if MODE == "truth":
        rx.enable(dt)
    motors = [robot.getDevice(name) for name in MOTORS]
    for motor in motors:
        motor.setPosition(float("inf"))
        motor.setVelocity(0.0)

    p = v = rpy = omega = None
    estimate_t = None
    stage = 0
    arrived_at = None
    holding = False
    report_sent = False
    while robot.step(dt) != -1:
        t = round(robot.getTime() * 1000)
        if t > 28000:
            continue
        raw_gps = None
        if MODE == "truth":
            while rx.getQueueLength():
                packet = json.loads(rx.getString())
                p, v, rpy, omega = (packet[key] for key in ("p", "v", "rpy", "body_omega"))
                estimate_t = packet["t_ms"]
                rx.nextPacket()
        else:
            rpy, omega = imu.getRollPitchYaw(), gyro.getValues()
            if t % GP_MS == 0 and not (DROP_GPS and 4480 <= t < 5056):
                gps_position, gps_speed = gps.getValues(), gps.getSpeedVector()
                if all(math.isfinite(val) for val in gps_position + gps_speed):
                    p, v, estimate_t = gps_position, gps_speed, t
                    raw_gps = {"p": p, "v": v, "sample_t_ms": t}

        def event(kind):
            bus.append("uav_events.jsonl", {"t_ms": t, "kind": kind, "position_sample_ms": estimate_t})

        target = ROUTE[min(stage, len(ROUTE) - 1)]
        age = t - estimate_t if estimate_t is not None else None
        stale = age is not None and age > MAX_POSITION_AGE_MS
        if stale != holding:
            event("position_stale" if stale else "position_recovered")
            holding = stale

        speeds, desired = [0.0] * 4, None
        estimate = None
        if p is not None and all(math.isfinite(val) for val in (*rpy, *omega)):
            estimate = {"p": p, "v": v, "rpy": rpy, "body_omega": omega}
            if stage < len(ROUTE):
                speeds, desired = motor_command(target, p, v, rpy, omega, stale)
            if not stale and stage < len(ROUTE):
                if stage == 2:
                    if t % FRAME_MS == 0:
                        frame = sample_camera(cam, t, bus)
                        if not report_sent and frame and frame["marker_pixels"] >= 40:
                            bus.append("observation_B3.jsonl", {
                                "report_id": f"B3-worksite-{t}", "sender": "B3", "destination": "ground_dispatch",
                                "kind": "marked_worksite_visible", "t_ms": t, "sample_t_ms": t,
                                "sent_at_ms": t, "image_signature": int(frame["rgb_sha256"][:8], 16),
                                "valid_until_ms": t + 6000, "marker_pixels": frame["marker_pixels"],
                                "camera_bytes": frame["camera_bytes"], "rgb_sha256": frame["rgb_sha256"],
                                "frame": frame["frame"],
                            })
                            report_sent = True
                    reached = t - arrived_at >= 2000
                    if reached and not report_sent:
                        event("report_missing")
                elif stage == 4:
                    reached = p[2] <= 0.070 and abs(v[2]) < 0.15
                    if reached:
                        speeds = [0.0] * 4
                else:
                    reached = math.dist(p, target) <= 0.22 and math.hypot(*v) <= 0.26
                if reached:
                    event(STAGES[stage])
                    arrived_at = t
                    stage += 1

        for motor, speed in zip(motors, speeds):
            motor.setVelocity(speed)
        bus.append("uav_telemetry.jsonl", {
            "t_ms": t, "mode": MODE, "target_enu": target, "estimate": estimate,
            "gps_sample": raw_gps, "position_age_ms": age, "position_hold": stale,
            "desired_rpy": desired, "motor_rad_s": speeds,
        })


if __name__ == "__main__":
    run()
