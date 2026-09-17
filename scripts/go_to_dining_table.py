#!/usr/bin/env python3
"""Send the fixed dining observation goal to the existing Nav2 stack once."""

import math
import sys
import time

from action_msgs.msg import GoalStatus
from nav2_msgs.action import NavigateToPose
import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.parameter import Parameter


ACTION_SERVER = '/navigate_to_pose'
FEEDBACK_PERIOD = 1.0


class GoToDiningTable(Node):
    """Navigate from the completed base task to one map-frame dining pose."""

    def __init__(self):
        super().__init__(
            'go_to_dining_table',
            parameter_overrides=[Parameter('use_sim_time', value=True)],
        )
        # South of the combined 2.4 m by 1.0 m dining-table region in the
        # packaged example world.  The camera and future arm face north.
        self.declare_parameter('dining_observation_x', 2.10)
        self.declare_parameter('dining_observation_y', 0.45)
        self.declare_parameter('dining_observation_yaw', math.pi / 2.0)
        self._action_client = ActionClient(self, NavigateToPose, ACTION_SERVER)
        self._last_feedback_time = None

    def _wait_for_server(self):
        self.get_logger().info('Waiting for NavigateToPose action server...')
        attempts = 0
        while rclpy.ok():
            if self._action_client.wait_for_server(timeout_sec=1.0):
                self.get_logger().info('NavigateToPose action server ready.')
                return True
            attempts += 1
            if attempts % 5 == 0:
                self.get_logger().info(
                    'Still waiting for NavigateToPose action server...'
                )
        return False

    def _feedback_callback(self, feedback_message):
        now = time.monotonic()
        if (
            self._last_feedback_time is None
            or now - self._last_feedback_time >= FEEDBACK_PERIOD
        ):
            self.get_logger().info(
                f'Distance remaining: '
                f'{feedback_message.feedback.distance_remaining:.2f} m'
            )
            self._last_feedback_time = now

    def navigate(self):
        if not self._wait_for_server():
            self.get_logger().error(
                'ROS shutdown before NavigateToPose action server became ready.'
            )
            return 1

        target_x = float(self.get_parameter('dining_observation_x').value)
        target_y = float(self.get_parameter('dining_observation_y').value)
        target_yaw = float(self.get_parameter('dining_observation_yaw').value)
        if not all(math.isfinite(value) for value in (target_x, target_y, target_yaw)):
            self.get_logger().error('Dining observation pose must be finite.')
            return 1

        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = 'map'
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x = target_x
        goal.pose.pose.position.y = target_y
        goal.pose.pose.orientation.z = math.sin(target_yaw / 2.0)
        goal.pose.pose.orientation.w = math.cos(target_yaw / 2.0)
        self.get_logger().info(
            'Dining observation target:\n'
            f'x = {target_x:.3f}\n'
            f'y = {target_y:.3f}\n'
            f'yaw = {target_yaw:.3f}'
        )

        send_goal_future = self._action_client.send_goal_async(
            goal, feedback_callback=self._feedback_callback
        )
        rclpy.spin_until_future_complete(self, send_goal_future)
        if not send_goal_future.done() or send_goal_future.exception() is not None:
            self.get_logger().error(
                f'Failed to send dining goal: {send_goal_future.exception()}'
            )
            return 1
        goal_handle = send_goal_future.result()
        if goal_handle is None or not goal_handle.accepted:
            self.get_logger().error('Dining navigation goal was rejected.')
            return 1

        self.get_logger().info('Goal accepted: navigating to dining observation pose.')
        result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future)
        if not result_future.done() or result_future.exception() is not None:
            self.get_logger().error(
                f'Failed while waiting for dining navigation: '
                f'{result_future.exception()}'
            )
            return 1
        result = result_future.result()
        if result is not None and result.status == GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().info('Dining observation navigation succeeded.')
            return 0
        status = result.status if result is not None else GoalStatus.STATUS_UNKNOWN
        self.get_logger().error(f'Dining navigation failed. Status: {status}.')
        return 1


def main():
    rclpy.init()
    node = GoToDiningTable()
    try:
        return node.navigate()
    except KeyboardInterrupt:
        node.get_logger().warning('Dining navigation interrupted by user.')
        return 130
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    sys.exit(main())
