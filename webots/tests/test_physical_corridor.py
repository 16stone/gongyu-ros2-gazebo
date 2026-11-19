import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
from physical_corridor import occupies_corridor, STAGING


class PhysicalCorridorTest(unittest.TestCase):
    def test_centre_crossing_old_release_line_does_not_clear_hull(self):
        self.assertTrue(occupies_corridor(4.9519, 0))
        self.assertTrue(occupies_corridor(2.0494, 0))
        self.assertTrue(occupies_corridor(5.2, 0))
        self.assertTrue(occupies_corridor(1.75, 0))

    def test_outer_hold_points_and_parking_bays_clear_corridor(self):
        for key in ("west_gate", "east_gate", "east_park", "west_park"):
            with self.subTest(key=key):
                self.assertFalse(occupies_corridor(*STAGING[key]))
        self.assertFalse(occupies_corridor(5.25, 0.95))
