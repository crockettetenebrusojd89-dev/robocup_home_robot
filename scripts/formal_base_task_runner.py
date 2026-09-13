#!/usr/bin/env python3
"""Run the existing navigation, scan, and answer-save stages exactly once."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time

import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from std_srvs.srv import Trigger

from formal_runtime_config import validate_answer_document
from go_to_living_room import GoToLivingRoom
from scan_living_room import ScanLivingRoom


SAVE_SERVICE = '/vision/save_answer'


class FormalBaseTaskRunner(Node):
    """Coordinate already-tested task nodes and verify their saved answer."""

    def __init__(self):
        super().__init__(
            'formal_base_task_runner',
            parameter_overrides=[Parameter('use_sim_time', value=True)],
        )
        self.declare_parameter(
            'target_classes',
            Parameter.Type.STRING_ARRAY,
        )
        self.declare_parameter('group_number', -1)
        self.declare_parameter(
            'answer_output_dir',
            str(Path.home() / 'robocup_assets/submissions'),
        )
        self.declare_parameter('save_service_wait_seconds', 60.0)

        self.target_classes = tuple(
            str(value)
            for value in self.get_parameter('target_classes').value
        )
        self.group_number = int(self.get_parameter('group_number').value)
        self.answer_output_dir = Path(
            self.get_parameter('answer_output_dir').value
        ).expanduser()
        self.save_service_wait_seconds = float(
            self.get_parameter('save_service_wait_seconds').value
        )
        self._validate_parameters()
        self._save_client = self.create_client(Trigger, SAVE_SERVICE)

    @property
    def answer_path(self):
        """Return the one output path owned by this run."""
        return self.answer_output_dir / f'{self.group_number}_answer.json'

    def _validate_parameters(self):
        if len(self.target_classes) != 3:
            raise RuntimeError('Exactly three target_classes are required.')
        if any(not value for value in self.target_classes):
            raise RuntimeError('target_classes must not contain empty names.')
        if len(set(self.target_classes)) != 3:
            raise RuntimeError('target_classes must be distinct.')
        if self.group_number <= 0:
            raise RuntimeError('group_number must be a positive integer.')
        if self.save_service_wait_seconds <= 0.0:
            raise RuntimeError('save_service_wait_seconds must be positive.')
        if self.answer_path.exists():
            raise RuntimeError(
                f'Answer already exists; refusing to overwrite: {self.answer_path}'
            )

    def _save_answer(self):
        self.get_logger().info(f'Waiting for {SAVE_SERVICE}...')
        deadline = time.monotonic() + self.save_service_wait_seconds
        while rclpy.ok() and time.monotonic() < deadline:
            if self._save_client.wait_for_service(timeout_sec=1.0):
                break
        else:
            self.get_logger().error(
                f'{SAVE_SERVICE} was not ready within '
                f'{self.save_service_wait_seconds:.1f} seconds.'
            )
            return 1

        future = self._save_client.call_async(Trigger.Request())
        remaining = max(0.0, deadline - time.monotonic())
        rclpy.spin_until_future_complete(self, future, timeout_sec=remaining)
        if not future.done():
            self.get_logger().error('Timed out waiting for answer save response.')
            return 1
        if future.exception() is not None:
            self.get_logger().error(
                f'Answer save service failed: {future.exception()}'
            )
            return 1
        response = future.result()
        if response is None or not response.success:
            message = response.message if response is not None else 'no response'
            self.get_logger().error(f'Answer save rejected: {message}')
            return 1
        self.get_logger().info(response.message)

        try:
            document = json.loads(self.answer_path.read_text(encoding='utf-8'))
            counts = validate_answer_document(document, self.target_classes)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            self.get_logger().error(f'Saved answer verification failed: {error}')
            return 1

        lines = ['Formal base task completed:', *[
            f'{class_name}: {counts[class_name]}'
            for class_name in self.target_classes
        ], f'Answer JSON: {self.answer_path}']
        self.get_logger().info('\n'.join(lines))
        return 0

    def run(self):
        """Run each stage serially and stop immediately on the first failure."""
        self.get_logger().info(
            'Formal base-task runner starting; '
            f'targets={list(self.target_classes)}; '
            f'group_number={self.group_number}'
        )

        navigation = GoToLivingRoom()
        try:
            navigation_result = navigation.navigate()
        finally:
            navigation.destroy_node()
        if navigation_result != 0:
            self.get_logger().error(
                f'Navigation stage failed with code {navigation_result}.'
            )
            return navigation_result

        scan = ScanLivingRoom()
        try:
            scan_result = scan.scan()
        finally:
            scan.destroy_node()
        if scan_result != 0:
            self.get_logger().error(f'Scan stage failed with code {scan_result}.')
            return scan_result

        return self._save_answer()


def main():
    rclpy.init()
    node = None
    try:
        node = FormalBaseTaskRunner()
        return node.run()
    except KeyboardInterrupt:
        if node is not None:
            node.get_logger().warning('Formal base task interrupted.')
        return 130
    except Exception as error:
        print(f'[formal_base_task_runner] Failed: {error}', file=sys.stderr)
        return 1
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    sys.exit(main())
