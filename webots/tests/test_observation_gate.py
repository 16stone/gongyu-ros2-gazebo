import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
from observation_gate import ObservationGate, ObservationLink


class ObservationGateTest(unittest.TestCase):
    def test_fresh_frame_permits_dispatch(self):
        gate = ObservationGate(6000, 1000)
        self.assertEqual(gate.step(100, None)[0], "observation_requested")
        self.assertEqual(gate.step(120, {"t_ms": 119, "camera_bytes": 1})[0],
                         "observation_queued")
        self.assertIsNone(gate.step(1119, None))
        self.assertEqual(gate.step(1120, None)[0], "observation_authorized")
        self.assertTrue(gate.authorized)

    def test_late_frame_requests_a_new_sample_and_keeps_dispatch_blocked(self):
        gate = ObservationGate(6000, 7300)
        gate.step(0, None)
        self.assertIsNone(gate.step(10, {"t_ms": 10, "camera_bytes": 0}))
        gate.step(20, {"t_ms": 20, "camera_bytes": 1})
        self.assertEqual(gate.step(7320, None)[0], "observation_expired")
        self.assertFalse(gate.authorized)
        self.assertIsNone(gate.step(7330, {"t_ms": 20, "camera_bytes": 1}))
        self.assertEqual(gate.step(7360, {"t_ms": 7340, "camera_bytes": 1})[0],
                         "observation_queued")
        self.assertEqual(gate.step(8360, None)[0], "observation_authorized")
        self.assertTrue(gate.authorized)

    def test_expiry_without_refresh_stays_blocked(self):
        gate = ObservationGate(6000, 7300, retry_on_expiry=False)
        gate.step(0, None)
        gate.step(20, {"t_ms": 20, "camera_bytes": 1})
        event, payload = gate.step(7320, None)
        self.assertEqual(event, "observation_expired")
        self.assertNotIn("refresh_requested_at", payload)
        self.assertIsNone(gate.step(8320, {"t_ms": 8320, "camera_bytes": 1}))
        self.assertEqual(gate.attempts, 1)
        self.assertFalse(gate.authorized)

    def test_lost_frame_waits_for_timeout_then_retries_fresh_sample(self):
        gate = ObservationGate(6000, 1000, link=ObservationLink(loss_rate=0.25, seed=1))
        gate.step(0, None)
        gate.step(20, {"t_ms": 20, "camera_bytes": 1})
        kind, loss = gate.step(1020, None)
        self.assertEqual((kind, loss["transport_failure"]),
                         ("observation_transport_dropped", "random_loss"))
        self.assertFalse(gate.authorized)
        self.assertIsNone(gate.step(6019, None))
        self.assertEqual(gate.step(6020, None)[0], "observation_timeout")
        self.assertIsNone(gate.step(6030, {"t_ms": 20, "camera_bytes": 1}))
        gate.step(6040, {"t_ms": 6040, "camera_bytes": 1})
        self.assertEqual(gate.step(7040, None)[0], "observation_authorized")

    def test_persistent_blackout_does_not_release_the_waiting_vehicle(self):
        gate = ObservationGate(6000, 1000, link=ObservationLink(blackout=(0, 400001)))
        gate.step(0, None)
        for sampled in (20, 6040, 12060):
            gate.step(sampled, {"t_ms": sampled, "camera_bytes": 1})
            kind, payload = gate.step(sampled + 1000, None)
            self.assertEqual((kind, payload["transport_failure"]),
                             ("observation_transport_dropped", "blackout"))
            self.assertEqual(gate.step(sampled + 6000, None)[0], "observation_timeout")
        self.assertFalse(gate.authorized)
