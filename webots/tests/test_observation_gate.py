import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
from observation_gate import ObservationGate


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
