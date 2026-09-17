"""Run the isolated dining-navigation and target-boxing Stage 1 workflow."""

import json
import os
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, EmitEvent, ExecuteProcess
from launch.actions import IncludeLaunchDescription, LogInfo, RegisterEventHandler
from launch.actions import TimerAction
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    """Start a separate all-class perception path without changing base task."""
    robot_share = get_package_share_directory('robocup_home_robot')
    manifest_path = Path(robot_share) / 'config' / 'formal_object_classes.json'
    classes = tuple(
        item['name']
        for item in json.loads(manifest_path.read_text(encoding='utf-8'))['classes']
    )
    navigation = IncludeLaunchDescription(
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
                robot_share, 'lib', 'robocup_home_robot', 'wait_for_vision_ready.py'
            )
        ],
        name='wait_for_vision_ready',
        output='screen',
    )
    localizer = Node(
        package='robocup_home_robot',
        executable='rgbd_object_localizer',
        name='advanced_rgbd_object_localizer',
        output='screen',
        parameters=[{
            'model_path': LaunchConfiguration('model_path'),
            'confidence_threshold': 0.50,
            'target_classes': list(classes),
            'output_image_topic': '/vision/detections_image',
            'localized_detection_topic': '/advanced/localized_detections',
            'marker_topic': '/advanced/object_markers',
            'deduplicated_marker_topic': '/advanced/deduplicated_object_markers',
            'final_marker_topic': '/advanced/final_object_markers',
        }],
    )
    selector = Node(
        package='robocup_home_robot',
        executable='advanced_target_selector.py',
        name='advanced_target_selector',
        output='screen',
        parameters=[{
            'target_image_evidence_path': LaunchConfiguration(
                'target_image_evidence_path'
            ),
        }],
    )
    evidence_saver = Node(
        package='robocup_home_robot',
        executable='advanced_target_image_saver.py',
        name='advanced_target_image_saver',
        output='screen',
        parameters=[{
            'evidence_path': LaunchConfiguration('target_image_evidence_path'),
        }],
    )
    runner = Node(
        package='robocup_home_robot',
        executable='advanced_stage1_runner.py',
        name='advanced_stage1_runner',
        output='screen',
        parameters=[{
            'dining_observation_x': 2.10,
            'dining_observation_y': 0.45,
            'dining_observation_yaw': 1.5707963267948966,
            'use_dining_entry_waypoint': LaunchConfiguration(
                'use_dining_entry_waypoint'
            ),
            'dining_entry_x': LaunchConfiguration('dining_entry_x'),
            'dining_entry_y': LaunchConfiguration('dining_entry_y'),
            'dining_entry_yaw': LaunchConfiguration('dining_entry_yaw'),
            'target_wait_seconds': 30.0,
            'navigate_to_p2_first': LaunchConfiguration(
                'standalone_navigate_to_p2'
            ),
        }],
    )

    def start_stage1(event, _context):
        if event.returncode != 0:
            message = 'Vision inputs failed readiness; Advanced Task Stage 1 not started.'
            return [
                LogInfo(msg=message),
                EmitEvent(event=Shutdown(reason=message)),
            ]
        return [
            LogInfo(
                msg=(
                    'Vision inputs ready; starting isolated 18-class dining '
                    'perception and autonomous Stage 1 runner.'
                )
            ),
            localizer,
            selector,
            runner,
        ]

    def finish_stage1(event, _context):
        message = (
            'Advanced Task Stage 1 succeeded.'
            if event.returncode == 0
            else f'Advanced Task Stage 1 failed; runner exit code {event.returncode}.'
        )
        return [
            LogInfo(msg=message),
            EmitEvent(event=Shutdown(reason=message)),
        ]

    return LaunchDescription([
        DeclareLaunchArgument('world_file', default_value=''),
        DeclareLaunchArgument('world_name', default_value='robocup_home'),
        DeclareLaunchArgument(
            'use_dining_entry_waypoint',
            default_value='true',
            description=(
                'Use the Advanced-only two-leg P2 handoff via the dining '
                'entry waypoint; this does not change the frozen base task.'
            ),
        ),
        DeclareLaunchArgument('dining_entry_x', default_value='0.45'),
        DeclareLaunchArgument('dining_entry_y', default_value='0.25'),
        DeclareLaunchArgument(
            'dining_entry_yaw', default_value='1.5707963267948966'
        ),
        DeclareLaunchArgument(
            'target_image_evidence_path',
            default_value='',
            description=(
                'Optional absolute PNG path for the first selected target image. '
                'Empty keeps evidence persistence disabled.'
            ),
        ),
        DeclareLaunchArgument(
            'model_path',
            default_value=str(
                Path.home()
                / 'robocup_assets/training_runs/formal_objects_v2_yolo11n_finetune'
                / 'weights/epoch30.pt'
            ),
        ),
        DeclareLaunchArgument(
            'standalone_navigate_to_p2',
            default_value='true',
            description=(
                'For a fresh simulator test, first navigate from the normal '
                'start to frozen P2. Set false only when this runner is '
                'started after the base task has already reached P2.'
            ),
        ),
        DeclareLaunchArgument(
            'stage_timeout_seconds',
            default_value='300.0',
            description=(
                'Whole Stage 1 watchdog budget, including simulator startup, '
                'the frozen P2 handoff, dining navigation, and one target wait.'
            ),
        ),
        navigation,
        evidence_saver,
        RegisterEventHandler(
            OnProcessExit(target_action=wait_for_vision, on_exit=start_stage1)
        ),
        RegisterEventHandler(
            OnProcessExit(target_action=runner, on_exit=finish_stage1)
        ),
        wait_for_vision,
        TimerAction(
            period=LaunchConfiguration('stage_timeout_seconds'),
            actions=[
                LogInfo(msg='Advanced Task Stage 1 exceeded its configured time limit.'),
                EmitEvent(event=Shutdown(reason='Advanced Task Stage 1 timeout')),
            ],
        ),
    ])
