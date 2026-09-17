#!/usr/bin/env python3
"""Convert the Stage 1 target to map and make one Advanced-only base approach."""

import math
import sys
import time

from action_msgs.msg import GoalStatus
from advanced_pregrasp_geometry import (
    manipulation_pose,
    manipulation_route,
    nearest_dining_table,
)
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.duration import Duration
import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from rcl_interfaces.srv import SetParameters
from std_msgs.msg import String
from tf2_geometry_msgs import do_transform_pose_stamped
from tf2_ros import Buffer, TransformException, TransformListener


class AdvancedStage2AApproach(Node):
    """Preserve Stage 1 observation, then move only as far as manipulation needs."""

    def __init__(self):
        super().__init__(
            'advanced_stage2a_approach',
            parameter_overrides=[Parameter('use_sim_time', value=True)],
        )
        self.declare_parameter('table_clearance_m', 0.45)
        self.declare_parameter('target_timeout_seconds', 180.0)
        self.declare_parameter('navigation_timeout_seconds', 150.0)
        self.declare_parameter('navigation_attempts', 2)
        self.declare_parameter('xy_goal_tolerance_m', 0.15)
        self.declare_parameter('yaw_goal_tolerance_rad', 0.08)
        self._target_map = None
        self._target_class = ''
        self._tf_buffer = Buffer(cache_time=Duration(seconds=30.0), node=self)
        self._tf_listener = TransformListener(self._tf_buffer, self)
        self._nav = ActionClient(self, NavigateToPose, '/navigate_to_pose')
        self._controller_parameters = self.create_client(
            SetParameters, '/controller_server/set_parameters'
        )
        self.create_subscription(
            String, '/advanced/grasp_target_class', self._class_callback, 1
        )
        self.create_subscription(
            PoseStamped,
            '/advanced/grasp_target_base_link',
            self._target_callback,
            1,
        )
        latched = QoSProfile(depth=1)
        latched.reliability = ReliabilityPolicy.RELIABLE
        latched.durability = DurabilityPolicy.TRANSIENT_LOCAL
        self._map_target_publisher = self.create_publisher(
            PoseStamped, '/advanced/stage2a_target_map', latched
        )
        self._class_publisher = self.create_publisher(
            String, '/advanced/stage2a_target_class', latched
        )

    def _class_callback(self, message):
        self._target_class = message.data.strip()

    def _target_callback(self, message):
        if self._target_map is not None:
            return
        try:
            transform = self._tf_buffer.lookup_transform(
                'map',
                message.header.frame_id,
                Time.from_msg(message.header.stamp),
                timeout=Duration(seconds=0.5),
            )
            self._target_map = do_transform_pose_stamped(message, transform)
        except TransformException as error:
            self.get_logger().warning(f'Target to map TF failed; waiting: {error}')

    def _wait_target(self):
        timeout = float(self.get_parameter('target_timeout_seconds').value)
        deadline = time.monotonic() + timeout
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)
            if self._target_map is not None and self._target_class:
                return True
        return False

    def _navigate(self, x, y, yaw):
        while rclpy.ok() and not self._nav.wait_for_server(timeout_sec=1.0):
            self.get_logger().info('Waiting for NavigateToPose...')
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = 'map'
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x = x
        goal.pose.pose.position.y = y
        goal.pose.pose.orientation.z = math.sin(yaw / 2.0)
        goal.pose.pose.orientation.w = math.cos(yaw / 2.0)
        future = self._nav.send_goal_async(goal)
        rclpy.spin_until_future_complete(self, future)
        handle = future.result()
        if handle is None or not handle.accepted:
            self.get_logger().error('Manipulation approach goal was rejected.')
            return False
        result_future = handle.get_result_async()
        timeout = float(self.get_parameter('navigation_timeout_seconds').value)
        deadline = time.monotonic() + timeout
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.2)
            if result_future.done():
                result = result_future.result()
                return result is not None and result.status == GoalStatus.STATUS_SUCCEEDED
        handle.cancel_goal_async()
        self.get_logger().error('Manipulation approach navigation timed out.')
        return False

    def _set_manipulation_goal_tolerance(self):
        if not self._controller_parameters.wait_for_service(timeout_sec=5.0):
            self.get_logger().error(
                'controller_server parameter service is not available.'
            )
            return False
        xy_tolerance = float(self.get_parameter('xy_goal_tolerance_m').value)
        yaw_tolerance = float(
            self.get_parameter('yaw_goal_tolerance_rad').value
        )
        request = SetParameters.Request()
        request.parameters = [
            Parameter(
                'general_goal_checker.xy_goal_tolerance',
                Parameter.Type.DOUBLE,
                xy_tolerance,
            ).to_parameter_msg(),
            Parameter(
                'general_goal_checker.yaw_goal_tolerance',
                Parameter.Type.DOUBLE,
                yaw_tolerance,
            ).to_parameter_msg(),
        ]
        future = self._controller_parameters.call_async(request)
        rclpy.spin_until_future_complete(self, future, timeout_sec=5.0)
        response = future.result()
        results = None if response is None else response.results
        if results is None or not all(result.successful for result in results):
            self.get_logger().error(
                'Failed to apply manipulation-only Nav2 goal tolerances.'
            )
            return False
        self.get_logger().info(
            'Manipulation-only Nav2 goal tolerance: '
            f'xy={xy_tolerance:.3f} m yaw={yaw_tolerance:.3f} rad.'
        )
        return True

    def run(self):
        if not self._wait_target():
            self.get_logger().error('No complete Stage 1 target arrived before timeout.')
            return 1
        point = self._target_map.pose.position
        try:
            table_name, _, _ = nearest_dining_table((point.x, point.y, point.z))
            base_transform = self._tf_buffer.lookup_transform(
                'map',
                'base_link',
                Time(),
                timeout=Duration(seconds=1.0),
            )
            current_base = (
                base_transform.transform.translation.x,
                base_transform.transform.translation.y,
            )
            x, y, yaw = manipulation_pose(
                (point.x, point.y, point.z),
                float(self.get_parameter('table_clearance_m').value),
                current_base=current_base,
            )
            route = manipulation_route(current_base, (x, y, yaw))
        except (TransformException, ValueError) as error:
            self.get_logger().error(str(error))
            return 1
        self.get_logger().warning('OBSERVATION POSE NOT MANIPULATION REACHABLE')
        self.get_logger().info(
            f'Selected {self._target_class} map target: '
            f'[{point.x:.3f}, {point.y:.3f}, {point.z:.3f}]; '
            f'nearest table={table_name}.'
        )
        self.get_logger().info(
            f'Advanced-only manipulation approach from base '
            f'({current_base[0]:.3f}, {current_base[1]:.3f}): '
            f'({x:.3f}, {y:.3f}, {yaw:.3f}).'
        )
        if len(route) > 1:
            self.get_logger().info(
                'Exterior table route: '
                + ' -> '.join(
                    f'({px:.3f}, {py:.3f}, {pyaw:.3f})'
                    for px, py, pyaw in route
                )
            )
        if not self._set_manipulation_goal_tolerance():
            return 1
        attempts = int(self.get_parameter('navigation_attempts').value)
        for waypoint_index, (route_x, route_y, route_yaw) in enumerate(route, 1):
            navigation_succeeded = False
            for attempt in range(1, max(1, attempts) + 1):
                if self._navigate(route_x, route_y, route_yaw):
                    navigation_succeeded = True
                    break
                if attempt < attempts:
                    self.get_logger().warning(
                        f'Approach waypoint {waypoint_index}/{len(route)} attempt '
                        f'{attempt}/{attempts} failed; retrying.'
                    )
                    time.sleep(1.0)
            if not navigation_succeeded:
                self.get_logger().error(
                    f'Advanced-only manipulation approach failed at waypoint '
                    f'{waypoint_index}/{len(route)}.'
                )
                return 1
        self.get_logger().info('Advanced-only manipulation approach succeeded.')
        # Re-stamp the static map target after navigation; the pose itself stays
        # fixed and the arm node transforms it into the new planning frame.
        self._target_map.header.stamp = self.get_clock().now().to_msg()
        self._class_publisher.publish(String(data=self._target_class))
        self._map_target_publisher.publish(self._target_map)
        deadline = time.monotonic() + 2.0
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)
        return 0


def main():
    rclpy.init()
    node = AdvancedStage2AApproach()
    try:
        return node.run()
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        print(f'[advanced_stage2a_approach] Failed: {error}', file=sys.stderr)
        return 1
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    sys.exit(main())
