import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
from b1_experiment import (CARD, drive, grid_search, grid_spec, ray_box,
                           wheel_predict, world_point)
from analyze_b1_experiment import scan_correct


class SingleVehicleExperiment(unittest.TestCase):
    def test_planners_have_equal_cost_and_avoid_inflation(self):
        for layout in ("open", "narrow"):
            free, start, goal = grid_spec(layout)
            dijkstra, d_cost, d_expanded = grid_search(free, start, goal, "dijkstra")
            astar, a_cost, a_expanded = grid_search(free, start, goal, "astar")
            self.assertAlmostEqual(d_cost, a_cost)
            self.assertLess(a_expanded, d_expanded)
            for path in (dijkstra, astar):
                self.assertEqual((path[0], path[-1]), (start, goal))
                for a, b in zip(path, path[1:]):
                    self.assertIn(b, free)
                    self.assertEqual(max(abs(a[0] - b[0]), abs(a[1] - b[1])), 1)
                    self.assertIn((a[0], b[1]), free)
                    self.assertIn((b[0], a[1]), free)
            self.assertEqual(tuple(world_point(start)), tuple(CARD["start"][:2]))
            self.assertEqual(tuple(world_point(goal)), tuple(CARD["goal"]))

    def test_scan_correction_of_lateral_and_yaw_offset(self):
        cloud = [(2.65 + i * 0.085 - 3.6 - 0.24, side * 0.55, 0)
                 for side in (-1, 1) for i in range(25)]
        (x, y, yaw), count = scan_correct((3.6, 0.08, 0.03), cloud)
        self.assertEqual(x, 3.6)
        self.assertGreater(count, 6)
        self.assertLess(abs(y), 0.02)
        self.assertLess(abs(yaw), 0.02)

    def test_geometry_and_right_side_encoder_sign(self):
        self.assertAlmostEqual(ray_box((0, 0), 0, (2, 3, -1, 1)), 2)
        self.assertIsNone(ray_box((0, 0), math.pi, (2, 3, -1, 1)))
        x, y, yaw = wheel_predict((0, 0, 0), 1, -1)
        self.assertAlmostEqual(x, 0)
        self.assertAlmostEqual(y, 0)
        self.assertAlmostEqual(yaw, 0.5)
        self.assertEqual(drive((0, 0, 0), (1, 0), True), (0.0, 0.0))
        self.assertGreater(drive((0, 0, 0), (1, 0), False)[0], 0.0)


if __name__ == "__main__":
    unittest.main()
