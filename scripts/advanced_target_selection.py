"""Pure target-quality checks shared by the advanced ROS node and unit test."""

import math


def detection_candidate(detection, image_width, image_height, edge_margin_pixels):
    """Return a comparable valid candidate or None for unusable detections."""
    if not detection.results or image_width <= 0 or image_height <= 0:
        return None
    result = detection.results[0]
    class_name = result.hypothesis.class_id
    confidence = float(result.hypothesis.score)
    point = result.pose.pose.position
    center = detection.bbox.center.position
    width = float(detection.bbox.size_x)
    height = float(detection.bbox.size_y)
    values = (
        confidence,
        point.x,
        point.y,
        point.z,
        center.x,
        center.y,
        width,
        height,
    )
    if not class_name or not all(math.isfinite(value) for value in values):
        return None
    if width <= 0.0 or height <= 0.0 or point.z <= 0.0:
        return None
    x1 = center.x - width * 0.5
    y1 = center.y - height * 0.5
    x2 = center.x + width * 0.5
    y2 = center.y + height * 0.5
    if (
        x1 < edge_margin_pixels
        or y1 < edge_margin_pixels
        or x2 > image_width - edge_margin_pixels
        or y2 > image_height - edge_margin_pixels
    ):
        return None
    return {
        'class_name': class_name,
        'confidence': confidence,
        'x1': x1,
        'y1': y1,
        'x2': x2,
        'y2': y2,
        'area': width * height,
        'point': point,
    }
