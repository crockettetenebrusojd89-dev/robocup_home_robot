#!/usr/bin/env python3
"""Evaluate an explicit one-to-three-point plan without object ground truth."""

from __future__ import annotations

import sys

from rclpy.parameter import Parameter
import rclpy

from formal_base_task_runner import FormalBaseTaskRunner
from go_to_living_room import GoToLivingRoom
from p2_viewpoint_plan import parse_observation_plan
from scan_living_room import ScanLivingRoom


class ContinueTrackingScan(ScanLivingRoom):
    """Use the verified scan action while keeping clusters from point one."""

    def _reset_visual_tracking(self):
        self.get_logger().info(
            "P2 evaluation: preserving visual tracking across observation points."
        )
        return True


class P2ViewpointTaskRunner(FormalBaseTaskRunner):
    """Navigate and scan an explicit seed-independent observation plan."""

    def __init__(self):
        super().__init__()
        self.declare_parameter("observation_plan_json")
        self.observation_plan = parse_observation_plan(
            str(self.get_parameter("observation_plan_json").value)
        )

    @staticmethod
    def _navigate(point):
        navigation = GoToLivingRoom()
        try:
            navigation.set_parameters([
                Parameter("living_room_x", value=point["x"]),
                Parameter("living_room_y", value=point["y"]),
                Parameter("living_room_yaw", value=point["yaw"]),
            ])
            return navigation.navigate()
        finally:
            navigation.destroy_node()

    @staticmethod
    def _scan(first_point):
        scan = ScanLivingRoom() if first_point else ContinueTrackingScan()
        try:
            return scan.scan()
        finally:
            scan.destroy_node()

    def run(self):
        """Evaluate every point serially and save one fused formal answer."""
        self.get_logger().info(
            "P2 viewpoint runner starting; "
            f"point_count={len(self.observation_plan)}; "
            f"targets={list(self.target_classes)}"
        )
        if not self._wait_for_navigation_active():
            return 1
        total = len(self.observation_plan)
        for index, point in enumerate(self.observation_plan, start=1):
            self.get_logger().info(
                f"Observation point {index}/{total}: "
                f"x={point['x']:.3f}, y={point['y']:.3f}, "
                f"yaw={point['yaw']:.3f}"
            )
            navigation_result = self._navigate(point)
            if navigation_result != 0:
                self.get_logger().error(
                    f"Observation point {index}/{total} navigation failed."
                )
                return navigation_result
            scan_result = self._scan(index == 1)
            if scan_result != 0:
                self.get_logger().error(
                    f"Observation point {index}/{total} scan failed."
                )
                return scan_result
        return self._save_answer()


def main():
    rclpy.init()
    node = None
    try:
        node = P2ViewpointTaskRunner()
        return node.run()
    except KeyboardInterrupt:
        if node is not None:
            node.get_logger().warning("P2 viewpoint evaluation interrupted.")
        return 130
    except Exception as error:
        print(f"[p2_viewpoint_task_runner] Failed: {error}", file=sys.stderr)
        return 1
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    sys.exit(main())
