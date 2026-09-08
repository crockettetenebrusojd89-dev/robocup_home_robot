#!/usr/bin/env python3
"""Send the calibrated living-room goal to the existing Nav2 stack once."""

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


class GoToLivingRoom(Node):
    """Send one configurable map-frame goal and report its outcome."""

    def __init__(self):
        super().__init__(
            'go_to_living_room',
            parameter_overrides=[Parameter('use_sim_time', value=True)],
            automatically_declare_parameters_from_overrides=True,
        )
        self.declare_parameter('living_room_x', -2.393)
        self.declare_parameter('living_room_y', -0.882)
        self.declare_parameter('living_room_yaw', 0.724)
        self._action_client = ActionClient(
            self,
            NavigateToPose,
            ACTION_SERVER,
        )
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
            distance = feedback_message.feedback.distance_remaining
            self.get_logger().info(f'Distance remaining: {distance:.2f} m')
            self._last_feedback_time = now

    def navigate(self):
        if not self._wait_for_server():
            self.get_logger().error(
                'ROS shutdown before NavigateToPose action server became ready.'
            )
            return 1

        target_x = self.get_parameter('living_room_x').value
        target_y = self.get_parameter('living_room_y').value
        target_yaw = self.get_parameter('living_room_yaw').value

        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = 'map'
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x = target_x
        goal.pose.pose.position.y = target_y
        goal.pose.pose.position.z = 0.0
        goal.pose.pose.orientation.x = 0.0
        goal.pose.pose.orientation.y = 0.0
        goal.pose.pose.orientation.z = math.sin(target_yaw / 2.0)
        goal.pose.pose.orientation.w = math.cos(target_yaw / 2.0)

        self.get_logger().info(
            'Living room target:\n'
            f'x = {target_x:.3f}\n'
            f'y = {target_y:.3f}\n'
            f'yaw = {target_yaw:.3f}'
        )

        send_goal_future = self._action_client.send_goal_async(
            goal,
            feedback_callback=self._feedback_callback,
        )
        rclpy.spin_until_future_complete(self, send_goal_future)
        if not send_goal_future.done():
            self.get_logger().error('Stopped before the navigation goal was sent.')
            return 1
        if send_goal_future.exception() is not None:
            self.get_logger().error(
                f'Failed to send living room goal: {send_goal_future.exception()}'
            )
            return 1

        goal_handle = send_goal_future.result()
        if goal_handle is None or not goal_handle.accepted:
            self.get_logger().error('Living room navigation goal was rejected.')
            return 1

        self.get_logger().info('Goal accepted: navigating to living room.')
        result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future)
        if not result_future.done():
            self.get_logger().error('Stopped before navigation returned a result.')
            return 1
        if result_future.exception() is not None:
            self.get_logger().error(
                f'Failed while waiting for navigation result: '
                f'{result_future.exception()}'
            )
            return 1

        wrapped_result = result_future.result()
        if wrapped_result is None:
            self.get_logger().error('Navigation ended without an action result.')
            return 1

        status = wrapped_result.status
        if status == GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().info('Living room navigation succeeded.')
            return 0
        if status == GoalStatus.STATUS_CANCELED:
            self.get_logger().warning('Living room navigation canceled.')
            return 2

        status_name = {
            GoalStatus.STATUS_UNKNOWN: 'UNKNOWN',
            GoalStatus.STATUS_ACCEPTED: 'ACCEPTED',
            GoalStatus.STATUS_EXECUTING: 'EXECUTING',
            GoalStatus.STATUS_CANCELING: 'CANCELING',
            GoalStatus.STATUS_ABORTED: 'ABORTED',
        }.get(status, 'UNRECOGNIZED')
        self.get_logger().error(
            f'Living room navigation failed. Status: {status_name} ({status}).'
        )
        return 1


def main():
    rclpy.init()
    node = GoToLivingRoom()
    try:
        return node.navigate()
    except KeyboardInterrupt:
        node.get_logger().warning('Living room navigation interrupted by user.')
        return 130
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    sys.exit(main())
