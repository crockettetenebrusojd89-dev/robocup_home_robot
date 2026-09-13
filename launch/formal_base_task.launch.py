"""Run one fail-closed formal base task from judge inputs to answer JSON."""

import math
import os
from pathlib import Path
import sys

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    EmitEvent,
    ExecuteProcess,
    IncludeLaunchDescription,
    LogInfo,
    OpaqueFunction,
    RegisterEventHandler,
    TimerAction,
)
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


sys.path.insert(0, os.path.dirname(__file__))
from formal_runtime_config import load_aliases  # noqa: E402
from formal_runtime_config import load_class_manifest  # noqa: E402
from formal_runtime_config import parse_group_number  # noqa: E402
from formal_runtime_config import resolve_target_classes  # noqa: E402


def _resolved(context, name):
    return context.perform_substitution(LaunchConfiguration(name))


def _fail(message):
    return [
        LogInfo(msg=f'Formal base-task preflight failed: {message}'),
        EmitEvent(event=Shutdown(reason='Formal base-task preflight failed')),
    ]


def _build_runtime(context, robot_share):
    try:
        manifest_path = Path(_resolved(context, 'class_manifest')).expanduser()
        alias_path = Path(_resolved(context, 'class_aliases')).expanduser()
        canonical_classes = load_class_manifest(manifest_path)
        if len(canonical_classes) != 18:
            raise ValueError(
                f'Formal manifest must contain exactly 18 classes; '
                f'got {len(canonical_classes)}.'
            )
        aliases = load_aliases(alias_path, canonical_classes)
        target_classes = resolve_target_classes(
            [
                _resolved(context, 'target_1'),
                _resolved(context, 'target_2'),
                _resolved(context, 'target_3'),
            ],
            canonical_classes,
            aliases,
        )
        group_number = parse_group_number(_resolved(context, 'group_number'))
        model_path = Path(_resolved(context, 'model_path')).expanduser()
        if not model_path.is_file():
            raise ValueError(f'Formal YOLO model does not exist: {model_path}')
        if model_path.suffix != '.pt':
            raise ValueError('Formal YOLO model must be a local .pt file.')
        output_directory = Path(
            _resolved(context, 'answer_output_dir')
        ).expanduser()
        answer_path = output_directory / f'{group_number}_answer.json'
        if answer_path.exists():
            raise ValueError(
                f'Answer already exists; refusing to overwrite: {answer_path}'
            )
        max_runtime_seconds = float(_resolved(context, 'max_runtime_seconds'))
        if (
            not math.isfinite(max_runtime_seconds)
            or max_runtime_seconds <= 0.0
        ):
            raise ValueError('max_runtime_seconds must be positive and finite.')
    except (OSError, TypeError, ValueError) as error:
        return _fail(str(error))

    navigation_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(robot_share, 'launch', 'navigation.launch.py')
        )
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
    )
    localizer = Node(
        package='robocup_home_robot',
        executable='rgbd_object_localizer',
        name='rgbd_object_localizer',
        output='screen',
        parameters=[{
            'model_path': str(model_path),
            'target_classes': list(target_classes),
            'expected_model_classes': list(canonical_classes),
            'group_number': group_number,
            'answer_output_dir': str(output_directory),
            'device': _resolved(context, 'device'),
        }],
    )
    runner = Node(
        package='robocup_home_robot',
        executable='formal_base_task_runner',
        name='formal_base_task_runner',
        output='screen',
        parameters=[{
            'target_classes': list(target_classes),
            'group_number': group_number,
            'answer_output_dir': str(output_directory),
        }],
    )

    def start_formal_nodes(event, _context):
        if event.returncode != 0:
            return [
                LogInfo(msg='Vision inputs failed readiness; task not started.'),
                EmitEvent(event=Shutdown(reason='Vision readiness failed')),
            ]
        return [
            LogInfo(
                msg=(
                    'Vision inputs are ready; starting the verified 18-class '
                    'localizer and automatic base-task runner.'
                )
            ),
            localizer,
            runner,
        ]

    def finish_after_runner(event, _context):
        if event.returncode == 0:
            message = f'Formal base task succeeded: {answer_path}'
        else:
            message = (
                'Formal base task failed; runner exit code '
                f'{event.returncode}. Inspect the first failed stage.'
            )
        return [
            LogInfo(msg=message),
            EmitEvent(event=Shutdown(reason=message)),
        ]

    return [
        LogInfo(
            msg=(
                f'Formal inputs accepted: group={group_number}; '
                f'targets={list(target_classes)}; model={model_path}; '
                f'answer={answer_path}; timeout={max_runtime_seconds:.1f}s'
            )
        ),
        navigation_launch,
        RegisterEventHandler(
            OnProcessExit(
                target_action=wait_for_vision,
                on_exit=start_formal_nodes,
            )
        ),
        RegisterEventHandler(
            OnProcessExit(
                target_action=runner,
                on_exit=finish_after_runner,
            )
        ),
        wait_for_vision,
        TimerAction(
            period=max_runtime_seconds,
            actions=[
                LogInfo(msg='Formal base task exceeded its runtime limit.'),
                EmitEvent(event=Shutdown(reason='Formal task timeout')),
            ],
        ),
    ]


def generate_launch_description():
    """Declare required judge inputs, validate them, and create the runtime."""
    robot_share = get_package_share_directory('robocup_home_robot')
    return LaunchDescription([
        DeclareLaunchArgument('target_1'),
        DeclareLaunchArgument('target_2'),
        DeclareLaunchArgument('target_3'),
        DeclareLaunchArgument('group_number'),
        DeclareLaunchArgument('model_path'),
        DeclareLaunchArgument(
            'answer_output_dir',
            default_value=str(Path.home() / 'robocup_assets/submissions'),
        ),
        DeclareLaunchArgument(
            'class_manifest',
            default_value=os.path.join(
                robot_share, 'config', 'formal_object_classes.json'
            ),
        ),
        DeclareLaunchArgument(
            'class_aliases',
            default_value=os.path.join(
                robot_share, 'config', 'formal_class_aliases.json'
            ),
        ),
        DeclareLaunchArgument('device', default_value='cpu'),
        DeclareLaunchArgument('max_runtime_seconds', default_value='450.0'),
        OpaqueFunction(
            function=lambda context: _build_runtime(context, robot_share)
        ),
    ])
