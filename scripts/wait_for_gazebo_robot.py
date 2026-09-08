#!/usr/bin/env python3
"""Wait until the spawned robot's ROS sensor and TF interfaces are ready."""

import sys
import time

import rclpy
from nav_msgs.msg import Odometry
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import Imu, LaserScan
from tf2_ros import Buffer, TransformListener


TIMEOUT = 90.0


class RobotReadiness:
    """Track the minimum ROS interfaces required before SLAM starts."""

    def __init__(self):
        self.node = rclpy.create_node('wait_for_robot_interfaces')
        self.scan_frame = None
        self.received_odom = False
        self.received_imu = False
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(
            self.tf_buffer,
            self.node,
            spin_thread=False,
        )
        self.node.create_subscription(
            LaserScan,
            '/scan',
            self.scan_callback,
            qos_profile_sensor_data,
        )
        self.node.create_subscription(
            Odometry,
            '/odom',
            self.odom_callback,
            10,
        )
        self.node.create_subscription(
            Imu,
            '/imu',
            self.imu_callback,
            qos_profile_sensor_data,
        )

    def scan_callback(self, message):
        self.scan_frame = message.header.frame_id

    def odom_callback(self, _message):
        self.received_odom = True

    def imu_callback(self, _message):
        self.received_imu = True

    def ready(self):
        if not self.scan_frame or not self.received_odom or not self.received_imu:
            return False
        return self.tf_buffer.can_transform('odom', self.scan_frame, Time())


def main():
    """Wait for real messages and odom-to-scan TF instead of a fixed delay."""
    rclpy.init()
    readiness = RobotReadiness()
    print('[robot_ready] Waiting for /scan, /odom, /imu, and odom -> scan TF', flush=True)
    deadline = time.monotonic() + TIMEOUT
    try:
        while time.monotonic() < deadline:
            rclpy.spin_once(readiness.node, timeout_sec=0.1)
            if readiness.ready():
                print(
                    '[robot_ready] ROS robot interfaces and TF are ready',
                    flush=True,
                )
                return 0

        print(
            f'[robot_ready] ROS robot interfaces unavailable after {TIMEOUT:.0f}s',
            file=sys.stderr,
            flush=True,
        )
        return 1
    finally:
        readiness.node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    sys.exit(main())
