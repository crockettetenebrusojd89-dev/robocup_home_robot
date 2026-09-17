#!/usr/bin/env python3
"""Focused checks for the Stage 1 target acceptance boundary."""

import unittest

from advanced_target_selection import detection_candidate


class Value:
    """Tiny attribute container so quality checks stay ROS-independent."""

    def __init__(self, **attributes):
        self.__dict__.update(attributes)


def make_detection(
    class_name='apple', confidence=0.91, center_x=320.0, center_y=240.0,
    width=100.0, height=80.0, depth=1.10,
):
    """Construct one localized 2-D detection without invoking YOLO."""
    return Value(
        bbox=Value(
            center=Value(position=Value(x=center_x, y=center_y)),
            size_x=width,
            size_y=height,
        ),
        results=[
            Value(
                hypothesis=Value(class_id=class_name, score=confidence),
                pose=Value(pose=Value(position=Value(x=0.0, y=0.0, z=depth))),
            )
        ],
    )


class AdvancedTargetSelectorTest(unittest.TestCase):
    """Keep invalid depth and edge boxes out of automatic target selection."""

    def test_valid_localized_detection_is_retained(self):
        candidate = detection_candidate(
            make_detection(), 640, 480, edge_margin_pixels=12.0
        )
        self.assertEqual(candidate['class_name'], 'apple')
        self.assertAlmostEqual(candidate['confidence'], 0.91)
        self.assertAlmostEqual(candidate['point'].z, 1.10)

    def test_edge_box_and_invalid_depth_are_rejected(self):
        self.assertIsNone(
            detection_candidate(
                make_detection(center_x=30.0), 640, 480, edge_margin_pixels=12.0
            )
        )
        self.assertIsNone(
            detection_candidate(
                make_detection(depth=0.0), 640, 480, edge_margin_pixels=12.0
            )
        )


if __name__ == '__main__':
    unittest.main()
