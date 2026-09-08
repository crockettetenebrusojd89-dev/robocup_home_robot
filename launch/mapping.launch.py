"""Start the competition world, robot, SLAM, and RViz for manual mapping."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    EmitEvent,
    ExecuteProcess,
    IncludeLaunchDescription,
    LogInfo,
    RegisterEventHandler,
)
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node


def generate_launch_description():
    """Launch each existing subsystem once, after Gazebo reports world readiness."""
    robot_share = get_package_share_directory('robocup_home_robot')
    world_share = get_package_share_directory('wpr_simulation_ros2')

    world_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(world_share, 'launch', 'world.launch.py')
        ),
        launch_arguments={'world_type': 'example'}.items(),
    )

    spawn_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(robot_share, 'launch', 'spawn_robot.launch.py')
        ),
    )

    slam_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(robot_share, 'launch', 'slam.launch.py')
        ),
    )

    rviz = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        output='screen',
        arguments=[
            '-d',
            os.path.join(robot_share, 'config', 'mapping.rviz'),
        ],
        parameters=[{'use_sim_time': True}],
    )

    wait_for_world = ExecuteProcess(
        cmd=[
            os.path.join(
                robot_share,
                'lib',
                'robocup_home_robot',
                'wait_for_gazebo_world.py',
            )
        ],
        name='wait_for_gazebo_world',
        output='screen',
    )

    wait_for_robot = ExecuteProcess(
        cmd=[
            os.path.join(
                robot_share,
                'lib',
                'robocup_home_robot',
                'wait_for_gazebo_robot.py',
            )
        ],
        name='wait_for_gazebo_robot',
        output='screen',
    )

    def start_mapping_stack(event, _context):
        if event.returncode != 0:
            return [
                LogInfo(msg='Gazebo world readiness check failed; mapping stack not started.'),
                EmitEvent(event=Shutdown(reason='Gazebo world did not become ready')),
            ]
        return [
            LogInfo(msg='Gazebo world is ready; spawning the robot once.'),
            spawn_launch,
            wait_for_robot,
        ]

    def start_slam_and_rviz(event, _context):
        if event.returncode != 0:
            return [
                LogInfo(msg='Robot readiness check failed; SLAM and RViz not started.'),
                EmitEvent(event=Shutdown(reason='Robot interfaces did not become ready')),
            ]
        return [
            LogInfo(msg='Robot interfaces are ready; starting SLAM and RViz once.'),
            slam_launch,
            rviz,
        ]

    start_after_world_ready = RegisterEventHandler(
        OnProcessExit(
            target_action=wait_for_world,
            on_exit=start_mapping_stack,
        )
    )

    start_after_robot_ready = RegisterEventHandler(
        OnProcessExit(
            target_action=wait_for_robot,
            on_exit=start_slam_and_rviz,
        )
    )

    return LaunchDescription([
        world_launch,
        start_after_world_ready,
        start_after_robot_ready,
        wait_for_world,
    ])
