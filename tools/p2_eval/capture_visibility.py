#!/usr/bin/env python3
"""Capture read-only image/timing evidence beside the frozen P2 runtime."""

from __future__ import annotations

import argparse
from collections import OrderedDict
import json
import math
from pathlib import Path
import re
import sys
import time

import cv2
from cv_bridge import CvBridge, CvBridgeError
import numpy as np
import rclpy
from rcl_interfaces.msg import Log
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
    qos_profile_sensor_data,
)
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo, Image
from tf2_ros import Buffer, TransformException, TransformListener


RESET_MARKER = "Reset visual tracking;"
SCAN_START_MARKER = "Living room scan starting."
SCAN_END_MARKER = "Living room scan completed."
TELEMETRY_MARKER = "VISION_TELEMETRY "
STEP_PATTERN = re.compile(r"Scan step (\d+)/(\d+)")
VIEWPOINT_PATTERN = re.compile(r"Observation point (\d+)/(\d+):")


def stamp_nanoseconds(stamp) -> int:
    return int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)


def scan_event_state(message: str, current_step: int, phase: str):
    """Return state changes implied by one existing runtime log message."""
    if RESET_MARKER in message:
        return True, 0, "pre_scan"
    if TELEMETRY_MARKER in message:
        return False, current_step, "finalized"
    if SCAN_END_MARKER in message:
        return True, current_step, "post_scan"
    match = STEP_PATTERN.search(message)
    if match:
        step = int(match.group(1))
        if "complete" in message or "Observing for" in message:
            return True, step, "dwell"
        return True, step, "rotation"
    if SCAN_START_MARKER in message:
        return True, current_step, "pre_scan"
    return None, current_step, phase


def quaternion_yaw(rotation) -> float:
    siny = 2.0 * (rotation.w * rotation.z + rotation.x * rotation.y)
    cosy = 1.0 - 2.0 * (rotation.y * rotation.y + rotation.z * rotation.z)
    return math.atan2(siny, cosy)


class VisibilityCapture(Node):
    """Observe existing topics and persist bounded JPEG evidence only."""

    def __init__(self, output_dir: Path, capture_hz: float, jpeg_quality: int):
        super().__init__(
            "p2_visibility_capture",
            parameter_overrides=[Parameter("use_sim_time", value=True)],
        )
        self.output_dir = output_dir
        self.raw_dir = output_dir / "raw"
        self.runtime_raw_dir = output_dir / "runtime_raw"
        self.runtime_depth_dir = output_dir / "runtime_depth"
        self.annotated_dir = output_dir / "annotated"
        for directory in (
            self.raw_dir,
            self.runtime_raw_dir,
            self.runtime_depth_dir,
            self.annotated_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self.capture_period_ns = int(1_000_000_000 / capture_hz)
        self.jpeg_quality = jpeg_quality
        self.bridge = CvBridge()
        self.tf_buffer = Buffer(cache_time=Duration(seconds=120.0), node=self)
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.active = False
        self.step = 0
        self.phase = "waiting"
        self.viewpoint_index = 0
        self.viewpoint_total = 0
        self.last_periodic_stamp_ns = None
        self.raw_cache: OrderedDict[int, Image] = OrderedDict()
        self.depth_cache: OrderedDict[int, Image] = OrderedDict()
        self.cache_limit = 90
        self.saved_periodic_stamps: set[int] = set()
        self.runtime_stamps: set[int] = set()
        self.counts = {
            "raw_messages": 0,
            "raw_periodic_saved": 0,
            "runtime_annotated_saved": 0,
            "runtime_raw_saved": 0,
            "runtime_raw_missing": 0,
            "depth_messages": 0,
            "runtime_depth_saved": 0,
            "runtime_depth_missing": 0,
            "camera_info_messages": 0,
            "image_write_failures": 0,
            "tf_lookup_failures": 0,
        }
        self.started_monotonic = time.monotonic()
        self.manifest = (output_dir / "frames.jsonl").open(
            "w", encoding="utf-8", buffering=1
        )
        self.events = (output_dir / "events.jsonl").open(
            "w", encoding="utf-8", buffering=1
        )
        self.create_subscription(
            Image,
            "/camera/color/image_raw",
            self._raw_callback,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            Image,
            "/camera/depth/image_raw",
            self._depth_callback,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            Image,
            "/vision/detections_image",
            self._annotated_callback,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            CameraInfo,
            "/camera/camera_info",
            self._camera_info_callback,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            Log,
            "/rosout",
            self._rosout_callback,
            QoSProfile(
                history=HistoryPolicy.KEEP_LAST,
                depth=1000,
                reliability=ReliabilityPolicy.RELIABLE,
                # Volatile avoids replaying a completed scan from an earlier run.
                durability=DurabilityPolicy.VOLATILE,
            ),
        )
        self._write_json(
            output_dir / "capture_config.json",
            {
                "schema_version": 1,
                "capture_hz": capture_hz,
                "jpeg_quality": jpeg_quality,
                "topics": [
                    "/camera/color/image_raw",
                    "/camera/depth/image_raw",
                    "/vision/detections_image",
                    "/camera/camera_info",
                    "/rosout",
                    "/tf",
                    "/tf_static",
                ],
                "ground_truth_access": False,
                "publishes_topics": False,
                "calls_services": False,
            },
        )
        self._write_json(
            output_dir / "ready.json",
            {"ready": True, "wall_time": time.time()},
        )

    @staticmethod
    def _write_json(path: Path, value) -> None:
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def _event(self, event: str, **values) -> None:
        record = {
            "event": event,
            "wall_time": time.time(),
            "monotonic_seconds": time.monotonic(),
            "capture_clock_ns": self.get_clock().now().nanoseconds,
            "step": self.step,
            "phase": self.phase,
            "viewpoint_index": self.viewpoint_index,
            "viewpoint_total": self.viewpoint_total,
        }
        record.update(values)
        self.events.write(json.dumps(record, separators=(",", ":")) + "\n")

    def _rosout_callback(self, message: Log) -> None:
        active, step, phase = scan_event_state(message.msg, self.step, self.phase)
        viewpoint_match = VIEWPOINT_PATTERN.search(message.msg)
        if viewpoint_match:
            self.viewpoint_index = int(viewpoint_match.group(1))
            self.viewpoint_total = int(viewpoint_match.group(2))
            self.step = 0
            phase = "navigation"
        relevant = (
            active is not None
            or viewpoint_match is not None
            or RESET_MARKER in message.msg
            or SCAN_START_MARKER in message.msg
            or SCAN_END_MARKER in message.msg
        )
        if not relevant:
            return
        if active is not None:
            self.active = active
        self.step = step
        self.phase = phase
        self._event(
            "runtime_log",
            logger=message.name,
            message=message.msg,
            log_stamp_ns=stamp_nanoseconds(message.stamp),
            active=self.active,
        )

    def _camera_info_callback(self, message: CameraInfo) -> None:
        self.counts["camera_info_messages"] += 1
        path = self.output_dir / "camera_info.json"
        if path.exists() or message.width <= 0 or message.height <= 0:
            return
        self._write_json(
            path,
            {
                "header_stamp_ns": stamp_nanoseconds(message.header.stamp),
                "frame_id": message.header.frame_id,
                "width": message.width,
                "height": message.height,
                "distortion_model": message.distortion_model,
                "d": list(message.d),
                "k": list(message.k),
                "r": list(message.r),
                "p": list(message.p),
            },
        )

    @staticmethod
    def _transform_record(transform) -> dict:
        translation = transform.transform.translation
        rotation = transform.transform.rotation
        return {
            "translation": {
                "x": translation.x,
                "y": translation.y,
                "z": translation.z,
            },
            "rotation": {
                "x": rotation.x,
                "y": rotation.y,
                "z": rotation.z,
                "w": rotation.w,
            },
        }

    def _frame_context(self, message: Image) -> dict:
        stamp = Time.from_msg(message.header.stamp)
        record = {
            "step": self.step,
            "phase": self.phase,
            "active": self.active,
            "viewpoint_index": self.viewpoint_index,
            "viewpoint_total": self.viewpoint_total,
            "frame_id": message.header.frame_id,
            "receipt_wall_time": time.time(),
            "receipt_monotonic_seconds": time.monotonic(),
        }
        for key, source_frame in (
            ("map_to_camera", message.header.frame_id),
            ("map_to_base", "base_link"),
        ):
            try:
                transform = self.tf_buffer.lookup_transform(
                    "map", source_frame, stamp, timeout=Duration(seconds=0.0)
                )
            except TransformException:
                self.counts["tf_lookup_failures"] += 1
                record[key] = None
            else:
                record[key] = self._transform_record(transform)
                if key == "map_to_base":
                    record["robot_yaw_rad"] = quaternion_yaw(
                        transform.transform.rotation
                    )
        return record

    def _save_image(
        self,
        message: Image,
        directory: Path,
        prefix: str,
        *,
        lossless: bool,
    ):
        stamp_ns = stamp_nanoseconds(message.header.stamp)
        suffix = ".png" if lossless else ".jpg"
        path = directory / f"{prefix}_{stamp_ns}{suffix}"
        try:
            image = self.bridge.imgmsg_to_cv2(message, desired_encoding="bgr8")
            parameters = (
                [cv2.IMWRITE_PNG_COMPRESSION, 1]
                if lossless else
                [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
            )
            ok = cv2.imwrite(str(path), image, parameters)
        except (CvBridgeError, cv2.error, TypeError, ValueError):
            ok = False
        if not ok:
            self.counts["image_write_failures"] += 1
            return None, None
        return path, self._frame_context(message)

    def _manifest_record(self, kind: str, message: Image, path: Path, context):
        record = {
            "kind": kind,
            "stamp_ns": stamp_nanoseconds(message.header.stamp),
            "path": str(path.resolve()),
            "width": message.width,
            "height": message.height,
            "encoding": message.encoding,
        }
        record.update(context)
        self.manifest.write(json.dumps(record, separators=(",", ":")) + "\n")

    def _raw_callback(self, message: Image) -> None:
        self.counts["raw_messages"] += 1
        stamp_ns = stamp_nanoseconds(message.header.stamp)
        self.raw_cache[stamp_ns] = message
        self.raw_cache.move_to_end(stamp_ns)
        while len(self.raw_cache) > self.cache_limit:
            self.raw_cache.popitem(last=False)
        if not self.active:
            return
        if (
            self.last_periodic_stamp_ns is not None
            and stamp_ns - self.last_periodic_stamp_ns < self.capture_period_ns
        ):
            return
        path, context = self._save_image(
            message, self.raw_dir, "raw", lossless=True
        )
        if path is None:
            return
        self.last_periodic_stamp_ns = stamp_ns
        self.saved_periodic_stamps.add(stamp_ns)
        self.counts["raw_periodic_saved"] += 1
        self._manifest_record("raw_periodic", message, path, context)

    def _depth_callback(self, message: Image) -> None:
        """Cache bounded synchronized depth without publishing or deciding."""
        self.counts["depth_messages"] += 1
        stamp_ns = stamp_nanoseconds(message.header.stamp)
        self.depth_cache[stamp_ns] = message
        self.depth_cache.move_to_end(stamp_ns)
        while len(self.depth_cache) > self.cache_limit:
            self.depth_cache.popitem(last=False)

    def _nearest_depth(self, stamp_ns: int):
        if not self.depth_cache:
            return None
        nearest_stamp = min(
            self.depth_cache,
            key=lambda candidate: abs(candidate - stamp_ns),
        )
        if abs(nearest_stamp - stamp_ns) > 50_000_000:
            return None
        return self.depth_cache[nearest_stamp]

    def _save_depth(self, message: Image, rgb_stamp_ns: int):
        """Persist millimetre uint16 depth for offline diagnostics only."""
        depth_stamp_ns = stamp_nanoseconds(message.header.stamp)
        path = self.runtime_depth_dir / f"runtime_depth_{rgb_stamp_ns}.png"
        try:
            depth = self.bridge.imgmsg_to_cv2(
                message, desired_encoding="passthrough"
            )
            depth_mm = np.zeros(depth.shape, dtype=np.uint16)
            if np.issubdtype(depth.dtype, np.integer):
                valid = (depth > 0) & (depth < np.iinfo(np.uint16).max)
                depth_mm[valid] = depth[valid].astype(np.uint16)
            else:
                valid = np.isfinite(depth) & (depth > 0.0) & (depth < 65.535)
                depth_mm[valid] = np.rint(depth[valid] * 1000.0).astype(
                    np.uint16
                )
            ok = cv2.imwrite(
                str(path), depth_mm, [cv2.IMWRITE_PNG_COMPRESSION, 1]
            )
        except (CvBridgeError, cv2.error, TypeError, ValueError):
            ok = False
        if not ok:
            self.counts["image_write_failures"] += 1
            return
        self.counts["runtime_depth_saved"] += 1
        record = {
            "kind": "runtime_depth",
            "stamp_ns": depth_stamp_ns,
            "rgb_stamp_ns": rgb_stamp_ns,
            "path": str(path.resolve()),
            "width": message.width,
            "height": message.height,
            "encoding": "16UC1",
            "source_encoding": message.encoding,
            "depth_scale_m": 0.001,
            "frame_id": message.header.frame_id,
        }
        self.manifest.write(json.dumps(record, separators=(",", ":")) + "\n")

    def _annotated_callback(self, message: Image) -> None:
        if not self.active:
            return
        stamp_ns = stamp_nanoseconds(message.header.stamp)
        path, context = self._save_image(
            message, self.annotated_dir, "annotated", lossless=False
        )
        if path is not None:
            self.counts["runtime_annotated_saved"] += 1
            self._manifest_record("runtime_annotated", message, path, context)
        if stamp_ns in self.runtime_stamps:
            return
        self.runtime_stamps.add(stamp_ns)
        raw_message = self.raw_cache.get(stamp_ns)
        if raw_message is None:
            self.counts["runtime_raw_missing"] += 1
            return
        raw_path, raw_context = self._save_image(
            raw_message, self.runtime_raw_dir, "runtime_raw", lossless=True
        )
        if raw_path is None:
            return
        self.counts["runtime_raw_saved"] += 1
        self._manifest_record("runtime_raw", raw_message, raw_path, raw_context)
        depth_message = self._nearest_depth(stamp_ns)
        if depth_message is None:
            self.counts["runtime_depth_missing"] += 1
        else:
            self._save_depth(depth_message, stamp_ns)

    def close(self) -> None:
        self._event("capture_stopped", active=self.active)
        self.manifest.close()
        self.events.close()
        elapsed = time.monotonic() - self.started_monotonic
        self._write_json(
            self.output_dir / "capture_summary.json",
            {
                "schema_version": 1,
                "elapsed_wall_seconds": elapsed,
                "final_step": self.step,
                "final_phase": self.phase,
                "final_viewpoint_index": self.viewpoint_index,
                "final_viewpoint_total": self.viewpoint_total,
                "counts": self.counts,
            },
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--capture-hz", type=float, default=10.0)
    parser.add_argument("--jpeg-quality", type=int, default=90)
    parser.add_argument("--stop-file", type=Path)
    args = parser.parse_args(argv)
    if args.capture_hz <= 0.0 or not math.isfinite(args.capture_hz):
        parser.error("--capture-hz must be positive and finite")
    if not 1 <= args.jpeg_quality <= 100:
        parser.error("--jpeg-quality must be in [1, 100]")
    if args.output_dir.exists():
        parser.error(f"output directory already exists: {args.output_dir}")
    args.output_dir.mkdir(parents=True)
    rclpy.init()
    node = VisibilityCapture(args.output_dir, args.capture_hz, args.jpeg_quality)
    try:
        while rclpy.ok():
            if args.stop_file is not None and args.stop_file.exists():
                break
            rclpy.spin_once(node, timeout_sec=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        node.close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
