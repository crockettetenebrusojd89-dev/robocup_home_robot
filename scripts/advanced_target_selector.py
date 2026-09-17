#!/usr/bin/env python3
"""Choose and display one depth-valid dining target from localizer output."""

from collections import OrderedDict
from pathlib import Path
import sys

import cv2
from advanced_target_selection import detection_candidate
from cv_bridge import CvBridge, CvBridgeError
from geometry_msgs.msg import PoseStamped
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool
from std_srvs.srv import SetBool
from tf2_geometry_msgs import do_transform_pose_stamped
from tf2_ros import Buffer, TransformException, TransformListener
from rclpy.duration import Duration
from rclpy.time import Time
from sensor_msgs.msg import Image
from vision_msgs.msg import Detection2DArray


class AdvancedTargetSelector(Node):
    """Select one high-quality localized detection after dining navigation."""

    def __init__(self):
        super().__init__('advanced_target_selector')
        self.declare_parameter('detection_topic', '/advanced/localized_detections')
        self.declare_parameter('annotated_image_topic', '/vision/detections_image')
        self.declare_parameter('target_image_topic', '/advanced/target_image')
        self.declare_parameter('target_image_evidence_path', '')
        self.declare_parameter('target_camera_topic', '/advanced/grasp_target_camera')
        self.declare_parameter('target_base_topic', '/advanced/grasp_target_base_link')
        self.declare_parameter('selected_topic', '/advanced/target_selected')
        self.declare_parameter('activation_service', '/advanced/enable_target_selection')
        self.declare_parameter('minimum_confidence', 0.50)
        self.declare_parameter('minimum_depth_m', 0.20)
        self.declare_parameter('maximum_depth_m', 2.50)
        self.declare_parameter('edge_margin_pixels', 12.0)
        self.declare_parameter('base_frame', 'base_link')
        self.declare_parameter('tf_timeout_seconds', 0.10)
        self.declare_parameter('enabled', False)

        self.minimum_confidence = float(self.get_parameter('minimum_confidence').value)
        self.minimum_depth_m = float(self.get_parameter('minimum_depth_m').value)
        self.maximum_depth_m = float(self.get_parameter('maximum_depth_m').value)
        self.edge_margin_pixels = float(self.get_parameter('edge_margin_pixels').value)
        self.base_frame = str(self.get_parameter('base_frame').value)
        self.tf_timeout_seconds = float(self.get_parameter('tf_timeout_seconds').value)
        self.enabled = bool(self.get_parameter('enabled').value)
        self.selected = False
        self.images_by_stamp = OrderedDict()
        self.bridge = CvBridge()
        self.tf_buffer = Buffer(cache_time=Duration(seconds=10.0), node=self)
        self.tf_listener = TransformListener(self.tf_buffer, self)
        sensor_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )
        self.target_image_publisher = self.create_publisher(
            Image, str(self.get_parameter('target_image_topic').value), sensor_qos
        )
        self.camera_publisher = self.create_publisher(
            PoseStamped, str(self.get_parameter('target_camera_topic').value), 1
        )
        self.base_publisher = self.create_publisher(
            PoseStamped, str(self.get_parameter('target_base_topic').value), 1
        )
        self.selected_publisher = self.create_publisher(
            Bool, str(self.get_parameter('selected_topic').value), 1
        )
        self.create_subscription(
            Image,
            str(self.get_parameter('annotated_image_topic').value),
            self._image_callback,
            sensor_qos,
        )
        self.create_subscription(
            Detection2DArray,
            str(self.get_parameter('detection_topic').value),
            self._detections_callback,
            sensor_qos,
        )
        self.create_service(
            SetBool,
            str(self.get_parameter('activation_service').value),
            self._activation_callback,
        )
        self.get_logger().info(
            'Advanced selector ready; it will choose one high-confidence, '
            'depth-valid, non-edge dining detection only after activation.'
        )

    def _activation_callback(self, request, response):
        self.enabled = request.data
        if self.enabled:
            self.selected = False
            response.message = 'Advanced target selection enabled.'
        else:
            response.message = 'Advanced target selection disabled.'
        response.success = True
        self.get_logger().info(response.message)
        return response

    def _image_callback(self, message):
        stamp = (message.header.stamp.sec, message.header.stamp.nanosec)
        self.images_by_stamp[stamp] = message
        while len(self.images_by_stamp) > 12:
            self.images_by_stamp.popitem(last=False)

    def _detections_callback(self, message):
        if not self.enabled or self.selected:
            return
        stamp = (message.header.stamp.sec, message.header.stamp.nanosec)
        image = self.images_by_stamp.get(stamp)
        if image is None:
            return
        candidates = []
        for detection in message.detections:
            candidate = detection_candidate(
                detection,
                image.width,
                image.height,
                self.edge_margin_pixels,
            )
            if candidate is None:
                continue
            if candidate['confidence'] < self.minimum_confidence:
                continue
            depth = candidate['point'].z
            if not self.minimum_depth_m <= depth <= self.maximum_depth_m:
                continue
            candidates.append(candidate)
        if not candidates:
            return
        selected = max(
            candidates,
            key=lambda item: (item['confidence'], item['area'], -item['point'].z),
        )
        self._publish_target(selected, message.header, image)
        self.selected = True
        self.selected_publisher.publish(Bool(data=True))

    def _publish_target(self, selected, header, image_message):
        target_camera = PoseStamped()
        target_camera.header = header
        target_camera.pose.position = selected['point']
        target_camera.pose.orientation.w = 1.0
        self.camera_publisher.publish(target_camera)
        target_base = None
        try:
            transform = self.tf_buffer.lookup_transform(
                self.base_frame,
                header.frame_id,
                Time.from_msg(header.stamp),
                timeout=Duration(seconds=self.tf_timeout_seconds),
            )
            target_base = do_transform_pose_stamped(target_camera, transform)
            self.base_publisher.publish(target_base)
        except TransformException as error:
            self.get_logger().warning(
                f'Camera target selected, but TF to {self.base_frame} is unavailable: '
                f'{error}'
            )

        try:
            rendered = self.bridge.imgmsg_to_cv2(image_message, desired_encoding='bgr8')
            start = (int(round(selected['x1'])), int(round(selected['y1'])))
            end = (int(round(selected['x2'])), int(round(selected['y2'])))
            cv2.rectangle(rendered, start, end, (255, 0, 255), 3)
            label = f"TARGET {selected['class_name']} {selected['confidence']:.2f}"
            cv2.putText(
                rendered, label, (start[0], max(22, start[1] - 8)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 0, 255), 2, cv2.LINE_AA,
            )
            target_image = self.bridge.cv2_to_imgmsg(rendered, encoding='bgr8')
            target_image.header = header
            self.target_image_publisher.publish(target_image)
            evidence_path = str(
                self.get_parameter('target_image_evidence_path').value
            ).strip()
            if evidence_path:
                path = Path(evidence_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                if not cv2.imwrite(str(path), rendered):
                    raise OSError('cv2.imwrite returned false')
                self.get_logger().info(
                    f'Published {self.get_parameter("target_image_topic").value} '
                    f'and saved selected-target evidence: {path}'
                )
        except (CvBridgeError, cv2.error, OSError, TypeError, ValueError) as error:
            self.get_logger().error(f'Could not render advanced target image: {error}')

        camera = target_camera.pose.position
        lines = [
            'Advanced task target:',
            f"class = {selected['class_name']}",
            f"confidence = {selected['confidence']:.3f}",
            f"bbox = [{selected['x1']:.1f}, {selected['y1']:.1f}, "
            f"{selected['x2']:.1f}, {selected['y2']:.1f}]",
            f'point_camera = [{camera.x:.3f}, {camera.y:.3f}, {camera.z:.3f}]',
        ]
        if target_base is not None:
            point = target_base.pose.position
            lines.append(
                f'point_{self.base_frame} = '
                f'[{point.x:.3f}, {point.y:.3f}, {point.z:.3f}]'
            )
        self.get_logger().info('\n'.join(lines))


def main():
    rclpy.init()
    node = None
    try:
        node = AdvancedTargetSelector()
        rclpy.spin(node)
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        print(f'[advanced_target_selector] Failed to start: {error}', file=sys.stderr)
        return 1
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    sys.exit(main())
