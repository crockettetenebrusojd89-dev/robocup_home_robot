"""Start slam_toolbox for the already running simulated robot."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    """Start only the asynchronous SLAM node with simulation time."""
    package_share = get_package_share_directory('robocup_home_robot')
    slam_params_file = os.path.join(
        package_share,
        'config',
        'mapper_params_online_async.yaml',
    )

    return LaunchDescription([
        Node(
            package='slam_toolbox',
            executable='async_slam_toolbox_node',
            name='slam_toolbox',
            output='screen',
            parameters=[slam_params_file, {'use_sim_time': True}],
        ),
    ])
