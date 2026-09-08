#!/usr/bin/env python3
"""Navigate once to a verified safe viewpoint for far-object reinspection."""

from dataclasses import dataclass
import json
import math
import os
import sys
import threading
import time

from action_msgs.msg import GoalStatus
from ament_index_python.packages import get_package_share_directory
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.duration import Duration
from rclpy.executors import MultiThreadedExecutor
import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.time import Time
from std_srvs.srv import Trigger
from tf2_ros import Buffer, TransformException, TransformListener
import yaml


ACTION_SERVER = '/navigate_to_pose'
CLUSTER_SERVICE = '/vision/get_clusters'
BASE_FRAME = 'base_link'
SERVER_WAIT_ATTEMPTS = 30
SERVICE_RESPONSE_TIMEOUT = 10.0
GOAL_RESPONSE_TIMEOUT = 10.0
NAVIGATION_RESULT_TIMEOUT = 120.0
CANCEL_RESPONSE_TIMEOUT = 5.0


@dataclass(frozen=True)
class VisualCluster:
    """One confirmed cluster returned by the visual localizer."""

    cluster_id: int
    class_name: str
    x: float
    y: float
    z: float
    observations: int


@dataclass(frozen=True)
class SafeViewpoint:
    """One map-frame robot standing position verified by the user."""

    name: str
    x: float
    y: float


@dataclass(frozen=True)
class ViewpointEvaluation:
    """Target and travel distances for one safe viewpoint."""

    viewpoint: SafeViewpoint
    target_distance: float
    robot_travel_distance: float


class ReinspectFarObject(Node):
    """Select the farthest visual target and send one Nav2 goal."""

    def __init__(self):
        super().__init__(
            'reinspect_far_object',
            parameter_overrides=[Parameter('use_sim_time', value=True)],
        )
        self.declare_parameter('target_class', 'apple')
        self.declare_parameter('reinspect_distance_threshold', 1.50)
        default_viewpoints_file = os.path.join(
            get_package_share_directory('robocup_home_robot'),
            'config',
            'living_room_viewpoints.yaml',
        )
        self.declare_parameter('viewpoints_file', default_viewpoints_file)
        self.declare_parameter('ideal_target_distance_min', 1.0)
        self.declare_parameter('ideal_target_distance_max', 1.5)
        self.declare_parameter('preferred_target_distance', 1.25)
        self.declare_parameter('max_target_view_distance', 2.0)
        self.declare_parameter('dwell_seconds', 3.0)
        self.declare_parameter('target_frame', 'map')

        self.target_class = str(self.get_parameter('target_class').value)
        self.reinspect_distance_threshold = float(
            self.get_parameter('reinspect_distance_threshold').value
        )
        self.viewpoints_file = str(
            self.get_parameter('viewpoints_file').value
        )
        self.ideal_target_distance_min = float(
            self.get_parameter('ideal_target_distance_min').value
        )
        self.ideal_target_distance_max = float(
            self.get_parameter('ideal_target_distance_max').value
        )
        self.preferred_target_distance = float(
            self.get_parameter('preferred_target_distance').value
        )
        self.max_target_view_distance = float(
            self.get_parameter('max_target_view_distance').value
        )
        self.dwell_seconds = float(
            self.get_parameter('dwell_seconds').value
        )
        self.target_frame = str(self.get_parameter('target_frame').value)
        self.use_sim_time = bool(self.get_parameter('use_sim_time').value)
        self._validate_parameters()
        self.safe_viewpoints = self._load_viewpoints(self.viewpoints_file)

        self._cluster_client = self.create_client(Trigger, CLUSTER_SERVICE)
        self._action_client = ActionClient(
            self,
            NavigateToPose,
            ACTION_SERVER,
        )
        self._tf_buffer = Buffer(
            cache_time=Duration(seconds=10.0),
            node=self,
        )
        self._tf_listener = TransformListener(self._tf_buffer, self)
        self._stop_requested = threading.Event()
        self._active_goal_handle = None

    def _validate_parameters(self):
        if not self.target_class:
            raise RuntimeError('target_class must not be empty.')
        if not self.target_frame:
            raise RuntimeError('target_frame must not be empty.')
        if not self.use_sim_time:
            raise RuntimeError('use_sim_time must be true for Gazebo navigation.')
        if (
            not math.isfinite(self.reinspect_distance_threshold)
            or self.reinspect_distance_threshold < 0.0
        ):
            raise RuntimeError(
                'reinspect_distance_threshold must be finite and non-negative.'
            )
        if not self.viewpoints_file:
            raise RuntimeError('viewpoints_file must not be empty.')
        distances = (
            self.ideal_target_distance_min,
            self.ideal_target_distance_max,
            self.preferred_target_distance,
            self.max_target_view_distance,
        )
        if not all(math.isfinite(value) and value > 0.0 for value in distances):
            raise RuntimeError(
                'viewpoint distance parameters must be finite and positive.'
            )
        if self.ideal_target_distance_min > self.ideal_target_distance_max:
            raise RuntimeError(
                'ideal_target_distance_min cannot exceed '
                'ideal_target_distance_max.'
            )
        if not (
            self.ideal_target_distance_min
            <= self.preferred_target_distance
            <= self.ideal_target_distance_max
        ):
            raise RuntimeError(
                'preferred_target_distance must be inside the ideal range.'
            )
        if self.max_target_view_distance < self.ideal_target_distance_max:
            raise RuntimeError(
                'max_target_view_distance cannot be below the ideal maximum.'
            )
        if not math.isfinite(self.dwell_seconds) or self.dwell_seconds < 0.0:
            raise RuntimeError('dwell_seconds must be finite and non-negative.')

    @staticmethod
    def _load_viewpoints(path):
        try:
            with open(path, encoding='utf-8') as stream:
                document = yaml.safe_load(stream)
        except (OSError, yaml.YAMLError) as error:
            raise RuntimeError(
                f'Could not load safe viewpoints from {path}: {error}'
            ) from error

        if not isinstance(document, dict) or set(document) != {'viewpoints'}:
            raise RuntimeError(
                'Viewpoint YAML must contain only the viewpoints key.'
            )
        raw_viewpoints = document['viewpoints']
        if not isinstance(raw_viewpoints, list) or not raw_viewpoints:
            raise RuntimeError('Viewpoint YAML must contain a non-empty list.')

        viewpoints = []
        names = set()
        for index, raw in enumerate(raw_viewpoints):
            location = f'viewpoints[{index}]'
            if not isinstance(raw, dict) or set(raw) != {'name', 'x', 'y'}:
                raise RuntimeError(
                    f'{location} must contain exactly name, x, and y.'
                )
            name = raw['name']
            if not isinstance(name, str) or not name:
                raise RuntimeError(f'{location}.name must be a non-empty string.')
            if name in names:
                raise RuntimeError(f'Duplicate safe viewpoint name: {name}')

            coordinates = []
            for axis in ('x', 'y'):
                value = raw[axis]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise RuntimeError(f'{location}.{axis} must be numeric.')
                value = float(value)
                if not math.isfinite(value):
                    raise RuntimeError(f'{location}.{axis} must be finite.')
                coordinates.append(value)

            viewpoints.append(
                SafeViewpoint(name=name, x=coordinates[0], y=coordinates[1])
            )
            names.add(name)
        return viewpoints

    def _wait_for_future(self, future, timeout_seconds):
        """Wait while the node's already-running executor handles callbacks."""
        done = threading.Event()
        future.add_done_callback(lambda _future: done.set())
        deadline = time.monotonic() + timeout_seconds
        while (
            rclpy.ok()
            and not self._stop_requested.is_set()
            and not future.done()
        ):
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                return False
            done.wait(timeout=min(0.1, remaining))
        return future.done()

    @staticmethod
    def _cancel_accepted(cancel_response):
        return (
            cancel_response is not None
            and bool(cancel_response.goals_canceling)
        )

    def _cancel_goal_and_wait(self, goal_handle, reason):
        self.get_logger().warning(f'{reason}; requesting goal cancellation.')
        cancel_future = goal_handle.cancel_goal_async()
        if not self._wait_for_future(cancel_future, CANCEL_RESPONSE_TIMEOUT):
            self.get_logger().error('Timed out waiting for goal cancellation.')
            return False
        if cancel_future.exception() is not None:
            self.get_logger().error(
                f'Goal cancellation failed: {cancel_future.exception()}'
            )
            return False
        if not self._cancel_accepted(cancel_future.result()):
            self.get_logger().error('NavigateToPose did not accept cancellation.')
            return False
        self.get_logger().info('NavigateToPose cancellation accepted.')
        return True

    def request_stop(self):
        """Stop local waits and request cancellation of any accepted goal."""
        self._stop_requested.set()
        goal_handle = self._active_goal_handle
        if goal_handle is None:
            return None
        self.get_logger().warning(
            'Shutdown requested while NavigateToPose is active; canceling goal.'
        )
        return goal_handle.cancel_goal_async()

    def _wait_for_cluster_service(self):
        self.get_logger().info(f'Waiting for {CLUSTER_SERVICE}...')
        for attempt in range(1, SERVER_WAIT_ATTEMPTS + 1):
            if self._cluster_client.wait_for_service(timeout_sec=1.0):
                return True
            if attempt % 5 == 0:
                self.get_logger().info(
                    f'Still waiting for {CLUSTER_SERVICE}...'
                )
            if not rclpy.ok():
                return False
        self.get_logger().error(
            f'{CLUSTER_SERVICE} was unavailable after '
            f'{SERVER_WAIT_ATTEMPTS} seconds.'
        )
        return False

    @staticmethod
    def _parse_cluster_message(message):
        try:
            document = json.loads(message)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError(f'invalid cluster JSON: {error}') from error
        if not isinstance(document, dict) or set(document) != {'objects'}:
            raise ValueError('cluster response must contain only objects.')
        raw_objects = document['objects']
        if not isinstance(raw_objects, list):
            raise ValueError('cluster response objects must be an array.')

        expected_keys = {
            'cluster_id',
            'class_name',
            'x',
            'y',
            'z',
            'observations',
        }
        clusters = []
        for index, raw in enumerate(raw_objects):
            location = f'objects[{index}]'
            if not isinstance(raw, dict) or set(raw) != expected_keys:
                raise ValueError(f'{location} has invalid fields.')
            cluster_id = raw['cluster_id']
            observations = raw['observations']
            class_name = raw['class_name']
            if isinstance(cluster_id, bool) or not isinstance(cluster_id, int):
                raise ValueError(f'{location}.cluster_id must be an integer.')
            if (
                isinstance(observations, bool)
                or not isinstance(observations, int)
                or observations < 1
            ):
                raise ValueError(
                    f'{location}.observations must be a positive integer.'
                )
            if not isinstance(class_name, str) or not class_name:
                raise ValueError(f'{location}.class_name must be non-empty.')
            coordinates = []
            for axis in ('x', 'y', 'z'):
                value = raw[axis]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f'{location}.{axis} must be numeric.')
                value = float(value)
                if not math.isfinite(value):
                    raise ValueError(f'{location}.{axis} must be finite.')
                coordinates.append(value)
            clusters.append(
                VisualCluster(
                    cluster_id=cluster_id,
                    class_name=class_name,
                    x=coordinates[0],
                    y=coordinates[1],
                    z=coordinates[2],
                    observations=observations,
                )
            )
        return clusters

    def _get_clusters(self):
        if not self._wait_for_cluster_service():
            return None
        future = self._cluster_client.call_async(Trigger.Request())
        if not self._wait_for_future(future, SERVICE_RESPONSE_TIMEOUT):
            future.cancel()
            self.get_logger().error(
                'Cluster service did not reply within '
                f'{SERVICE_RESPONSE_TIMEOUT:.1f} seconds.'
            )
            return None
        if future.exception() is not None:
            self.get_logger().error(
                f'Cluster service call failed: {future.exception()}'
            )
            return None
        response = future.result()
        if response is None or not response.success:
            message = response.message if response is not None else 'no response'
            self.get_logger().error(f'Cluster service rejected request: {message}')
            return None
        try:
            return self._parse_cluster_message(response.message)
        except ValueError as error:
            self.get_logger().error(f'Cluster service returned invalid data: {error}')
            return None

    def _current_robot_position(self):
        self.get_logger().info(
            f'Waiting for TF {self.target_frame} -> {BASE_FRAME}...'
        )
        for attempt in range(1, SERVER_WAIT_ATTEMPTS + 1):
            try:
                transform = self._tf_buffer.lookup_transform(
                    self.target_frame,
                    BASE_FRAME,
                    Time(),
                    timeout=Duration(seconds=1.0),
                )
            except TransformException:
                if attempt % 5 == 0:
                    self.get_logger().info(
                        f'Still waiting for TF '
                        f'{self.target_frame} -> {BASE_FRAME}...'
                    )
                continue
            translation = transform.transform.translation
            return float(translation.x), float(translation.y)
        self.get_logger().error(
            f'TF {self.target_frame} -> {BASE_FRAME} was unavailable after '
            f'{SERVER_WAIT_ATTEMPTS} seconds.'
        )
        return None

    @staticmethod
    def _select_farthest(clusters, class_name, robot_x, robot_y):
        candidates = [
            cluster
            for cluster in clusters
            if cluster.class_name == class_name
        ]
        if not candidates:
            return None
        return max(
            (
                (
                    math.hypot(cluster.x - robot_x, cluster.y - robot_y),
                    cluster,
                )
                for cluster in candidates
            ),
            key=lambda item: (item[0], -item[1].cluster_id),
        )

    @staticmethod
    def _evaluate_viewpoints(viewpoints, target_x, target_y, robot_x, robot_y):
        return [
            ViewpointEvaluation(
                viewpoint=viewpoint,
                target_distance=math.hypot(
                    target_x - viewpoint.x,
                    target_y - viewpoint.y,
                ),
                robot_travel_distance=math.hypot(
                    robot_x - viewpoint.x,
                    robot_y - viewpoint.y,
                ),
            )
            for viewpoint in viewpoints
        ]

    @staticmethod
    def _select_safe_viewpoint(
        evaluations,
        ideal_distance_min,
        ideal_distance_max,
        preferred_distance,
        maximum_distance,
    ):
        ideal = [
            evaluation
            for evaluation in evaluations
            if ideal_distance_min
            <= evaluation.target_distance
            <= ideal_distance_max
        ]
        if ideal:
            return min(
                ideal,
                key=lambda item: (
                    item.robot_travel_distance,
                    item.target_distance,
                    item.viewpoint.name,
                ),
            ), 'ideal range'

        allowed = [
            evaluation
            for evaluation in evaluations
            if evaluation.target_distance <= maximum_distance
        ]
        if not allowed:
            return None, 'no safe viewpoint is within the maximum distance'
        return min(
            allowed,
            key=lambda item: (
                abs(item.target_distance - preferred_distance),
                item.robot_travel_distance,
                item.viewpoint.name,
            ),
        ), 'closest to preferred distance'

    @staticmethod
    def _viewpoint_yaw(viewpoint, target_x, target_y):
        return math.atan2(target_y - viewpoint.y, target_x - viewpoint.x)

    def _log_viewpoints(self, evaluations):
        lines = ['Safe viewpoints:']
        for evaluation in evaluations:
            lines.extend([
                f'{evaluation.viewpoint.name}:',
                f'  target_distance={evaluation.target_distance:.3f} m',
                '  robot_travel_distance='
                f'{evaluation.robot_travel_distance:.3f} m',
            ])
        self.get_logger().info('\n'.join(lines))

    def _wait_for_action_server(self):
        self.get_logger().info('Waiting for NavigateToPose action server...')
        for attempt in range(1, SERVER_WAIT_ATTEMPTS + 1):
            if self._action_client.wait_for_server(timeout_sec=1.0):
                return True
            if attempt % 5 == 0:
                self.get_logger().info(
                    'Still waiting for NavigateToPose action server...'
                )
            if not rclpy.ok():
                return False
        self.get_logger().error(
            'NavigateToPose action server was unavailable after '
            f'{SERVER_WAIT_ATTEMPTS} seconds.'
        )
        return False

    def _navigate(self, x, y, yaw):
        if not self._wait_for_action_server():
            return False

        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = self.target_frame
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x = x
        goal.pose.pose.position.y = y
        goal.pose.pose.orientation.z = math.sin(yaw / 2.0)
        goal.pose.pose.orientation.w = math.cos(yaw / 2.0)

        self.get_logger().info('Sending NavigateToPose...')
        send_future = self._action_client.send_goal_async(goal)
        if not self._wait_for_future(send_future, GOAL_RESPONSE_TIMEOUT):
            send_future.cancel()
            self.get_logger().error(
                'NavigateToPose did not answer the goal request within '
                f'{GOAL_RESPONSE_TIMEOUT:.1f} seconds.'
            )
            return False
        if send_future.exception() is not None:
            self.get_logger().error(
                f'Failed to send NavigateToPose goal: {send_future.exception()}'
            )
            return False

        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            self.get_logger().error('NavigateToPose goal was rejected.')
            return False

        self._active_goal_handle = goal_handle
        self.get_logger().info(
            'Goal accepted: navigating to the selected safe viewpoint.'
        )
        result_future = goal_handle.get_result_async()
        if not self._wait_for_future(
            result_future,
            NAVIGATION_RESULT_TIMEOUT,
        ):
            if not self._stop_requested.is_set():
                self._cancel_goal_and_wait(
                    goal_handle,
                    'NavigateToPose exceeded '
                    f'{NAVIGATION_RESULT_TIMEOUT:.1f} seconds',
                )
            self._active_goal_handle = None
            return False
        self._active_goal_handle = None
        if result_future.exception() is not None:
            self.get_logger().error(
                f'Failed while waiting for navigation result: '
                f'{result_future.exception()}'
            )
            return False

        wrapped_result = result_future.result()
        if wrapped_result is None:
            self.get_logger().error('Navigation ended without an action result.')
            return False
        if wrapped_result.status == GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().info('Observation pose reached.')
            return True
        if wrapped_result.status == GoalStatus.STATUS_CANCELED:
            self.get_logger().warning('NavigateToPose goal was canceled.')
            return False

        status_name = {
            GoalStatus.STATUS_UNKNOWN: 'UNKNOWN',
            GoalStatus.STATUS_ACCEPTED: 'ACCEPTED',
            GoalStatus.STATUS_EXECUTING: 'EXECUTING',
            GoalStatus.STATUS_CANCELING: 'CANCELING',
            GoalStatus.STATUS_ABORTED: 'ABORTED',
        }.get(wrapped_result.status, 'UNRECOGNIZED')
        self.get_logger().error(
            f'NavigateToPose failed. Status: '
            f'{status_name} ({wrapped_result.status}).'
        )
        return False

    def _dwell_using_ros_time(self):
        if self.dwell_seconds == 0.0:
            return True
        start_time = self.get_clock().now()
        dwell_duration = Duration(seconds=self.dwell_seconds)
        while rclpy.ok():
            if self.get_clock().now() - start_time >= dwell_duration:
                return True
            time.sleep(0.1)
        return False

    def _log_before(self, target, distance):
        self.get_logger().info(
            'Before reinspection:\n'
            f'{target.class_name} #{target.cluster_id}\n'
            f'x={target.x:.3f}\n'
            f'y={target.y:.3f}\n'
            f'distance={distance:.3f} m\n'
            f'observations={target.observations}'
        )

    def _log_after(self, before, clusters):
        same_class = sorted(
            (
                cluster
                for cluster in clusters
                if cluster.class_name == before.class_name
            ),
            key=lambda cluster: cluster.cluster_id,
        )
        lines = [f'After reinspection:\n{before.class_name} clusters:']
        for cluster in same_class:
            lines.append(
                f'#{cluster.cluster_id} x={cluster.x:.3f} '
                f'y={cluster.y:.3f} observations={cluster.observations}'
            )
        if not same_class:
            lines.append('none')
        matching = next(
            (
                cluster
                for cluster in same_class
                if cluster.cluster_id == before.cluster_id
            ),
            None,
        )
        if matching is None:
            lines.append(
                f'Original cluster #{before.cluster_id} is no longer present.'
            )
        else:
            displacement = math.hypot(
                matching.x - before.x,
                matching.y - before.y,
            )
            lines.append(
                f'Original cluster position change={displacement:.3f} m; '
                f'observation increase='
                f'{matching.observations - before.observations}'
            )
        self.get_logger().info('\n'.join(lines))

    def run(self):
        self.get_logger().info('Far-object reinspection starting.')
        before_clusters = self._get_clusters()
        if before_clusters is None:
            return 1
        if not any(
            cluster.class_name == self.target_class
            for cluster in before_clusters
        ):
            self.get_logger().error(
                f'No confirmed {self.target_class} clusters are available.'
            )
            return 1

        robot_position = self._current_robot_position()
        if robot_position is None:
            return 1
        robot_x, robot_y = robot_position
        self.get_logger().info(
            f'Current robot:\nx={robot_x:.3f}\ny={robot_y:.3f}'
        )

        selected = self._select_farthest(
            before_clusters,
            self.target_class,
            robot_x,
            robot_y,
        )
        if selected is None:
            self.get_logger().error(
                f'No confirmed {self.target_class} clusters are available.'
            )
            return 1
        distance, target = selected
        self.get_logger().info(
            'Selected target:\n'
            f'class={target.class_name}\n'
            f'cluster_id={target.cluster_id}\n'
            f'x={target.x:.3f}\n'
            f'y={target.y:.3f}\n'
            f'distance={distance:.3f} m'
        )
        self._log_before(target, distance)

        if distance <= self.reinspect_distance_threshold:
            self.get_logger().info(
                'Target is already close enough; reinspection not required.'
            )
            return 0

        evaluations = self._evaluate_viewpoints(
            self.safe_viewpoints,
            target.x,
            target.y,
            robot_x,
            robot_y,
        )
        self._log_viewpoints(evaluations)
        selected_viewpoint, selection_reason = self._select_safe_viewpoint(
            evaluations,
            self.ideal_target_distance_min,
            self.ideal_target_distance_max,
            self.preferred_target_distance,
            self.max_target_view_distance,
        )
        if selected_viewpoint is None:
            self.get_logger().error(
                'No permitted safe viewpoint for the selected target: '
                f'all target distances exceed '
                f'{self.max_target_view_distance:.2f} m. Navigation canceled.'
            )
            return 0
        viewpoint = selected_viewpoint.viewpoint
        yaw = self._viewpoint_yaw(viewpoint, target.x, target.y)
        self.get_logger().info(
            'Selected safe viewpoint:\n'
            f'name={viewpoint.name}\n'
            f'x={viewpoint.x:.3f}\n'
            f'y={viewpoint.y:.3f}\n'
            f'target_distance={selected_viewpoint.target_distance:.3f} m\n'
            'robot_travel_distance='
            f'{selected_viewpoint.robot_travel_distance:.3f} m\n'
            f'yaw={yaw:.3f}\n'
            f'selection={selection_reason}'
        )

        if not self._navigate(viewpoint.x, viewpoint.y, yaw):
            return 1

        self.get_logger().info(
            f'Observing for {self.dwell_seconds:.1f} seconds...'
        )
        if not self._dwell_using_ros_time():
            self.get_logger().error('Reinspection dwell was interrupted.')
            return 1

        after_clusters = self._get_clusters()
        if after_clusters is None:
            return 1
        self._log_after(target, after_clusters)
        self.get_logger().info('Reinspection complete.')
        return 0


def main():
    rclpy.init()
    node = None
    executor = None
    executor_thread = None
    try:
        node = ReinspectFarObject()
        executor = MultiThreadedExecutor(num_threads=2)
        executor.add_node(node)
        executor_thread = threading.Thread(
            target=executor.spin,
            name='reinspect_far_object_executor',
        )
        executor_thread.start()
        node.get_logger().info(
            'use_sim_time=true; using a background 2-thread executor so TF, '
            'service, and action callbacks remain responsive during the '
            'main-thread workflow.'
        )
        return node.run()
    except KeyboardInterrupt:
        if node is not None:
            node.get_logger().warning('Far-object reinspection interrupted by user.')
            cancel_future = node.request_stop()
            if cancel_future is not None:
                if not node._wait_for_future(
                    cancel_future,
                    CANCEL_RESPONSE_TIMEOUT,
                ):
                    node.get_logger().error(
                        'Timed out waiting for shutdown goal cancellation.'
                    )
                elif cancel_future.exception() is not None:
                    node.get_logger().error(
                        'Shutdown goal cancellation failed: '
                        f'{cancel_future.exception()}'
                    )
                elif node._cancel_accepted(cancel_future.result()):
                    node.get_logger().info(
                        'Shutdown goal cancellation accepted.'
                    )
                else:
                    node.get_logger().error(
                        'NavigateToPose did not accept shutdown cancellation.'
                    )
        return 130
    except Exception as error:
        print(f'[reinspect_far_object] Failed to start: {error}', file=sys.stderr)
        return 1
    finally:
        if executor is not None:
            executor.shutdown(timeout_sec=CANCEL_RESPONSE_TIMEOUT)
        if executor_thread is not None:
            executor_thread.join(timeout=CANCEL_RESPONSE_TIMEOUT)
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    sys.exit(main())
