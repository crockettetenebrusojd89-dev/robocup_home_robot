#!/usr/bin/env python3
"""Expose baked Gazebo FR3 joint zeros as the original URDF joint angles."""

import os
import subprocess
import xml.etree.ElementTree as ET

from ament_index_python.packages import get_package_share_directory
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState


def _stowed_offsets():
    package_share = get_package_share_directory('robocup_home_robot')
    xacro_file = os.path.join(package_share, 'urdf', 'robot.urdf.xacro')
    result = subprocess.run(
        ['xacro', xacro_file],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    root = ET.fromstring(result.stdout)
    offsets = {}
    for gazebo in root.findall('gazebo'):
        joint_name = gazebo.get('reference', '')
        reference = gazebo.find('springReference')
        if joint_name.startswith('fr3_') and reference is not None:
            offsets[joint_name] = float(reference.text)
    if not offsets:
        raise RuntimeError('No FR3 passive joint references were found')
    return offsets


class OffsetJointStates(Node):
    """Relay Gazebo joint states with the baked stowed offsets restored."""

    def __init__(self):
        super().__init__('offset_joint_states')
        self.declare_parameter('apply_stowed_offsets', True)
        self._offsets = (
            _stowed_offsets()
            if bool(self.get_parameter('apply_stowed_offsets').value)
            else {}
        )
        self._publisher = self.create_publisher(JointState, '/joint_states', 10)
        self.create_subscription(
            JointState,
            '/gazebo_joint_states',
            self._relay,
            10,
        )
        self.get_logger().info(
            f'Relaying complete Gazebo joint state; restoring offsets for '
            f'{len(self._offsets)} FR3 joints'
        )

    def _relay(self, message):
        output = JointState()
        output.header = message.header
        output.name = list(message.name)
        output.position = [
            position + self._offsets.get(name, 0.0)
            for name, position in zip(message.name, message.position)
        ]
        output.velocity = list(message.velocity)
        output.effort = list(message.effort)
        self._publisher.publish(output)


def main(args=None):
    rclpy.init(args=args)
    node = OffsetJointStates()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    try:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
