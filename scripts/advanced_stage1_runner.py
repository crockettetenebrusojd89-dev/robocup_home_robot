#!/usr/bin/env python3
"""Run P2-to-dining navigation, then wait for one selected visual target."""

import math
import sys
import time

from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from std_msgs.msg import Bool
from std_srvs.srv import SetBool

from advanced_dining_navigation import (
    DEFAULT_DINING_ENTRY_WAYPOINT,
    dining_entry_waypoint,
)


class AdvancedStage1Runner(Node):
    """Keep the Stage 1 handoff autonomous and independent of the base runner."""

    def __init__(self):
        super().__init__(
            'advanced_stage1_runner',
            parameter_overrides=[Parameter('use_sim_time', value=True)],
        )
        self.declare_parameter('dining_observation_x', 2.10)
        self.declare_parameter('dining_observation_y', 0.45)
        self.declare_parameter('dining_observation_yaw', math.pi / 2.0)
        self.declare_parameter('use_dining_entry_waypoint', True)
        self.declare_parameter(
            'dining_entry_x', DEFAULT_DINING_ENTRY_WAYPOINT[0]
        )
        self.declare_parameter(
            'dining_entry_y', DEFAULT_DINING_ENTRY_WAYPOINT[1]
        )
        self.declare_parameter(
            'dining_entry_yaw', DEFAULT_DINING_ENTRY_WAYPOINT[2]
        )
        self.declare_parameter('navigate_to_p2_first', False)
        self.declare_parameter('skip_dining_navigation', False)
        self.declare_parameter('p2_x', 0.265)
        self.declare_parameter('p2_y', -0.665)
        self.declare_parameter('p2_yaw', -2.638)
        self.declare_parameter('navigation_goal_accept_timeout_seconds', 20.0)
        self.declare_parameter('activation_service', '/advanced/enable_target_selection')
        self.declare_parameter('selected_topic', '/advanced/target_selected')
        self.declare_parameter('target_wait_seconds', 30.0)
        self.declare_parameter('post_selection_wait_seconds', 1.0)
        self._action_client = ActionClient(self, NavigateToPose, '/navigate_to_pose')
        self._activation_client = self.create_client(
            SetBool, str(self.get_parameter('activation_service').value)
        )
        self._target_selected = False
        self._last_feedback_log_time = {}
        self._latest_amcl_pose = None
        self.create_subscription(
            Bool,
            str(self.get_parameter('selected_topic').value),
            self._selected_callback,
            1,
        )
        self.create_subscription(
            PoseWithCovarianceStamped,
            '/amcl_pose',
            self._amcl_callback,
            10,
        )

    def _selected_callback(self, message):
        self._target_selected = message.data

    def _amcl_callback(self, message):
        self._latest_amcl_pose = message

    def _log_goal_error(self, label, x, y):
        """Record the latest localization estimate at a successful Nav2 leg."""
        if self._latest_amcl_pose is None:
            self.get_logger().warning(
                f'{label} succeeded, but no AMCL pose has arrived yet.'
            )
            return
        position = self._latest_amcl_pose.pose.pose.position
        error = math.hypot(position.x - x, position.y - y)
        self.get_logger().info(
            f'{label} latest AMCL: ({position.x:.3f}, {position.y:.3f}); '
            f'xy goal error={error:.3f} m.'
        )

    def _wait_for_action_server(self):
        self.get_logger().info('Waiting for NavigateToPose action server...')
        while rclpy.ok():
            if self._action_client.wait_for_server(timeout_sec=1.0):
                return True
        return False

    def _already_at_pose(self, label, x, y, yaw):
        deadline = time.monotonic() + 2.0
        while rclpy.ok() and self._latest_amcl_pose is None:
            if time.monotonic() >= deadline:
                return False
            rclpy.spin_once(self, timeout_sec=0.1)
        if self._latest_amcl_pose is None:
            return False
        pose = self._latest_amcl_pose.pose.pose
        xy_error = math.hypot(pose.position.x - x, pose.position.y - y)
        current_yaw = 2.0 * math.atan2(
            pose.orientation.z, pose.orientation.w
        )
        yaw_error = abs(math.atan2(
            math.sin(current_yaw - yaw), math.cos(current_yaw - yaw)
        ))
        if xy_error > 0.15 or yaw_error > 0.15:
            return False
        self.get_logger().info(
            f'Stage 1 {label} already satisfied by localization: '
            f'xy_error={xy_error:.3f} m yaw_error={yaw_error:.3f} rad; '
            'skipping zero-distance Nav2 goal.'
        )
        return True

    def _feedback_callback(self, label):
        """Log live distance without altering Nav2 control or recovery."""
        def callback(feedback_message):
            now = time.monotonic()
            if now - self._last_feedback_log_time.get(label, 0.0) < 1.0:
                return
            self._last_feedback_log_time[label] = now
            distance = feedback_message.feedback.distance_remaining
            self.get_logger().info(
                f'{label} feedback: distance_remaining={distance:.3f} m.'
            )
        return callback

    def _send_navigation_goal(self, label, x, y, yaw):
        if not all(math.isfinite(value) for value in (x, y, yaw)):
            self.get_logger().error(f'{label} pose must be finite.')
            return 1
        if self._already_at_pose(label, x, y, yaw):
            return 0
        if not self._wait_for_action_server():
            return 1
        # DDS can expose the action endpoints just before bt_navigator finishes
        # its lifecycle activation. Avoid sending into that short transition.
        rclpy.spin_once(self, timeout_sec=1.0)
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = 'map'
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x = x
        goal.pose.pose.position.y = y
        goal.pose.pose.orientation.z = math.sin(yaw / 2.0)
        goal.pose.pose.orientation.w = math.cos(yaw / 2.0)
        self.get_logger().info(
            f'Stage 1 navigation to {label}: ({x:.3f}, {y:.3f}, {yaw:.3f}).'
        )
        accept_timeout = float(
            self.get_parameter('navigation_goal_accept_timeout_seconds').value
        )
        if not math.isfinite(accept_timeout) or accept_timeout <= 0.0:
            self.get_logger().error(
                'navigation_goal_accept_timeout_seconds must be positive and finite.'
            )
            return 1
        deadline = time.monotonic() + accept_timeout
        handle = None
        while rclpy.ok() and time.monotonic() < deadline:
            send_future = self._action_client.send_goal_async(
                goal, feedback_callback=self._feedback_callback(label)
            )
            rclpy.spin_until_future_complete(self, send_future)
            if send_future.exception() is not None:
                self.get_logger().warning(
                    f'Could not send {label} goal yet: {send_future.exception()}'
                )
            else:
                handle = send_future.result()
                if handle is not None and handle.accepted:
                    break
                self.get_logger().info(
                    f'{label} navigation is not accepting goals yet; retrying.'
                )
            rclpy.spin_once(self, timeout_sec=0.5)
        if handle is None or not handle.accepted:
            self.get_logger().error(
                f'{label} navigation goal was not accepted within {accept_timeout:.1f} s.'
            )
            return 1
        self.get_logger().info(f'{label} navigation goal accepted.')
        result_future = handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future)
        if result_future.exception() is not None:
            self.get_logger().error(
                f'{label} navigation returned an exception: '
                f'{result_future.exception()}'
            )
            return 1
        result = result_future.result()
        if result is not None and result.status == GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().info(f'Stage 1 {label} navigation succeeded.')
            self._log_goal_error(label, x, y)
            return 0
        status = result.status if result is not None else GoalStatus.STATUS_UNKNOWN
        self.get_logger().error(f'Stage 1 {label} navigation failed. Status: {status}.')
        return 1

    def _enable_selector(self):
        self.get_logger().info('Waiting for advanced target selector service...')
        while rclpy.ok():
            if self._activation_client.wait_for_service(timeout_sec=1.0):
                break
        if not rclpy.ok():
            return False
        future = self._activation_client.call_async(SetBool.Request(data=True))
        rclpy.spin_until_future_complete(self, future)
        response = future.result()
        if response is None or not response.success:
            self.get_logger().error(
                f'Could not enable target selector: '
                f'{response.message if response else "no response"}'
            )
            return False
        self.get_logger().info(response.message)
        return True

    def run(self):
        if bool(self.get_parameter('navigate_to_p2_first').value):
            if self._send_navigation_goal(
                'frozen P2',
                float(self.get_parameter('p2_x').value),
                float(self.get_parameter('p2_y').value),
                float(self.get_parameter('p2_yaw').value),
            ) != 0:
                return 1
        skip_dining_navigation = bool(
            self.get_parameter('skip_dining_navigation').value
        )
        if bool(self.get_parameter('use_dining_entry_waypoint').value) and not (
            skip_dining_navigation
        ):
            try:
                entry_x, entry_y, entry_yaw = dining_entry_waypoint(
                    self.get_parameter('dining_entry_x').value,
                    self.get_parameter('dining_entry_y').value,
                    self.get_parameter('dining_entry_yaw').value,
                )
            except (TypeError, ValueError) as error:
                self.get_logger().error(str(error))
                return 1
            self.get_logger().info(
                'Advanced dining navigation:\n'
                'Leg 1: P2 \u2192 dining entry waypoint\n'
                'Leg 2: dining entry waypoint \u2192 observation pose'
            )
            if self._send_navigation_goal(
                'Leg 1 P2 to dining entry waypoint', entry_x, entry_y, entry_yaw
            ) != 0:
                return 1
            observation_label = 'Leg 2 dining entry waypoint to observation pose'
        else:
            observation_label = 'dining observation pose'
        if not skip_dining_navigation:
            if self._send_navigation_goal(
                observation_label,
                float(self.get_parameter('dining_observation_x').value),
                float(self.get_parameter('dining_observation_y').value),
                float(self.get_parameter('dining_observation_yaw').value),
            ) != 0:
                return 1
        else:
            self.get_logger().warning(
                'Focused test: using the supplied manipulation-area spawn '
                'instead of Stage 1 dining navigation.'
            )
        if not self._enable_selector():
            return 1
        timeout = float(self.get_parameter('target_wait_seconds').value)
        if not math.isfinite(timeout) or timeout <= 0.0:
            self.get_logger().error('target_wait_seconds must be positive and finite.')
            return 1
        self.get_logger().info('Dining target selection is active; waiting for one target.')
        deadline = time.monotonic() + timeout
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.2)
            if self._target_selected:
                post_selection_wait = float(
                    self.get_parameter('post_selection_wait_seconds').value
                )
                if math.isfinite(post_selection_wait) and post_selection_wait > 0.0:
                    deadline_after_selection = time.monotonic() + post_selection_wait
                    while rclpy.ok() and time.monotonic() < deadline_after_selection:
                        rclpy.spin_once(self, timeout_sec=0.1)
                self.get_logger().info('Advanced Task Stage 1 succeeded: target selected.')
                return 0
        self.get_logger().error('No valid dining target was selected before timeout.')
        return 1


def main():
    rclpy.init()
    node = None
    try:
        node = AdvancedStage1Runner()
        return node.run()
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        print(f'[advanced_stage1_runner] Failed: {error}', file=sys.stderr)
        return 1
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    sys.exit(main())
