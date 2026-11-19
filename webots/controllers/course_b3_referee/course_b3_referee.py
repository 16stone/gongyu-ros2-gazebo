"""Record independent simulated motion and contacts for the one-UAV experiment."""
import json
from math import asin, atan2
import os
from pathlib import Path
import sys

from controller import Supervisor

sys.path.insert(0, os.environ["GONGYU_WEBOTS_COMMON"])
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from bus import Bus
from check_uav_course import verify

run = Path(os.environ["GONGYU_RUN_DIR"])
mode = os.environ.get("GONGYU_FEEDBACK_MODE", "sensor")
occluded = os.environ.get("GONGYU_UAV_OCCLUDED", "0") == "1"
dropout = os.environ.get("GONGYU_UAV_DROPOUT", "0") == "1"
(run / "uav_config.json").write_text(json.dumps({
    "mode": mode, "occluded": occluded, "gps_dropout": dropout,
    "coordinate_system": "ENU", "seed": 19, "gps_period_ms": 32,
    "gps_accuracy_m": 0.006, "gps_vector_speed_noise_m_s": 0.0,
    "imu_period_ms": 16, "imu_noise": 0.001, "gyro_period_ms": 16,
    "gyro_resolution_rad_s": 0.001, "constant_sensor_bias": 0,
    "camera_period_ms": 160, "camera_rgb_noise": 0,
}, indent=2))
bus = Bus(run / "bus")
supervisor = Supervisor()
dt = int(supervisor.getBasicTimeStep())
drone = supervisor.getFromDef("B3")

if occluded:
    supervisor.getFromDef("COVER").getField("translation").setSFVec3f([2.2, 0.8, 0.32])
emitter = supervisor.getDevice("reference emitter")
while supervisor.step(dt) != -1:
    t = round(supervisor.getTime() * 1000)
    r = drone.getOrientation()
    vel = drone.getVelocity()
    contacts = drone.getContactPoints(True)
    # The reported ID may be B3 itself. Only the floor surface intersects this z band.
    contact_points = [list(point.getPoint()) for point in contacts]
    support = sum(-0.02 <= z <= 0.012 and -5 <= x <= 7 and -5 <= y <= 5
                  for x, y, z in contact_points)
    packet = {
        "t_ms": t, "p": drone.getPosition(), "v": vel[:3],
        "rpy": [atan2(r[7], r[8]), asin(max(-1, min(1, -r[6]))), atan2(r[3], r[0])],
        "body_omega": [sum(r[3 * row + col] * vel[3 + row] for row in range(3)) for col in range(3)],
    }
    bus.append("uav_truth.jsonl", {
        **packet, "floor_contacts": support, "non_floor_contacts": len(contact_points) - support,
        "contact_points_enu": contact_points,
    })
    if mode == "truth":
        emitter.send(json.dumps(packet).encode())
    if t >= 28000:
        break

# Advance a final tick so the controller has finished writing the previous tick.
supervisor.step(dt)
try:
    metrics = verify(run)
except (AssertionError, KeyError, StopIteration, ValueError, OSError):
    import traceback
    (run / "shutdown.json").write_text(json.dumps({"status": "FAILED", "t_ms": t}))
    with (run / "controller_error.log").open("w") as log:
        traceback.print_exc(file=log)
    supervisor.simulationQuit(4)
else:
    (run / "result" / "metrics.json").write_text(json.dumps(metrics, indent=2))
    (run / "shutdown.json").write_text(json.dumps({"status": "COMPLETE", "t_ms": t}))
    supervisor.simulationQuit(0)
