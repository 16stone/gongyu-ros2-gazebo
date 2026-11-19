"""Recompute the Phase C gates from raw controller, referee and camera records."""
import hashlib
import json
from math import atan2, cos, dist, pi, sin, sqrt
from pathlib import Path
import sys


def verify(run):
    def rows(name):
        return [json.loads(line) for line in (run / "bus" / f"{name}.jsonl").read_text().splitlines()]

    config = json.loads((run / "uav_config.json").read_text())
    telemetry = rows("uav_telemetry")
    events = rows("uav_events")
    truth = {row["t_ms"]: row for row in rows("uav_truth")}
    frames = rows("uav_frames")
    report_path = run / "bus" / "observation_B3.jsonl"
    reports = rows("observation_B3") if report_path.exists() else []
    by_event = {row["kind"]: row for row in events}
    stages = ["takeoff_reached", "waypoint_reached", "hover_complete", "home_reached", "landed"]
    missing = [stage for stage in stages if stage not in by_event]
    if missing:
        raise ValueError(f"Mission milestones missing: {missing}")
    stages_ms = {stage: by_event[stage]["t_ms"] for stage in stages}
    assert list(stages_ms.values()) == sorted(set(stages_ms.values()))
    assert len(truth) == 1750 and max(truth) == 28000 and stages_ms["landed"] < 28000
    assert set(row["mode"] for row in telemetry) == {config["mode"]}
    assert set(row["t_ms"] for row in telemetry) <= set(truth)
    assert any(any(abs(w) > 150 for w in row["motor_rad_s"]) for row in telemetry)
    assert max(row["p"][2] for row in truth.values()) > 1.6
    waypoint = (2.2, 0.8, 1.9)
    assert dist(truth[stages_ms["takeoff_reached"]]["p"], (0, 0, 1.9)) <= 0.28
    assert dist(truth[stages_ms["waypoint_reached"]]["p"], waypoint) <= 0.28
    assert dist(truth[stages_ms["home_reached"]]["p"], (0, 0, 1.9)) <= 0.28
    assert dist(truth[stages_ms["landed"]]["p"], (0, 0, 0.05)) <= 0.20
    assert not any(row["non_floor_contacts"] for row in truth.values())
    assert any(row["floor_contacts"] for t, row in truth.items() if t >= stages_ms["landed"])

    hover = [r for t, r in truth.items() if stages_ms["waypoint_reached"] <= t <= stages_ms["hover_complete"]]
    hover_errors = [dist(r["p"], waypoint) for r in hover]
    assert len(hover) >= 126 and max(hover_errors) <= 0.30
    assert max(abs(r["rpy"][2]) for r in hover) <= 0.15
    assert len(frames) >= 5 and all(frame["camera_bytes"] == 96 * 72 * 4 for frame in frames)
    for frame in frames:
        assert frame["t_ms"] % 160 == 0
        rgb = (run / "evidence" / frame["frame"]).read_bytes().split(b"\n", 3)
        assert rgb[:3] == [b"P6", b"96 72", b"255"] and len(rgb[3]) == 96 * 72 * 3
        assert hashlib.sha256(rgb[3]).hexdigest() == frame["rgb_sha256"]
        pixels = sum(r >= 100 and b >= 100 and min(r, b) - g >= 50
                     for r, g, b in zip(rgb[3][::3], rgb[3][1::3], rgb[3][2::3]))
        assert pixels == frame["marker_pixels"]
    if config["occluded"]:
        assert not reports and "report_missing" in by_event
        assert max(frame["marker_pixels"] for frame in frames) < 40
    else:
        assert len(reports) == 1 and "report_missing" not in by_event
        report = reports[0]
        frame = next(item for item in frames if item["t_ms"] == report["sample_t_ms"])
        assert report["sender"] == "B3" and report["destination"] == "ground_dispatch"
        assert frame["rgb_sha256"] == report["rgb_sha256"] and frame["marker_pixels"] >= 40
        assert stages_ms["waypoint_reached"] <= report["sample_t_ms"] <= report["sent_at_ms"] < stages_ms["hover_complete"]
        assert report["valid_until_ms"] - report["sample_t_ms"] == 6000
    if config["gps_dropout"]:
        lost = by_event["position_stale"]["t_ms"]
        found = by_event["position_recovered"]["t_ms"]
        assert 4512 <= lost < found <= 5200
        held = [r for r in telemetry if lost <= r["t_ms"] < found]
        assert held and all(r["position_hold"] and r["desired_rpy"] == [0.0, 0.0, 0.0]
                            and r["position_age_ms"] > 96 for r in held)
        assert not any(lost <= row["t_ms"] < found for row in frames + [by_event[stage] for stage in stages])
    else:
        assert "position_stale" not in by_event
    aligned = [(row, truth[row["t_ms"]]) for row in telemetry
               if row["estimate"] is not None and not row["position_hold"]]
    assert aligned
    errors = [dist(row["estimate"]["p"], actual["p"]) for row, actual in aligned]
    yaw_error = [row["estimate"]["rpy"][2] - actual["rpy"][2] for row, actual in aligned]
    gps_errors = [dist(row["gps_sample"]["p"], actual["p"]) for row, actual in aligned
                  if row["gps_sample"] is not None]

    def rms(items):
        return sqrt(sum(value ** 2 for value in items) / len(items))

    return {
        "on_time": 5, "total": 5, "full_window": max(truth) >= 28000,
        "violation_count": 0, "flight_events_ms": stages_ms,
        "gps_position_rmse_m": rms(gps_errors) if gps_errors else None,
        "positions_compared": len(aligned), "position_rmse_m": rms(errors),
        "yaw_rmse_rad": rms([atan2(sin(delta), cos(delta)) for delta in yaw_error]),
        "hover_samples": len(hover), "hover_rms_from_waypoint_m": rms(hover_errors),
        "hover_max_from_waypoint_m": max(hover_errors), "max_altitude_m": max(row["p"][2] for row in truth.values()),
        "hover_speed_rms_m_s": rms([dist(row["v"], (0, 0, 0)) for row in hover]),
        "hover_max_abs_yaw_deg": max(abs(r["rpy"][2]) for r in hover) * 180 / pi,
        "non_floor_contact_samples": 0, "frame_count": len(frames),
        "marker_pixel_count_range": [min(row["marker_pixels"] for row in frames), max(row["marker_pixels"] for row in frames)],
        "reports": len(reports), "report_sample_ms": reports[0]["sample_t_ms"] if reports else None,
        "position_hold_ms": [by_event[key]["t_ms"] for key in ("position_stale", "position_recovered")]
        if config["gps_dropout"] else None,
    }


if __name__ == "__main__":
    print(json.dumps(verify(Path(sys.argv[1])), indent=2))
