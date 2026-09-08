#!/usr/bin/env python3
"""Wait for the RGB-D messages and camera-to-map TF needed by vision."""

import importlib.util
import sys
import time

import rclpy
from rclpy.parameter import Parameter
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo, Image
from tf2_ros import Buffer, TransformListener


TIMEOUT = 120.0
VISION_MODULES = ('cv2', 'cv_bridge', 'torch', 'ultralytics')


class VisionReadiness:
    """Observe the runtime inputs without changing any stable subsystem."""

    def __init__(self):
        self.node = rclpy.create_node(
            'wait_for_vision_interfaces',
            parameter_overrides=[Parameter('use_sim_time', value=True)],
        )
        self.received_rgb = False
        self.received_depth = False
        self.camera_frame = None
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(
            self.tf_buffer,
            self.node,
            spin_thread=False,
        )
        self.node.create_subscription(
            Image,
            '/camera/color/image_raw',
            self._rgb_callback,
            qos_profile_sensor_data,
        )
        self.node.create_subscription(
            Image,
            '/camera/depth/image_raw',
            self._depth_callback,
            qos_profile_sensor_data,
        )
        self.node.create_subscription(
            CameraInfo,
            '/camera/camera_info',
            self._camera_info_callback,
            qos_profile_sensor_data,
        )

    def _rgb_callback(self, _message):
        self.received_rgb = True

    def _depth_callback(self, _message):
        self.received_depth = True

    def _camera_info_callback(self, message):
        if message.header.frame_id:
            self.camera_frame = message.header.frame_id

    def ready(self):
        if not self.received_rgb or not self.received_depth or not self.camera_frame:
            return False
        return self.tf_buffer.can_transform('map', self.camera_frame, Time())


def missing_vision_modules():
    """Return required Python modules absent from the active interpreter."""
    return [
        module_name
        for module_name in VISION_MODULES
        if importlib.util.find_spec(module_name) is None
    ]


def main():
    """Exit successfully only after the complete localizer input chain is ready."""
    missing_modules = missing_vision_modules()
    if missing_modules:
        print(
            '[vision_ready] Missing Python modules in the active environment: '
            f'{", ".join(missing_modules)}. Activate '
            '~/robocup_vision_venv before launching base_system.launch.py.',
            file=sys.stderr,
            flush=True,
        )
        return 1

    rclpy.init()
    readiness = VisionReadiness()
    print(
        '[vision_ready] Waiting for RGB, depth, CameraInfo, and map -> camera TF',
        flush=True,
    )
    deadline = time.monotonic() + TIMEOUT
    try:
        while time.monotonic() < deadline:
            rclpy.spin_once(readiness.node, timeout_sec=0.1)
            if readiness.ready():
                print(
                    '[vision_ready] Vision inputs are ready; '
                    f'camera frame={readiness.camera_frame}',
                    flush=True,
                )
                return 0

        print(
            f'[vision_ready] Vision inputs unavailable after {TIMEOUT:.0f}s',
            file=sys.stderr,
            flush=True,
        )
        return 1
    finally:
        readiness.node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    sys.exit(main())
