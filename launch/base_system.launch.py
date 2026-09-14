"""Start the stable navigation stack and the RGB-D vision localizer."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    IncludeLaunchDescription,
    LogInfo,
    RegisterEventHandler,
)
from launch.conditions import IfCondition, UnlessCondition
from launch.event_handlers import OnProcessExit
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    """Reuse navigation bringup, then start vision when its inputs are ready."""
    robot_share = get_package_share_directory('robocup_home_robot')
    start_vision = LaunchConfiguration('start_vision')

    navigation_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(robot_share, 'launch', 'navigation.launch.py')
        ),
        launch_arguments={
            'world_file': LaunchConfiguration('world_file'),
            'world_name': LaunchConfiguration('world_name'),
        }.items(),
    )

    wait_for_vision = ExecuteProcess(
        cmd=[
            os.path.join(
                robot_share,
                'lib',
                'robocup_home_robot',
                'wait_for_vision_ready.py',
            )
        ],
        name='wait_for_vision_ready',
        output='screen',
        condition=IfCondition(start_vision),
    )

    vision_localizer = Node(
        package='robocup_home_robot',
        executable='rgbd_object_localizer',
        name='rgbd_object_localizer',
        output='screen',
    )

    def start_localizer_after_inputs(event, _context):
        if event.returncode != 0:
            return [
                LogInfo(
                    msg=(
                        'Vision readiness check failed; '
                        'rgbd_object_localizer was not started. '
                        'Navigation remains available for diagnosis.'
                    )
                )
            ]
        return [
            LogInfo(
                msg=(
                    'RGB-D topics and camera TF are ready; starting the '
                    'combined YOLO + RGB-D object localizer.'
                )
            ),
            vision_localizer,
        ]

    return LaunchDescription([
        DeclareLaunchArgument(
            'world_file',
            default_value='',
            description='Optional competition .world path; empty uses example.',
        ),
        DeclareLaunchArgument(
            'world_name',
            default_value='robocup_home',
            description='Gazebo world name inside the supplied file.',
        ),
        DeclareLaunchArgument(
            'start_vision',
            default_value='true',
            description='Start the combined YOLO and RGB-D localizer.',
        ),
        LogInfo(
            msg=(
                'Starting the selected world, one robot, Nav2, AMCL, RViz, '
                'and the vision readiness check. No motion task is started.'
            )
        ),
        LogInfo(
            msg=(
                'Vision disabled: navigation will start without the RGB-D '
                'object localizer.'
            ),
            condition=UnlessCondition(start_vision),
        ),
        navigation_launch,
        RegisterEventHandler(
            OnProcessExit(
                target_action=wait_for_vision,
                on_exit=start_localizer_after_inputs,
            )
        ),
        wait_for_vision,
    ])
