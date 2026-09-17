#!/usr/bin/env python3
"""Persist the first Advanced Stage 1 target image when evidence is requested."""

from pathlib import Path
import sys

import cv2
from cv_bridge import CvBridge, CvBridgeError
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image


class AdvancedTargetImageSaver(Node):
    """Save one selected-target image without changing perception behavior."""

    def __init__(self):
        super().__init__('advanced_target_image_saver')
        self.declare_parameter('target_image_topic', '/advanced/target_image')
        self.declare_parameter('evidence_path', '')
        self.evidence_path = str(self.get_parameter('evidence_path').value).strip()
        self.saved = False
        self.bridge = CvBridge()
        if not self.evidence_path:
            self.get_logger().info('Target-image persistence disabled.')
            return
        sensor_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )
        self.create_subscription(
            Image,
            str(self.get_parameter('target_image_topic').value),
            self._image_callback,
            sensor_qos,
        )
        self.get_logger().info(f'Will save selected-target evidence to {self.evidence_path}.')

    def _image_callback(self, message):
        if self.saved:
            return
        try:
            image = self.bridge.imgmsg_to_cv2(message, desired_encoding='bgr8')
            path = Path(self.evidence_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(path), image):
                raise OSError('cv2.imwrite returned false')
        except (CvBridgeError, OSError, ValueError, cv2.error) as error:
            self.get_logger().error(f'Could not save target-image evidence: {error}')
            return
        self.saved = True
        self.get_logger().info(f'Saved selected-target evidence: {path}')


def main():
    rclpy.init()
    node = None
    try:
        node = AdvancedTargetImageSaver()
        rclpy.spin(node)
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        print(f'[advanced_target_image_saver] Failed to start: {error}', file=sys.stderr)
        return 1
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    sys.exit(main())
