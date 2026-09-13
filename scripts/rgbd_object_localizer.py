#!/usr/bin/env python3
"""Detect pilot objects and localize their visible surfaces in the map frame."""

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time

import cv2
from cv_bridge import CvBridge, CvBridgeError
from geometry_msgs.msg import PointStamped
from message_filters import ApproximateTimeSynchronizer, Subscriber
import numpy as np
from rclpy.duration import Duration
from rclpy.executors import MultiThreadedExecutor
import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo, Image
from std_srvs.srv import Trigger
from tf2_geometry_msgs import do_transform_point
from tf2_ros import Buffer, TransformException, TransformListener
from ultralytics import YOLO
from visualization_msgs.msg import Marker, MarkerArray
from vision_final_dedup import final_deduplicate_clusters
from vision_final_dedup import partition_by_minimum_observations
from formal_runtime_config import validate_model_contract


DETECTION_LOG_PERIOD = 1.0
CLUSTER_LOG_PERIOD = 2.0
WARNING_LOG_PERIOD = 5.0


@dataclass
class ObjectCluster:
    """Compact running-mean state for one same-class spatial object."""

    cluster_id: int
    class_name: str
    x: float
    y: float
    z: float
    observation_count: int
    last_seen_time: float
    mean_confidence: float

    def add_observation(self, x, y, z, confidence, seen_time):
        """Update the cluster centroid without retaining observation history."""
        new_count = self.observation_count + 1
        weight = 1.0 / new_count
        self.x += (x - self.x) * weight
        self.y += (y - self.y) * weight
        self.z += (z - self.z) * weight
        self.mean_confidence += (confidence - self.mean_confidence) * weight
        self.observation_count = new_count
        self.last_seen_time = seen_time

    def merge_from(self, other):
        """Merge another cluster using observation-count-weighted means."""
        total_count = self.observation_count + other.observation_count
        self_weight = self.observation_count / total_count
        other_weight = other.observation_count / total_count
        self.x = self.x * self_weight + other.x * other_weight
        self.y = self.y * self_weight + other.y * other_weight
        self.z = self.z * self_weight + other.z * other_weight
        self.mean_confidence = (
            self.mean_confidence * self_weight
            + other.mean_confidence * other_weight
        )
        self.observation_count = total_count
        self.last_seen_time = max(
            self.last_seen_time,
            other.last_seen_time,
        )


class RgbdObjectLocalizer(Node):
    """Run YOLO once, estimate robust bbox depth, and transform points to map."""

    def __init__(self):
        super().__init__(
            'rgbd_object_localizer',
            parameter_overrides=[Parameter('use_sim_time', value=True)],
        )

        default_model = str(
            Path.home()
            / 'robocup_assets/training_runs/apple_coke_pilot/weights/best.pt'
        )
        self.declare_parameter('model_path', default_model)
        self.declare_parameter('confidence_threshold', 0.50)
        self.declare_parameter('rgb_topic', '/camera/color/image_raw')
        self.declare_parameter('depth_topic', '/camera/depth/image_raw')
        self.declare_parameter('camera_info_topic', '/camera/camera_info')
        self.declare_parameter('output_image_topic', '/vision/detections_image')
        self.declare_parameter('marker_topic', '/vision/object_markers')
        self.declare_parameter(
            'deduplicated_marker_topic',
            '/vision/deduplicated_object_markers',
        )
        self.declare_parameter(
            'final_marker_topic',
            '/vision/final_object_markers',
        )
        self.declare_parameter('final_marker_z', 0.75)
        self.declare_parameter('target_frame', 'map')
        self.declare_parameter('device', 'cpu')
        self.declare_parameter('max_inference_hz', 5.0)
        self.declare_parameter('sync_slop_seconds', 0.05)
        self.declare_parameter('depth_roi_ratio', 0.40)
        self.declare_parameter('minimum_depth_roi_size', 5)
        self.declare_parameter('minimum_valid_depth_pixels', 5)
        self.declare_parameter('minimum_depth_m', 0.20)
        self.declare_parameter('maximum_depth_m', 5.00)
        self.declare_parameter('tf_timeout_seconds', 0.10)
        self.declare_parameter('deduplication_radius', 0.05)
        self.declare_parameter('final_deduplication_radius', 0.08)
        self.declare_parameter('min_confirmations', 3)
        self.declare_parameter('final_min_confirmations', 5)
        self.declare_parameter('target_classes', ['apple', 'coke_can'])
        self.declare_parameter(
            'expected_model_classes',
            Parameter.Type.STRING_ARRAY,
        )
        self.declare_parameter('group_number', -1)
        self.declare_parameter(
            'answer_output_dir',
            str(Path.home() / 'robocup_assets/submissions'),
        )

        model_path = Path(self.get_parameter('model_path').value).expanduser()
        self.confidence_threshold = float(
            self.get_parameter('confidence_threshold').value
        )
        self.rgb_topic = str(self.get_parameter('rgb_topic').value)
        self.depth_topic = str(self.get_parameter('depth_topic').value)
        self.camera_info_topic = str(
            self.get_parameter('camera_info_topic').value
        )
        self.output_image_topic = str(
            self.get_parameter('output_image_topic').value
        )
        self.marker_topic = str(self.get_parameter('marker_topic').value)
        self.deduplicated_marker_topic = str(
            self.get_parameter('deduplicated_marker_topic').value
        )
        self.final_marker_topic = str(
            self.get_parameter('final_marker_topic').value
        )
        self.final_marker_z = float(
            self.get_parameter('final_marker_z').value
        )
        self.target_frame = str(self.get_parameter('target_frame').value)
        self.device = str(self.get_parameter('device').value)
        self.max_inference_hz = float(
            self.get_parameter('max_inference_hz').value
        )
        self.sync_slop_seconds = float(
            self.get_parameter('sync_slop_seconds').value
        )
        self.depth_roi_ratio = float(
            self.get_parameter('depth_roi_ratio').value
        )
        self.minimum_depth_roi_size = int(
            self.get_parameter('minimum_depth_roi_size').value
        )
        self.minimum_valid_depth_pixels = int(
            self.get_parameter('minimum_valid_depth_pixels').value
        )
        self.minimum_depth_m = float(
            self.get_parameter('minimum_depth_m').value
        )
        self.maximum_depth_m = float(
            self.get_parameter('maximum_depth_m').value
        )
        self.tf_timeout_seconds = float(
            self.get_parameter('tf_timeout_seconds').value
        )
        self.deduplication_radius = float(
            self.get_parameter('deduplication_radius').value
        )
        self.final_deduplication_radius = float(
            self.get_parameter('final_deduplication_radius').value
        )
        self.min_confirmations = int(
            self.get_parameter('min_confirmations').value
        )
        self.final_min_confirmations = int(
            self.get_parameter('final_min_confirmations').value
        )
        self.target_classes = tuple(
            str(class_name)
            for class_name in self.get_parameter('target_classes').value
        )
        self.expected_model_classes = tuple(
            str(class_name)
            for class_name in self.get_parameter('expected_model_classes').value
        )
        self.group_number = int(self.get_parameter('group_number').value)
        self.answer_output_dir = Path(
            self.get_parameter('answer_output_dir').value
        ).expanduser()
        self._validate_parameters(model_path)

        self.get_logger().info(f'Loading local YOLO model: {model_path}')
        self.model = YOLO(str(model_path))
        try:
            model_names = validate_model_contract(
                self.model.names,
                self.expected_model_classes,
                self.target_classes,
            )
        except ValueError as error:
            raise RuntimeError(f'Invalid YOLO model contract: {error}') from error
        self.get_logger().info(
            f'YOLO model loaded; classes={list(model_names)}, '
            f'device={self.device}, confidence_threshold='
            f'{self.confidence_threshold:.2f}'
        )

        self.bridge = CvBridge()
        self.tf_buffer = Buffer(cache_time=Duration(seconds=10.0), node=self)
        self.tf_listener = TransformListener(self.tf_buffer, self)
        sensor_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )
        self.image_publisher = self.create_publisher(
            Image, self.output_image_topic, sensor_qos
        )
        self.marker_publisher = self.create_publisher(
            MarkerArray, self.marker_topic, 10
        )
        self.deduplicated_marker_publisher = self.create_publisher(
            MarkerArray, self.deduplicated_marker_topic, 10
        )
        final_marker_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.final_marker_publisher = self.create_publisher(
            MarkerArray,
            self.final_marker_topic,
            final_marker_qos,
        )
        self.camera_info_subscription = self.create_subscription(
            CameraInfo,
            self.camera_info_topic,
            self._camera_info_callback,
            sensor_qos,
        )
        self.rgb_subscriber = Subscriber(
            self, Image, self.rgb_topic, qos_profile=sensor_qos
        )
        self.depth_subscriber = Subscriber(
            self, Image, self.depth_topic, qos_profile=sensor_qos
        )
        self.synchronizer = ApproximateTimeSynchronizer(
            [self.rgb_subscriber, self.depth_subscriber],
            queue_size=10,
            slop=self.sync_slop_seconds,
        )
        self.synchronizer.registerCallback(self._synchronized_callback)

        self._camera_info = None
        self._minimum_inference_period = 1.0 / self.max_inference_hz
        self._last_inference_started = None
        self._last_detection_log = None
        self._last_cluster_log = None
        self._warning_times = {}
        self._first_camera_info_logged = False
        self._first_sync_logged = False
        self._inference_disabled = False
        self._clusters = []
        self._next_cluster_id = 0
        self._cluster_lineages = {}
        self._same_frame_separate_pairs = set()
        self.save_answer_service = self.create_service(
            Trigger,
            '/vision/save_answer',
            self._save_answer_callback,
        )
        self.reset_tracking_service = self.create_service(
            Trigger,
            '/vision/reset_tracking',
            self._reset_tracking_callback,
        )
        self.get_clusters_service = self.create_service(
            Trigger,
            '/vision/get_clusters',
            self._get_clusters_callback,
        )

        self.get_logger().info(
            f'Synchronizing RGB={self.rgb_topic} and depth={self.depth_topic} '
            f'with slop={self.sync_slop_seconds:.3f}s; '
            f'CameraInfo={self.camera_info_topic}; target={self.target_frame}; '
            f'markers={self.marker_topic}; '
            f'deduplicated_markers={self.deduplicated_marker_topic}; '
            f'final_markers={self.final_marker_topic}; '
            f'deduplication_radius={self.deduplication_radius:.3f}m; '
            f'final_deduplication_radius='
            f'{self.final_deduplication_radius:.3f}m; '
            f'min_confirmations={self.min_confirmations}; '
            f'final_min_confirmations={self.final_min_confirmations}; '
            f'target_classes={list(self.target_classes)}; '
            f'group_number={self.group_number}; '
            f'answer_output_dir={self.answer_output_dir}; '
            'save_service=/vision/save_answer; '
            'reset_service=/vision/reset_tracking; '
            'cluster_service=/vision/get_clusters'
        )

    def _validate_parameters(self, model_path):
        if not model_path.is_file():
            raise RuntimeError(
                f'Local YOLO model does not exist: {model_path}. '
                'Automatic model download is disabled.'
            )
        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise RuntimeError('confidence_threshold must be in [0, 1].')
        if self.max_inference_hz <= 0.0:
            raise RuntimeError('max_inference_hz must be greater than zero.')
        if self.sync_slop_seconds < 0.0:
            raise RuntimeError('sync_slop_seconds cannot be negative.')
        if not 0.0 < self.depth_roi_ratio <= 1.0:
            raise RuntimeError('depth_roi_ratio must be in (0, 1].')
        if self.minimum_depth_roi_size < 1:
            raise RuntimeError('minimum_depth_roi_size must be at least one.')
        if self.minimum_valid_depth_pixels < 1:
            raise RuntimeError('minimum_valid_depth_pixels must be at least one.')
        if not 0.0 < self.minimum_depth_m < self.maximum_depth_m:
            raise RuntimeError('invalid minimum/maximum depth range.')
        if self.tf_timeout_seconds < 0.0:
            raise RuntimeError('tf_timeout_seconds cannot be negative.')
        if not math.isfinite(self.final_marker_z):
            raise RuntimeError('final_marker_z must be finite.')
        if self.deduplication_radius <= 0.0:
            raise RuntimeError('deduplication_radius must be greater than zero.')
        if self.final_deduplication_radius <= 0.0:
            raise RuntimeError(
                'final_deduplication_radius must be greater than zero.'
            )
        if self.min_confirmations < 1:
            raise RuntimeError('min_confirmations must be at least one.')
        if self.final_min_confirmations < self.min_confirmations:
            raise RuntimeError(
                'final_min_confirmations must be at least min_confirmations.'
            )
        if not self.target_classes:
            raise RuntimeError('target_classes must not be empty.')
        if any(not class_name for class_name in self.target_classes):
            raise RuntimeError('target_classes must not contain empty names.')
        if len(set(self.target_classes)) != len(self.target_classes):
            raise RuntimeError('target_classes must not contain duplicates.')
        if self.expected_model_classes:
            if len(self.expected_model_classes) != 18:
                raise RuntimeError(
                    'Formal expected_model_classes must contain 18 names.'
                )
            if len(set(self.expected_model_classes)) != 18:
                raise RuntimeError(
                    'Formal expected_model_classes must be distinct.'
                )
            if len(self.target_classes) != 3:
                raise RuntimeError(
                    'Formal runtime requires exactly three target_classes.'
                )
            if self.group_number <= 0:
                raise RuntimeError(
                    'Formal runtime requires a positive group_number.'
                )

    def _warn_throttled(self, key, message):
        now = time.monotonic()
        previous = self._warning_times.get(key)
        if previous is None or now - previous >= WARNING_LOG_PERIOD:
            self.get_logger().warning(message)
            self._warning_times[key] = now

    def _camera_info_callback(self, message):
        if message.width == 0 or message.height == 0:
            self._warn_throttled('camera_info_size', 'CameraInfo has zero size.')
            return
        fx, fy = float(message.k[0]), float(message.k[4])
        if not np.isfinite([fx, fy]).all() or fx <= 0.0 or fy <= 0.0:
            self._warn_throttled(
                'camera_info_intrinsics', 'CameraInfo has invalid fx/fy.'
            )
            return
        self._camera_info = message
        if not self._first_camera_info_logged:
            self.get_logger().info(
                f'CameraInfo: {message.width}x{message.height}, '
                f'frame_id={message.header.frame_id}, fx={fx:.6f}, '
                f'fy={fy:.6f}, cx={message.k[2]:.6f}, '
                f'cy={message.k[5]:.6f}'
            )
            self._first_camera_info_logged = True

    @staticmethod
    def _stamp_seconds(message):
        return message.header.stamp.sec + message.header.stamp.nanosec * 1e-9

    def _aligned_inputs(self, rgb_message, depth_message, camera_info):
        if rgb_message.encoding.lower() != 'rgb8':
            self._warn_throttled(
                'rgb_encoding',
                f'Expected rgb8 RGB image, got {rgb_message.encoding}; skipping.',
            )
            return False
        if depth_message.encoding.upper() != '32FC1':
            self._warn_throttled(
                'depth_encoding',
                f'Expected 32FC1 depth image, got {depth_message.encoding}; skipping.',
            )
            return False
        dimensions = {
            (rgb_message.width, rgb_message.height),
            (depth_message.width, depth_message.height),
            (camera_info.width, camera_info.height),
        }
        if len(dimensions) != 1:
            self._warn_throttled(
                'alignment_dimensions',
                f'RGB/Depth/CameraInfo dimensions differ: {sorted(dimensions)}; '
                'pixel correspondence is unsafe.',
            )
            return False
        frames = {
            rgb_message.header.frame_id,
            depth_message.header.frame_id,
            camera_info.header.frame_id,
        }
        if len(frames) != 1 or not next(iter(frames)):
            self._warn_throttled(
                'alignment_frames',
                f'RGB/Depth/CameraInfo frames differ: {sorted(frames)}; '
                'pixel correspondence is unsafe.',
            )
            return False
        return True

    @staticmethod
    def _class_name(names, class_id):
        if isinstance(names, dict):
            return str(names.get(class_id, class_id))
        if 0 <= class_id < len(names):
            return str(names[class_id])
        return str(class_id)

    def _extract_detections(self, result):
        detections = []
        if result.boxes is None:
            return detections
        for box in result.boxes:
            confidence = float(box.conf[0].item())
            if confidence < self.confidence_threshold:
                continue
            class_id = int(box.cls[0].item())
            x1, y1, x2, y2 = (float(value) for value in box.xyxy[0].tolist())
            detections.append(
                (
                    self._class_name(result.names, class_id),
                    confidence,
                    x1,
                    y1,
                    x2,
                    y2,
                )
            )
        return detections

    def _median_bbox_depth(self, depth_image, detection):
        _, _, x1, y1, x2, y2 = detection
        height, width = depth_image.shape[:2]
        x1 = max(0.0, min(width - 1.0, x1))
        x2 = max(0.0, min(width - 1.0, x2))
        y1 = max(0.0, min(height - 1.0, y1))
        y2 = max(0.0, min(height - 1.0, y2))
        if x2 <= x1 or y2 <= y1:
            return None

        center_u = (x1 + x2) * 0.5
        center_v = (y1 + y2) * 0.5
        roi_width = max(
            self.minimum_depth_roi_size,
            int(round((x2 - x1) * self.depth_roi_ratio)),
        )
        roi_height = max(
            self.minimum_depth_roi_size,
            int(round((y2 - y1) * self.depth_roi_ratio)),
        )
        roi_x1 = max(0, int(round(center_u - roi_width * 0.5)))
        roi_x2 = min(width, roi_x1 + roi_width)
        roi_y1 = max(0, int(round(center_v - roi_height * 0.5)))
        roi_y2 = min(height, roi_y1 + roi_height)
        roi = depth_image[roi_y1:roi_y2, roi_x1:roi_x2]
        valid_mask = (
            np.isfinite(roi)
            & (roi >= self.minimum_depth_m)
            & (roi <= self.maximum_depth_m)
        )
        valid_depths = roi[valid_mask]
        if valid_depths.size < self.minimum_valid_depth_pixels:
            return None
        return center_u, center_v, float(np.median(valid_depths)), valid_depths.size

    @staticmethod
    def _camera_point(u, v, depth, camera_info, stamp):
        fx = float(camera_info.k[0])
        fy = float(camera_info.k[4])
        cx = float(camera_info.k[2])
        cy = float(camera_info.k[5])
        point = PointStamped()
        point.header.stamp = stamp
        point.header.frame_id = camera_info.header.frame_id
        point.point.x = (u - cx) * depth / fx
        point.point.y = (v - cy) * depth / fy
        point.point.z = depth
        return point

    def _transform_to_target(self, camera_point):
        transform = self.tf_buffer.lookup_transform(
            self.target_frame,
            camera_point.header.frame_id,
            Time.from_msg(camera_point.header.stamp),
            timeout=Duration(seconds=self.tf_timeout_seconds),
        )
        return do_transform_point(camera_point, transform)

    @staticmethod
    def _draw_detection(image, detection, localized):
        class_name, confidence, x1, y1, x2, y2 = detection
        height, width = image.shape[:2]
        start = (
            max(0, min(width - 1, int(round(x1)))),
            max(0, min(height - 1, int(round(y1)))),
        )
        end = (
            max(0, min(width - 1, int(round(x2)))),
            max(0, min(height - 1, int(round(y2)))),
        )
        color = (0, 255, 0) if localized else (0, 180, 255)
        cv2.rectangle(image, start, end, color, 2)
        label = f'{class_name} {confidence:.2f}'
        if localized:
            label += f' {localized["depth"]:.2f}m'
        cv2.putText(
            image,
            label,
            (start[0], max(15, start[1] - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1,
            cv2.LINE_AA,
        )

    def _make_markers(self, localizations, stamp):
        messages = []
        delete_all = Marker()
        delete_all.action = Marker.DELETEALL
        messages.append(delete_all)
        lifetime = Duration(
            seconds=max(0.5, 2.0 / self.max_inference_hz)
        ).to_msg()

        for index, localized in enumerate(localizations):
            class_name = localized['class_name']
            point = localized['map'].point
            color = (0.2, 1.0, 0.2) if class_name == 'apple' else (1.0, 0.2, 0.1)

            shape = Marker()
            shape.header.frame_id = self.target_frame
            shape.header.stamp = stamp
            shape.ns = 'current_objects'
            shape.id = index * 2
            shape.type = Marker.SPHERE
            shape.action = Marker.ADD
            shape.pose.position = point
            shape.pose.orientation.w = 1.0
            shape.scale.x = 0.08
            shape.scale.y = 0.08
            shape.scale.z = 0.08
            shape.color.r, shape.color.g, shape.color.b = color
            shape.color.a = 0.9
            shape.lifetime = lifetime
            messages.append(shape)

            text = Marker()
            text.header.frame_id = self.target_frame
            text.header.stamp = stamp
            text.ns = 'current_object_labels'
            text.id = index * 2 + 1
            text.type = Marker.TEXT_VIEW_FACING
            text.action = Marker.ADD
            text.pose.position.x = point.x
            text.pose.position.y = point.y
            text.pose.position.z = point.z + 0.12
            text.pose.orientation.w = 1.0
            text.scale.z = 0.08
            text.color.r = 1.0
            text.color.g = 1.0
            text.color.b = 1.0
            text.color.a = 1.0
            text.text = f'{class_name} {localized["confidence"]:.2f}'
            text.lifetime = lifetime
            messages.append(text)
        return MarkerArray(markers=messages)

    def _matching_cluster(self, localized):
        class_name = localized['class_name']
        point = localized['map'].point
        nearest_cluster = None
        nearest_distance = None
        for cluster in self._clusters:
            if cluster.class_name != class_name:
                continue
            distance = math.hypot(point.x - cluster.x, point.y - cluster.y)
            if nearest_distance is None or distance < nearest_distance:
                nearest_cluster = cluster
                nearest_distance = distance
        if (
            nearest_cluster is not None
            and nearest_distance < self.deduplication_radius
        ):
            return nearest_cluster
        return None

    def _update_clusters(self, localizations, stamp):
        seen_time = stamp.sec + stamp.nanosec * 1e-9
        associated_clusters = []
        for localized in localizations:
            point = localized['map'].point
            cluster = self._matching_cluster(localized)
            if cluster is None:
                cluster = ObjectCluster(
                    cluster_id=self._next_cluster_id,
                    class_name=localized['class_name'],
                    x=point.x,
                    y=point.y,
                    z=point.z,
                    observation_count=1,
                    last_seen_time=seen_time,
                    mean_confidence=localized['confidence'],
                )
                self._clusters.append(cluster)
                self._cluster_lineages[cluster.cluster_id] = frozenset(
                    (cluster.cluster_id,)
                )
                self._next_cluster_id += 1
            else:
                cluster.add_observation(
                    point.x,
                    point.y,
                    point.z,
                    localized['confidence'],
                    seen_time,
                )
            associated_clusters.append(cluster)
        self._record_same_frame_separate_pairs(associated_clusters)
        self._consolidate_clusters()

    def _record_same_frame_separate_pairs(self, associated_clusters):
        """Remember same-class detections that remained separate this frame."""
        for first_index, first in enumerate(associated_clusters):
            for second in associated_clusters[first_index + 1:]:
                if first.class_name != second.class_name:
                    continue
                if first.cluster_id == second.cluster_id:
                    continue
                self._same_frame_separate_pairs.add(
                    frozenset((first.cluster_id, second.cluster_id))
                )

    def _merge_cluster_lineages(self, retained_cluster_id, removed_cluster_id):
        """Keep historical pair evidence valid after online consolidation."""
        retained_lineage = self._cluster_lineages.get(
            retained_cluster_id,
            frozenset((retained_cluster_id,)),
        )
        removed_lineage = self._cluster_lineages.pop(
            removed_cluster_id,
            frozenset((removed_cluster_id,)),
        )
        self._cluster_lineages[retained_cluster_id] = (
            retained_lineage | removed_lineage
        )

    def _consolidate_clusters(self):
        """Merge overlapping same-class clusters until none remain."""
        while True:
            merged = False
            for first_index, first in enumerate(self._clusters):
                for second in self._clusters[first_index + 1:]:
                    if first.class_name != second.class_name:
                        continue
                    distance = math.hypot(
                        first.x - second.x,
                        first.y - second.y,
                    )
                    if distance >= self.deduplication_radius:
                        continue

                    retained, removed = sorted(
                        (first, second),
                        key=lambda cluster: cluster.cluster_id,
                    )
                    retained.merge_from(removed)
                    self._merge_cluster_lineages(
                        retained.cluster_id,
                        removed.cluster_id,
                    )
                    self._clusters.remove(removed)
                    self.get_logger().info(
                        f'Merged {retained.class_name} cluster '
                        f'#{removed.cluster_id} into #{retained.cluster_id}; '
                        f'distance={distance:.3f} m; '
                        f'observations={retained.observation_count}'
                    )
                    merged = True
                    break
                if merged:
                    break
            if not merged:
                return

    def _make_deduplicated_markers(self, stamp):
        messages = []
        delete_all = Marker()
        delete_all.action = Marker.DELETEALL
        messages.append(delete_all)

        for cluster in self._clusters:
            if cluster.observation_count < self.min_confirmations:
                continue
            color = (
                (0.2, 1.0, 0.2)
                if cluster.class_name == 'apple'
                else (1.0, 0.2, 0.1)
            )
            marker = Marker()
            marker.header.frame_id = self.target_frame
            marker.header.stamp = stamp
            marker.ns = 'deduplicated_objects'
            marker.id = cluster.cluster_id
            marker.type = Marker.TEXT_VIEW_FACING
            marker.action = Marker.ADD
            marker.pose.position.x = cluster.x
            marker.pose.position.y = cluster.y
            marker.pose.position.z = cluster.z + 0.12
            marker.pose.orientation.w = 1.0
            marker.scale.z = 0.10
            marker.color.r, marker.color.g, marker.color.b = color
            marker.color.a = 1.0
            marker.text = (
                f'{cluster.class_name} ({cluster.observation_count})'
            )
            messages.append(marker)
        return MarkerArray(markers=messages)

    def _log_clusters(self):
        if not self._clusters:
            return
        now = time.monotonic()
        if (
            self._last_cluster_log is not None
            and now - self._last_cluster_log < CLUSTER_LOG_PERIOD
        ):
            return

        lines = ['Tracked objects:']
        current_class = None
        for cluster in sorted(
            self._clusters,
            key=lambda item: (item.class_name, item.cluster_id),
        ):
            if cluster.class_name != current_class:
                current_class = cluster.class_name
                lines.append(f'{current_class}:')
            confirmed = cluster.observation_count >= self.min_confirmations
            lines.append(
                f'  #{cluster.cluster_id} x={cluster.x:.3f} '
                f'y={cluster.y:.3f} observations={cluster.observation_count} '
                f'confirmed={str(confirmed).lower()}'
            )
        self.get_logger().info('\n'.join(lines))
        self._last_cluster_log = now

    def _log_localizations(self, localizations):
        if not localizations:
            return
        now = time.monotonic()
        if (
            self._last_detection_log is not None
            and now - self._last_detection_log < DETECTION_LOG_PERIOD
        ):
            return
        lines = ['RGB-D localizations (visible surface estimate):']
        for localized in localizations:
            camera = localized['camera'].point
            target = localized['map'].point
            lines.append(
                f'{localized["class_name"]}: conf={localized["confidence"]:.3f}, '
                f'pixel=({localized["u"]:.1f}, {localized["v"]:.1f}), '
                f'depth={localized["depth"]:.3f}m, '
                f'camera=[{camera.x:.3f}, {camera.y:.3f}, {camera.z:.3f}], '
                f'{self.target_frame}=[{target.x:.3f}, {target.y:.3f}, '
                f'{target.z:.3f}]'
            )
        self.get_logger().info('\n'.join(lines))
        self._last_detection_log = now

    def _make_answer_snapshot(self):
        """Copy confirmed target clusters into the official JSON structure."""
        if not self.target_classes:
            raise ValueError('target_classes must not be empty.')
        if any(not class_name for class_name in self.target_classes):
            raise ValueError('target_classes must not contain empty names.')
        if len(set(self.target_classes)) != len(self.target_classes):
            raise ValueError('target_classes must not contain duplicates.')

        objects = {class_name: [] for class_name in self.target_classes}
        confirmed_clusters = [
            cluster
            for cluster in self._clusters
            if (
                cluster.class_name in objects
                and cluster.observation_count >= self.min_confirmations
            )
        ]
        final_clusters, final_merges = final_deduplicate_clusters(
            confirmed_clusters,
            self.final_deduplication_radius,
            self._same_frame_separate_pairs,
            self._cluster_lineages,
        )
        for merge in final_merges:
            self.get_logger().info(
                f'Final dedup merged {merge.class_name} clusters '
                f'{merge.first_cluster_ids} and {merge.second_cluster_ids}; '
                f'distance={merge.distance:.3f} m; '
                f'observations={merge.first_observations}+'
                f'{merge.second_observations}'
            )
        output_clusters, suppressed_clusters = (
            partition_by_minimum_observations(
                final_clusters,
                self.final_min_confirmations,
            )
        )
        for cluster in suppressed_clusters:
            self.get_logger().info(
                f'Final output suppressed low-evidence '
                f'{cluster.class_name} cluster '
                f'{cluster.source_cluster_ids}; '
                f'observations={cluster.observation_count} < '
                f'{self.final_min_confirmations}'
            )

        for cluster in output_clusters:
            x = float(cluster.x)
            y = float(cluster.y)
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError(
                    f'Final {cluster.class_name} cluster '
                    f'{cluster.source_cluster_ids} has non-finite x/y.'
                )
            objects[cluster.class_name].append({'x': x, 'y': y})

        for detected_objects in objects.values():
            detected_objects.sort(key=lambda item: (item['x'], item['y']))
        return {'objects': objects}

    def _write_answer_snapshot(self, snapshot):
        """Atomically publish a complete JSON file without overwriting."""
        if self.group_number <= 0:
            raise ValueError(
                'group_number must be a positive integer before saving.'
            )

        self.answer_output_dir.mkdir(parents=True, exist_ok=True)
        output_path = (
            self.answer_output_dir / f'{self.group_number}_answer.json'
        )
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.answer_output_dir,
            prefix=f'.{output_path.name}.',
            suffix='.tmp',
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(
                    snapshot,
                    stream,
                    ensure_ascii=False,
                    indent=2,
                    allow_nan=False,
                )
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary_path, output_path)
            except FileExistsError:
                raise FileExistsError(
                    'Answer file already exists; refusing to overwrite: '
                    f'{output_path}'
                ) from None
        finally:
            temporary_path.unlink(missing_ok=True)
        return output_path

    def _make_final_answer_markers(self, snapshot, stamp):
        """Render the exact saved x/y snapshot as persistent RViz markers."""
        messages = []
        delete_all = Marker()
        delete_all.action = Marker.DELETEALL
        messages.append(delete_all)

        marker_id = 0
        for class_name in self.target_classes:
            color = (
                (0.2, 1.0, 0.2)
                if class_name == 'apple'
                else (1.0, 0.2, 0.1)
            )
            for class_index, point in enumerate(snapshot['objects'][class_name], 1):
                shape = Marker()
                shape.header.frame_id = self.target_frame
                shape.header.stamp = stamp
                shape.ns = 'final_objects'
                shape.id = marker_id
                marker_id += 1
                shape.type = Marker.SPHERE
                shape.action = Marker.ADD
                shape.pose.position.x = point['x']
                shape.pose.position.y = point['y']
                shape.pose.position.z = self.final_marker_z
                shape.pose.orientation.w = 1.0
                shape.scale.x = 0.10
                shape.scale.y = 0.10
                shape.scale.z = 0.10
                shape.color.r, shape.color.g, shape.color.b = color
                shape.color.a = 1.0
                messages.append(shape)

                label = Marker()
                label.header.frame_id = self.target_frame
                label.header.stamp = stamp
                label.ns = 'final_object_labels'
                label.id = marker_id
                marker_id += 1
                label.type = Marker.TEXT_VIEW_FACING
                label.action = Marker.ADD
                label.pose.position.x = point['x']
                label.pose.position.y = point['y']
                label.pose.position.z = self.final_marker_z + 0.12
                label.pose.orientation.w = 1.0
                label.scale.z = 0.10
                label.color.r = 1.0
                label.color.g = 1.0
                label.color.b = 1.0
                label.color.a = 1.0
                label.text = f'{class_name} {class_index}'
                messages.append(label)
        return MarkerArray(markers=messages)

    def _save_answer_callback(self, request, response):
        del request
        try:
            snapshot = self._make_answer_snapshot()
            counts = [
                f'{class_name}: {len(snapshot["objects"][class_name])}'
                for class_name in self.target_classes
            ]
            self.get_logger().info('\n'.join(['Final results:', *counts]))
            output_path = self._write_answer_snapshot(snapshot)
        except (OSError, TypeError, ValueError) as error:
            response.success = False
            response.message = str(error)
            self.get_logger().error(f'Answer save failed: {error}')
            return response

        response.success = True
        response.message = f'Answer saved: {output_path}'
        self.final_marker_publisher.publish(
            self._make_final_answer_markers(
                snapshot,
                self.get_clock().now().to_msg(),
            )
        )
        self.get_logger().info(response.message)
        return response

    def _reset_tracking_callback(self, request, response):
        """Start a fresh scoring observation window without restarting YOLO."""
        del request
        removed_count = len(self._clusters)
        self._clusters.clear()
        self._next_cluster_id = 0
        self._cluster_lineages.clear()
        self._same_frame_separate_pairs.clear()
        self._last_cluster_log = None
        response.success = True
        response.message = f'Reset visual tracking; removed {removed_count} clusters.'
        self.get_logger().info(response.message)
        return response

    def _get_clusters_callback(self, request, response):
        """Return a read-only snapshot of all confirmed visual clusters."""
        del request
        try:
            objects = []
            for cluster in sorted(
                self._clusters,
                key=lambda item: (item.class_name, item.cluster_id),
            ):
                if cluster.observation_count < self.min_confirmations:
                    continue
                coordinates = (cluster.x, cluster.y, cluster.z)
                if not all(math.isfinite(value) for value in coordinates):
                    raise ValueError(
                        f'Confirmed {cluster.class_name} cluster '
                        f'#{cluster.cluster_id} has non-finite coordinates.'
                    )
                objects.append({
                    'cluster_id': cluster.cluster_id,
                    'class_name': cluster.class_name,
                    'x': float(cluster.x),
                    'y': float(cluster.y),
                    'z': float(cluster.z),
                    'observations': cluster.observation_count,
                })
            response.message = json.dumps(
                {'objects': objects},
                ensure_ascii=False,
                allow_nan=False,
                separators=(',', ':'),
            )
        except (TypeError, ValueError) as error:
            response.success = False
            response.message = f'Could not serialize clusters: {error}'
            return response

        response.success = True
        return response

    def _synchronized_callback(self, rgb_message, depth_message):
        if self._inference_disabled:
            return
        now = time.monotonic()
        if (
            self._last_inference_started is not None
            and now - self._last_inference_started < self._minimum_inference_period
        ):
            return
        self._last_inference_started = now

        camera_info = self._camera_info
        if camera_info is None:
            self._warn_throttled(
                'camera_info_missing', 'Waiting for a valid CameraInfo message.'
            )
            return
        if not self._aligned_inputs(rgb_message, depth_message, camera_info):
            return
        if not self._first_sync_logged:
            difference = abs(
                self._stamp_seconds(rgb_message)
                - self._stamp_seconds(depth_message)
            )
            self.get_logger().info(
                f'First aligned RGB-D pair: {rgb_message.width}x'
                f'{rgb_message.height}, RGB={rgb_message.encoding}, '
                f'depth={depth_message.encoding}, '
                f'frame_id={rgb_message.header.frame_id}, dt={difference:.6f}s'
            )
            self._first_sync_logged = True

        try:
            bgr_image = self.bridge.imgmsg_to_cv2(
                rgb_message, desired_encoding='bgr8'
            )
            depth_image = self.bridge.imgmsg_to_cv2(
                depth_message, desired_encoding='passthrough'
            )
        except (CvBridgeError, cv2.error, TypeError, ValueError) as error:
            self._warn_throttled('cv_bridge', f'CvBridge conversion failed: {error}')
            return

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
        if not results:
            self._warn_throttled('yolo_empty', 'YOLO returned no result object.')
            return

        detections = self._extract_detections(results[0])
        annotated_image = bgr_image.copy()
        localizations = []
        for detection in detections:
            class_name, confidence, _, _, _, _ = detection
            depth_result = self._median_bbox_depth(depth_image, detection)
            localized = None
            if depth_result is None:
                self._warn_throttled(
                    f'depth_{class_name}',
                    f'{class_name}: too few valid depth pixels in central bbox ROI; '
                    'skipping its 3D point for this frame.',
                )
            else:
                u, v, depth, valid_count = depth_result
                camera_point = self._camera_point(
                    u, v, depth, camera_info, rgb_message.header.stamp
                )
                try:
                    target_point = self._transform_to_target(camera_point)
                except TransformException as error:
                    self._warn_throttled(
                        'tf',
                        f'TF {camera_point.header.frame_id} -> '
                        f'{self.target_frame} unavailable at image timestamp: {error}',
                    )
                else:
                    localized = {
                        'class_name': class_name,
                        'confidence': confidence,
                        'u': u,
                        'v': v,
                        'depth': depth,
                        'valid_depth_pixels': valid_count,
                        'camera': camera_point,
                        'map': target_point,
                    }
                    localizations.append(localized)
            self._draw_detection(annotated_image, detection, localized)

        try:
            output_message = self.bridge.cv2_to_imgmsg(
                annotated_image, encoding='bgr8'
            )
        except (CvBridgeError, cv2.error, TypeError, ValueError) as error:
            self._warn_throttled(
                'annotated_image', f'Annotated image conversion failed: {error}'
            )
        else:
            output_message.header = rgb_message.header
            self.image_publisher.publish(output_message)

        self.marker_publisher.publish(
            self._make_markers(localizations, rgb_message.header.stamp)
        )
        self._update_clusters(localizations, rgb_message.header.stamp)
        self.deduplicated_marker_publisher.publish(
            self._make_deduplicated_markers(rgb_message.header.stamp)
        )
        self._log_localizations(localizations)
        self._log_clusters()


def main():
    rclpy.init()
    node = None
    executor = None
    try:
        node = RgbdObjectLocalizer()
        executor = MultiThreadedExecutor(num_threads=2)
        executor.add_node(node)
        node.get_logger().info(
            'Using a 2-thread executor so TF callbacks remain responsive '
            'during YOLO inference.'
        )
        executor.spin()
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        print(f'[rgbd_object_localizer] Failed to start: {error}', file=sys.stderr)
        return 1
    finally:
        if executor is not None:
            executor.shutdown()
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    sys.exit(main())
