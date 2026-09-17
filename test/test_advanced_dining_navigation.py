#!/usr/bin/env python3
"""Focused guards for the isolated dining-entry waypoint."""

import math
import unittest

from advanced_dining_navigation import (
    DEFAULT_DINING_ENTRY_WAYPOINT,
    dining_entry_waypoint,
)


class AdvancedDiningNavigationTest(unittest.TestCase):
    def test_default_entry_waypoint_is_finite_and_not_the_observation_pose(self):
        waypoint = dining_entry_waypoint(*DEFAULT_DINING_ENTRY_WAYPOINT)
        self.assertTrue(all(math.isfinite(value) for value in waypoint))
        self.assertNotEqual(waypoint[:2], (2.10, 0.45))

    def test_non_finite_entry_waypoint_is_rejected(self):
        with self.assertRaises(ValueError):
            dining_entry_waypoint(float('nan'), 0.25, math.pi / 2.0)


if __name__ == '__main__':
    unittest.main()
