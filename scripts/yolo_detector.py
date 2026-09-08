#!/usr/bin/env python3
"""Run local YOLO inference on the robot RGB image and publish annotations."""

from pathlib import Path
import sys
import time

from ament_index_python.packages import get_package_share_directory
import cv2
from cv_bridge import CvBridge, CvBridgeError
import rclpy
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from sensor_msgs.msg import Image
from ultralytics import YOLO


DETECTION_LOG_PERIOD = 1.0
PERFORMANCE_LOG_PERIOD = 5.0
ERROR_LOG_PERIOD = 5.0


class YoloDetector(Node):
    """Detect objects in RGB images using one explicitly local YOLO model."""

    def __init__(self):
        super().__init__('yolo_detector')

        package_share = get_package_share_directory('robocup_home_robot')
        default_model = str(Path(package_share) / 'models' / 'yolo11n.pt')
        self.declare_parameter('model_path', default_model)
        self.declare_parameter('confidence_threshold', 0.50)
        self.declare_parameter('image_topic', '/camera/color/image_raw')
        self.declare_parameter('output_topic', '/vision/detections_image')
        self.declare_parameter('device', 'cpu')
        self.declare_parameter('max_inference_hz', 5.0)

        model_path = Path(
            self.get_parameter('model_path').get_parameter_value().string_value
        ).expanduser()
        self.confidence_threshold = self.get_parameter(
            'confidence_threshold'
        ).get_parameter_value().double_value
        self.image_topic = self.get_parameter(
            'image_topic'
        ).get_parameter_value().string_value
        self.output_topic = self.get_parameter(
            'output_topic'
        ).get_parameter_value().string_value
        self.device = self.get_parameter(
            'device'
        ).get_parameter_value().string_value
        self.max_inference_hz = self.get_parameter(
            'max_inference_hz'
        ).get_parameter_value().double_value

        if not model_path.is_file():
            raise RuntimeError(
                f'Local YOLO model does not exist: {model_path}. '
                'Automatic model download is disabled.'
            )
        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise RuntimeError('confidence_threshold must be between 0.0 and 1.0.')
        if self.max_inference_hz <= 0.0:
            raise RuntimeError('max_inference_hz must be greater than zero.')

        self.get_logger().info(f'Loading local YOLO model: {model_path}')
        self.model = YOLO(str(model_path))
        self.get_logger().info(
            f'YOLO model loaded; device={self.device}, '
            f'confidence_threshold={self.confidence_threshold:.2f}'
        )

        self.bridge = CvBridge()
        sensor_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )
        self.publisher = self.create_publisher(
            Image,
            self.output_topic,
            sensor_qos,
        )
        self.subscription = self.create_subscription(
            Image,
            self.image_topic,
            self._image_callback,
            sensor_qos,
        )

        self._minimum_inference_period = 1.0 / self.max_inference_hz
        self._last_inference_started = None
        self._last_detection_log = None
        self._last_error_log = None
        self._first_image_logged = False
        self._inference_disabled = False
        self._stats_started = time.monotonic()
        self._stats_frames = 0
        self._stats_inference_seconds = 0.0

        self.get_logger().info(
            f'Subscribing to {self.image_topic}; publishing annotations to '
            f'{self.output_topic}; max_inference_hz={self.max_inference_hz:.1f}'
        )

    def _log_frame_error(self, message):
        now = time.monotonic()
        if (
            self._last_error_log is None
            or now - self._last_error_log >= ERROR_LOG_PERIOD
        ):
            self.get_logger().error(message)
            self._last_error_log = now

    @staticmethod
    def _class_name(names, class_id):
        if isinstance(names, dict):
            return str(names.get(class_id, class_id))
        if 0 <= class_id < len(names):
            return str(names[class_id])
        return str(class_id)

    @staticmethod
    def _draw_detection(image, detection):
        class_name, confidence, x1, y1, x2, y2 = detection
        height, width = image.shape[:2]
        x1 = max(0, min(width - 1, x1))
        x2 = max(0, min(width - 1, x2))
        y1 = max(0, min(height - 1, y1))
        y2 = max(0, min(height - 1, y2))
        label = f'{class_name} {confidence:.2f}'

        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
        (text_width, text_height), baseline = cv2.getTextSize(
            label,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            1,
        )
        text_top = max(0, y1 - text_height - baseline - 4)
        cv2.rectangle(
            image,
            (x1, text_top),
            (min(width - 1, x1 + text_width + 4), y1),
            (0, 255, 0),
            -1,
        )
        cv2.putText(
            image,
            label,
            (x1 + 2, max(text_height, y1 - baseline - 2)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )

    def _extract_detections(self, result):
        detections = []
        if result.boxes is None:
            return detections

        for box in result.boxes:
            confidence = float(box.conf[0].item())
            if confidence < self.confidence_threshold:
                continue
            class_id = int(box.cls[0].item())
            x1, y1, x2, y2 = (
                int(round(value)) for value in box.xyxy[0].tolist()
            )
            detections.append((
                self._class_name(result.names, class_id),
                confidence,
                x1,
                y1,
                x2,
                y2,
            ))
        return detections

    def _log_detections(self, detections, now):
        if not detections:
            return
        if (
            self._last_detection_log is not None
            and now - self._last_detection_log < DETECTION_LOG_PERIOD
        ):
            return

        lines = ['Detections:']
        for class_name, confidence, x1, y1, x2, y2 in detections:
            lines.append(
                f'{class_name} conf={confidence:.3f} '
                f'bbox=[{x1}, {y1}, {x2}, {y2}]'
            )
        self.get_logger().info('\n'.join(lines))
        self._last_detection_log = now

    def _update_performance_stats(self, inference_seconds, now):
        self._stats_frames += 1
        self._stats_inference_seconds += inference_seconds
        elapsed = now - self._stats_started
        if elapsed < PERFORMANCE_LOG_PERIOD:
            return

        average_ms = 1000.0 * self._stats_inference_seconds / self._stats_frames
        processing_fps = self._stats_frames / elapsed
        self.get_logger().info(
            f'Performance: inference={average_ms:.1f} ms/frame, '
            f'processing={processing_fps:.2f} FPS, device={self.device}'
        )
        self._stats_started = now
        self._stats_frames = 0
        self._stats_inference_seconds = 0.0

    def _image_callback(self, message):
        if self._inference_disabled:
            return

        now = time.monotonic()
        if (
            self._last_inference_started is not None
            and now - self._last_inference_started < self._minimum_inference_period
        ):
            return
        self._last_inference_started = now

        if not self._first_image_logged:
            self.get_logger().info(
                f'First RGB image: {message.width}x{message.height}, '
                f'encoding={message.encoding}, frame_id={message.header.frame_id}'
            )
            self._first_image_logged = True

        try:
            bgr_image = self.bridge.imgmsg_to_cv2(
                message,
                desired_encoding='bgr8',
            )
        except (CvBridgeError, cv2.error, TypeError, ValueError) as error:
            self._log_frame_error(f'CvBridge conversion failed: {error}')
            return

        inference_started = time.perf_counter()
        try:
            results = self.model.predict(
                source=bgr_image,
                conf=self.confidence_threshold,
                device=self.device,
                verbose=False,
            )
        except Exception as error:
            self.get_logger().error(
                f'YOLO inference failed; inference has been disabled: {error}'
            )
            self._inference_disabled = True
            return
        inference_seconds = time.perf_counter() - inference_started

        if not results:
            self._log_frame_error('YOLO inference returned no result object.')
            return

        detections = self._extract_detections(results[0])
        annotated_image = bgr_image.copy()
        for detection in detections:
            self._draw_detection(annotated_image, detection)

        try:
            output_message = self.bridge.cv2_to_imgmsg(
                annotated_image,
                encoding='bgr8',
            )
        except (CvBridgeError, cv2.error, TypeError, ValueError) as error:
            self._log_frame_error(f'Annotated image conversion failed: {error}')
            return
        output_message.header = message.header
        self.publisher.publish(output_message)

        finished = time.monotonic()
        self._log_detections(detections, finished)
        self._update_performance_stats(inference_seconds, finished)


def main():
    rclpy.init()
    node = None
    try:
        node = YoloDetector()
        rclpy.spin(node)
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        print(f'[yolo_detector] Failed to start: {error}', file=sys.stderr)
        return 1
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    sys.exit(main())
