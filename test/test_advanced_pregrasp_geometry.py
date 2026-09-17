#!/usr/bin/env python3

import unittest

from advanced_pregrasp_geometry import (
    manipulation_pose,
    manipulation_route,
    nearest_dining_table,
    pregrasp_position,
    within_arm_workspace,
)


class AdvancedPregraspGeometryTest(unittest.TestCase):
    def test_target_to_pregrasp_and_table(self):
        self.assertEqual(
            nearest_dining_table((1.507, 1.758, 0.677))[0],
            'dinning_table_1',
        )
        x, y, yaw = manipulation_pose((1.507, 1.758, 0.677))
        self.assertAlmostEqual(x, 1.507)
        self.assertAlmostEqual(y, 2.70)
        self.assertAlmostEqual(yaw, 2.119345729245138)
        self.assertEqual(pregrasp_position((0.65, 0.055, 0.677)), (0.65, 0.055, 0.857))

    def test_north_table_target_uses_open_cluster_edge(self):
        x, y, yaw = manipulation_pose((2.160, 1.968, 0.679))
        self.assertAlmostEqual(x, 2.160)
        self.assertAlmostEqual(y, 2.70)
        self.assertAlmostEqual(yaw, 2.119345729245138)

    def test_current_base_still_prefers_stronger_arm_margin(self):
        x, y, yaw = manipulation_pose(
            (1.854, 1.898, 0.677), current_base=(2.10, 0.45)
        )
        self.assertAlmostEqual(x, 1.854)
        self.assertAlmostEqual(y, 2.70)
        self.assertAlmostEqual(yaw, 2.119345729245138)

    def test_route_stays_outside_table_cluster(self):
        route = manipulation_route(
            (2.10, 0.45), (1.854, 2.55, 2.119345729245138)
        )
        self.assertEqual(len(route), 3)
        self.assertAlmostEqual(route[0][0], 0.55)
        self.assertAlmostEqual(route[0][1], 0.90)
        self.assertAlmostEqual(route[1][0], 0.55)
        self.assertAlmostEqual(route[1][1], 2.60)

    def test_invalid_and_unreachable_target(self):
        with self.assertRaises(ValueError):
            pregrasp_position((float('nan'), 0.0, 0.7))
        with self.assertRaises(ValueError):
            pregrasp_position((0.6, 0.0, 0.2))
        reachable, distance = within_arm_workspace(
            (1.338, 0.371, 0.677), (-0.09, 0.055, 0.425)
        )
        self.assertFalse(reachable)
        self.assertGreater(distance, 1.4)


if __name__ == '__main__':
    unittest.main()
