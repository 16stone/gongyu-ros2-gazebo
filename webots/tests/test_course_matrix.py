import sys
import unittest
from math import dist
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
from course_matrix import EXIT_STAGING, LONG_ROUTE, STARTS, choose_support, dispatch_due


from physical_corridor import occupies_corridor


class CourseMatrixTest(unittest.TestCase):
    def test_long_bypass_has_frozen_28_m_length(self):
        points = (STARTS["web_long"]["R1"], *LONG_ROUTE)
        self.assertAlmostEqual(sum(dist(a, b) for a, b in zip(points, points[1:])), 28)

    def test_release_rule_never_authorizes_an_occupied_lane(self):
        self.assertFalse(dispatch_due(40000, True, False))
        self.assertFalse(dispatch_due(8000, False, True))
        self.assertTrue(dispatch_due(8000, True, True))
        self.assertTrue(dispatch_due(32000, False, True))

    def test_exit_staging_is_clear_of_the_corridor(self):
        west, east = EXIT_STAGING
        self.assertLess(west[0], east[0])
        self.assertFalse(occupies_corridor(*west))
        self.assertFalse(occupies_corridor(*east))

    def test_destination_blocking_keeps_the_channel_idle(self):
        self.assertFalse(dispatch_due(40000, True, True, destination_clear=False))
        self.assertTrue(dispatch_due(40000, True, True, destination_clear=True))

    def test_cost_deadline_changes_the_executing_vehicle(self):
        low = choose_support(50000)
        high = choose_support(23000)
        self.assertEqual((low["carrier"], high["carrier"]), ("B2", "B1"))
        self.assertGreater(low["extra_work_ms"], 0)
        self.assertGreater(low["delivery_gain_ms"], low["extra_work_ms"])
        self.assertLessEqual(high["direct_return_ms"], 23000)
        self.assertGreater(high["support_return_ms"], 23000)
