import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
from adversary import IdleMonitor, ReplayAttacker, ResponseThreshold, sign_frame, verify_frame
from observation_gate import ObservationGate


class FrameAuthTest(unittest.TestCase):
    def test_sign_and_verify_detects_tampering(self):
        key = "blue-shared-secret"
        rec = {
            "t_ms": 12000,
            "actor": "B3",
            "camera_bytes": 76800,
            "image_signature": 495801,
            "sensor_pose": [14.0, 8.0],
        }
        signed = sign_frame(key, rec)
        self.assertTrue(verify_frame(key, signed))
        self.assertFalse(verify_frame("wrong-key", signed))
        self.assertFalse(verify_frame(key, rec))

        for field, bad_val in (
            ("t_ms", 240000),
            ("image_signature", 495802),
            ("camera_bytes", 100),
            ("actor", "R5"),
        ):
            tampered = dict(signed)
            tampered[field] = bad_val
            self.assertFalse(verify_frame(key, tampered), f"failed to reject tampered {field}")


class ResponseThresholdTest(unittest.TestCase):
    def test_threshold_scales_with_slack_and_resets_when_idle_stops(self):
        rule = ResponseThreshold(theta_min_s=1.0, theta_max_s=6.0, slack_ref_s=300.0, rate=1.0, seed=0)
        self.assertAlmostEqual(rule.threshold(300.0), 6.0)
        self.assertAlmostEqual(rule.threshold(0.0), 1.0)
        self.assertAlmostEqual(rule.threshold(150.0), 3.5)
        self.assertAlmostEqual(rule.probability(3.0, 3.0), 0.5)

        _, s1, _, p1 = rule.step(True, 150.0)
        _, s2, _, p2 = rule.step(True, 150.0)
        self.assertEqual((s1, s2), (1.0, 2.0))
        self.assertGreater(p2, p1)

        resp, s_reset, _, p_reset = rule.step(False, 150.0)
        self.assertFalse(resp)
        self.assertEqual(s_reset, 0.0)
        self.assertEqual(p_reset, 0.0)

    def test_persistent_demand_eventually_triggers(self):
        rule = ResponseThreshold(theta_min_s=1.0, theta_max_s=6.0, slack_ref_s=300.0, seed=42)
        triggered = False
        for _ in range(30):
            resp, _, _, _ = rule.step(True, 200.0)
            if resp:
                triggered = True
                break
        self.assertTrue(triggered)


class IdleMonitorTest(unittest.TestCase):
    def test_requires_full_window_and_detects_translation_or_rotation(self):
        mon = IdleMonitor(window_ms=2000, still_m=0.05, still_rad=0.05)
        mon.add(0, (5.6, -0.95), 0.0)
        mon.add(1000, (5.6, -0.95), 0.0)
        self.assertFalse(mon.idle())

        mon.add(2000, (5.6, -0.95), 0.0)
        self.assertTrue(mon.idle())

        # Slight rotation breaks idle even with zero translation
        mon.add(2500, (5.6, -0.95), 0.12)
        self.assertFalse(mon.idle())

        # Translation breaks idle
        mon.reset()
        mon.add(3000, (5.6, -0.95), 0.0)
        mon.add(5000, (5.7, -0.95), 0.0)
        self.assertFalse(mon.idle())


class ReplayAttackerTest(unittest.TestCase):
    def test_intercept_range_age_and_forged_mac_invalidation(self):
        key = "blue-key"
        atk = ReplayAttacker(intercept_range_m=8.0, inject_range_m=10.0, min_age_ms=20000)

        far_frame = sign_frame(key, {"t_ms": 5000, "actor": "B3", "camera_bytes": 100,
                                     "image_signature": 11, "sensor_pose": [0.0, 0.0]})
        self.assertFalse(atk.observe((12.0, 5.0), far_frame))

        near_frame = sign_frame(key, {"t_ms": 10000, "actor": "B3", "camera_bytes": 100,
                                      "image_signature": 22, "sensor_pose": [14.0, 8.0]})
        self.assertTrue(atk.observe((12.0, 5.0), near_frame))
        # Duplicate timestamp ignored
        self.assertFalse(atk.observe((12.0, 5.0), near_frame))

        req = {"t_ms": 25000, "request_id": "req-1"}
        # Too young (< 20000 ms age)
        self.assertIsNone(atk.forge(25000, (12.0, 5.0), req, (8.0, 1.6)))
        # Out of injection range
        self.assertIsNone(atk.forge(35000, (25.0, 5.0), req, (8.0, 1.6)))

        res = atk.forge(35000, (12.0, 5.0), req, (8.0, 1.6))
        self.assertIsNotNone(res)
        forged, original = res
        self.assertEqual(original["t_ms"], 10000)
        self.assertEqual(forged["t_ms"], 35000)
        self.assertFalse(verify_frame(key, forged))
        # Same request_id is not forged twice
        self.assertIsNone(atk.forge(35100, (12.0, 5.0), req, (8.0, 1.6)))


class GateVerifierTest(unittest.TestCase):
    def test_gate_rejects_replayed_frame_then_accepts_signed_frame(self):
        key = "blue-key"
        gate = ObservationGate(6000, 1000, verifier=lambda rec: verify_frame(key, rec))
        self.assertEqual(gate.step(240000, None)[0], "observation_requested")

        # Forged replay arrives with fresh timestamp but old MAC
        old = sign_frame(key, {"t_ms": 10000, "actor": "B3", "camera_bytes": 76800,
                               "image_signature": 495801, "sensor_pose": [14.0, 8.0]})
        forged = dict(old, t_ms=240016)
        ev1 = gate.step(240032, forged)
        self.assertEqual(ev1[0], "observation_unauthenticated")
        self.assertFalse(gate.authorized)
        # Same forged frame on the next tick is silently ignored (no log spam)
        self.assertIsNone(gate.step(240048, forged))

        # Genuine signed frame from B3 queues and authorizes
        genuine = sign_frame(key, {"t_ms": 240500, "actor": "B3", "camera_bytes": 76800,
                                   "image_signature": 512000, "sensor_pose": [14.0, 8.0]})
        ev2 = gate.step(240520, genuine)
        self.assertEqual(ev2[0], "observation_queued")
        self.assertEqual(gate.step(241520, None)[0], "observation_authorized")
        self.assertTrue(gate.authorized)


if __name__ == "__main__":
    unittest.main()
