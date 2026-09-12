#!/usr/bin/env python3
"""Scan the living room in relative steps using the Nav2 Spin behavior."""

import math
import sys

from action_msgs.msg import GoalStatus
from nav2_msgs.action import Spin
from rclpy.action import ActionClient
from rclpy.duration import Duration
import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from std_srvs.srv import Trigger


ACTION_SERVER = '/spin'
RESET_TRACKING_SERVICE = '/vision/reset_tracking'
SERVICE_WAIT_ATTEMPTS = 30


class ScanLivingRoom(Node):
    """Request a finite sequence of relative Nav2 Spin actions."""

    def __init__(self):
        super().__init__(
            'scan_living_room',
            parameter_overrides=[Parameter('use_sim_time', value=True)],
        )
        self.declare_parameter('scan_steps', 12)
        self.declare_parameter('spin_angle', 0.5235987756)
        self.declare_parameter('dwell_seconds', 2.0)
        self.declare_parameter('spin_time_allowance', 15.0)

        self.scan_steps = int(self.get_parameter('scan_steps').value)
        self.spin_angle = float(self.get_parameter('spin_angle').value)
        self.dwell_seconds = float(self.get_parameter('dwell_seconds').value)
        self.spin_time_allowance = float(
            self.get_parameter('spin_time_allowance').value
        )
        self._validate_parameters()
        self._action_client = ActionClient(self, Spin, ACTION_SERVER)
        self._reset_tracking_client = self.create_client(
            Trigger,
            RESET_TRACKING_SERVICE,
        )

    def _validate_parameters(self):
        if self.scan_steps < 1:
            raise RuntimeError('scan_steps must be at least one.')
        if not math.isfinite(self.spin_angle) or self.spin_angle == 0.0:
            raise RuntimeError('spin_angle must be finite and non-zero.')
        if not math.isfinite(self.dwell_seconds) or self.dwell_seconds < 0.0:
            raise RuntimeError('dwell_seconds must be finite and non-negative.')
        if (
            not math.isfinite(self.spin_time_allowance)
            or self.spin_time_allowance <= 0.0
        ):
            raise RuntimeError(
                'spin_time_allowance must be finite and greater than zero.'
            )

    def _wait_for_server(self):
        self.get_logger().info('Waiting for Nav2 Spin action server...')
        while rclpy.ok():
            if self._action_client.wait_for_server(timeout_sec=1.0):
                self.get_logger().info('Nav2 Spin action server ready.')
                return True
        return False

    def _send_spin_goal(self):
        goal = Spin.Goal()
        goal.target_yaw = self.spin_angle
        goal.time_allowance = Duration(
            seconds=self.spin_time_allowance
        ).to_msg()

        send_future = self._action_client.send_goal_async(goal)
        rclpy.spin_until_future_complete(self, send_future)
        if not send_future.done():
            self.get_logger().error('Stopped before the Spin goal was sent.')
            return None, 1
        if send_future.exception() is not None:
            self.get_logger().error(
                f'Failed to send Spin goal: {send_future.exception()}'
            )
            return None, 1

        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            self.get_logger().error('Spin goal was rejected.')
            return None, 1

        result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future)
        if not result_future.done():
            self.get_logger().error('Stopped before Spin returned a result.')
            return None, 1
        if result_future.exception() is not None:
            self.get_logger().error(
                f'Failed while waiting for Spin result: '
                f'{result_future.exception()}'
            )
            return None, 1

        wrapped_result = result_future.result()
        if wrapped_result is None:
            self.get_logger().error('Spin ended without an action result.')
            return None, 1
        return wrapped_result, 0

    def _reset_visual_tracking(self):
        self.get_logger().info(
            f'Waiting for {RESET_TRACKING_SERVICE} before scanning...'
        )
        for attempt in range(1, SERVICE_WAIT_ATTEMPTS + 1):
            if self._reset_tracking_client.wait_for_service(timeout_sec=1.0):
                break
            if attempt % 5 == 0:
                self.get_logger().info(
                    f'Still waiting for {RESET_TRACKING_SERVICE}...'
                )
            if not rclpy.ok():
                return False
        else:
            self.get_logger().error(
                f'{RESET_TRACKING_SERVICE} was unavailable after '
                f'{SERVICE_WAIT_ATTEMPTS} seconds.'
            )
            return False

        future = self._reset_tracking_client.call_async(Trigger.Request())
        rclpy.spin_until_future_complete(self, future)
        if not future.done():
            self.get_logger().error('Stopped before visual tracking was reset.')
            return False
        if future.exception() is not None:
            self.get_logger().error(
                f'Visual tracking reset failed: {future.exception()}'
            )
            return False
        response = future.result()
        if response is None or not response.success:
            message = response.message if response is not None else 'no response'
            self.get_logger().error(
                f'Visual tracking reset was rejected: {message}'
            )
            return False
        self.get_logger().info(response.message)
        return True

    def _dwell_using_ros_time(self):
        if self.dwell_seconds == 0.0:
            return True
        start_time = self.get_clock().now()
        dwell_duration = Duration(seconds=self.dwell_seconds)
        while rclpy.ok():
            if self.get_clock().now() - start_time >= dwell_duration:
                return True
            rclpy.spin_once(self, timeout_sec=0.1)
        return False

    @staticmethod
    def _status_name(status):
        return {
            GoalStatus.STATUS_UNKNOWN: 'UNKNOWN',
            GoalStatus.STATUS_ACCEPTED: 'ACCEPTED',
            GoalStatus.STATUS_EXECUTING: 'EXECUTING',
            GoalStatus.STATUS_CANCELING: 'CANCELING',
            GoalStatus.STATUS_SUCCEEDED: 'SUCCEEDED',
            GoalStatus.STATUS_CANCELED: 'CANCELED',
            GoalStatus.STATUS_ABORTED: 'ABORTED',
        }.get(status, 'UNRECOGNIZED')

    def scan(self):
        if not self._wait_for_server():
            self.get_logger().error(
                'ROS shutdown before the Nav2 Spin action server became ready.'
            )
            return 1
        if not self._reset_visual_tracking():
            return 1

        self.get_logger().info('Living room scan starting.')
        angle_degrees = math.degrees(self.spin_angle)
        for step_index in range(1, self.scan_steps + 1):
            self.get_logger().info(
                f'Scan step {step_index}/{self.scan_steps}\n'
                f'Rotating {angle_degrees:.1f} deg...'
            )
            wrapped_result, error_code = self._send_spin_goal()
            if error_code != 0:
                self.get_logger().error(
                    f'Scan step {step_index}/{self.scan_steps} failed.'
                )
                return error_code

            status = wrapped_result.status
            if status != GoalStatus.STATUS_SUCCEEDED:
                status_name = self._status_name(status)
                self.get_logger().error(
                    f'Scan step {step_index}/{self.scan_steps} failed. '
                    f'Spin status: {status_name} ({status}).'
                )
                return 2 if status == GoalStatus.STATUS_CANCELED else 1

            self.get_logger().info(
                f'Scan step {step_index}/{self.scan_steps} complete.\n'
                f'Observing for {self.dwell_seconds:.1f} seconds...'
            )
            if not self._dwell_using_ros_time():
                self.get_logger().error(
                    f'Scan interrupted while observing after step '
                    f'{step_index}/{self.scan_steps}.'
                )
                return 1

        self.get_logger().info('Living room scan completed.')
        return 0


def main():
    rclpy.init()
    node = None
    try:
        node = ScanLivingRoom()
        return node.scan()
    except KeyboardInterrupt:
        if node is not None:
            node.get_logger().warning('Living room scan interrupted by user.')
        return 130
    except Exception as error:
        print(f'[scan_living_room] Failed to start: {error}', file=sys.stderr)
        return 1
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    sys.exit(main())
