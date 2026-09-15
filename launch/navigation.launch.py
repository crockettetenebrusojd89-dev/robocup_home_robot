"""Start the saved-map Nav2 stack with the existing simulation and robot."""

import os
from pathlib import Path
import re

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
    SetEnvironmentVariable,
)
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import EnvironmentVariable, LaunchConfiguration
from launch_ros.actions import Node


WORLD_NAME_PATTERN = re.compile(r'^[A-Za-z0-9_.-]+$')


def _validated_world_name(context):
    world_name = LaunchConfiguration('world_name').perform(context).strip()
    if not world_name or WORLD_NAME_PATTERN.fullmatch(world_name) is None:
        raise RuntimeError(
            'world_name must contain only letters, digits, underscore, dot, '
            f'or hyphen; got {world_name!r}'
        )
    return world_name


def _resolve_world_file(value):
    """Resolve a supplied path without reading or parsing scene contents."""
    if not value.strip():
        return None
    world_path = Path(value).expanduser().resolve()
    if world_path.suffix.lower() != '.world':
        raise RuntimeError(f'world_file must end in .world: {world_path}')
    if not world_path.is_file():
        raise RuntimeError(f'world_file does not exist: {world_path}')
    return world_path


def _gazebo_command(world_path):
    """Run one headless server directly so launch owns the simulator process."""
    return [
        'ign',
        'gazebo',
        '-r',
        '-s',
        '-v',
        '2',
        str(world_path),
        '--force-version',
        '6',
    ]


def _select_world_launch(context, world_share):
    """Use the packaged example or pass an official file directly to Gazebo."""
    _validated_world_name(context)
    world_path = _resolve_world_file(
        LaunchConfiguration('world_file').perform(context)
    )
    if world_path is None:
        return [
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(world_share, 'launch', 'world.launch.py')
                ),
                launch_arguments={'world_type': 'example'}.items(),
            )
        ]

    gazebo = ExecuteProcess(
        cmd=_gazebo_command(world_path),
        name='gazebo_server',
        output='screen',
        on_exit=EmitEvent(
            event=Shutdown(reason='Gazebo server exited')
        ),
    )
    clock_bridge = Node(
        package='ros_gz_bridge',
        executable='parameter_bridge',
        arguments=['/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock'],
        output='screen',
    )
    return [
        LogInfo(msg=f'Loading supplied competition world: {world_path}'),
        gazebo,
        clock_bridge,
    ]


def generate_launch_description():
    """Start each subsystem once, gated by observable world and robot readiness."""
    robot_share = get_package_share_directory('robocup_home_robot')
    world_share = get_package_share_directory('wpr_simulation_ros2')
    franka_share_parent = os.path.dirname(
        get_package_share_directory('franka_description')
    )
    nav2_params = os.path.join(robot_share, 'config', 'nav2_params.yaml')
    map_yaml = os.path.join(robot_share, 'maps', 'example_map_v1.yaml')

    world_launch = OpaqueFunction(
        function=lambda context: _select_world_launch(context, world_share)
    )

    spawn_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(robot_share, 'launch', 'spawn_robot.launch.py')
        ),
        launch_arguments={
            'x': LaunchConfiguration('spawn_x'),
            'y': LaunchConfiguration('spawn_y'),
            'z': LaunchConfiguration('spawn_z'),
            'yaw': LaunchConfiguration('spawn_yaw'),
            'world_name': LaunchConfiguration('world_name'),
        }.items(),
    )

    wait_for_world = ExecuteProcess(
        cmd=[
            os.path.join(
                robot_share,
                'lib',
                'robocup_home_robot',
                'wait_for_gazebo_world.py',
            ),
            '--world-name',
            LaunchConfiguration('world_name'),
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

    map_server = Node(
        package='nav2_map_server',
        executable='map_server',
        name='map_server',
        output='screen',
        parameters=[nav2_params, {'yaml_filename': map_yaml, 'use_sim_time': True}],
    )

    amcl = Node(
        package='nav2_amcl',
        executable='amcl',
        name='amcl',
        output='screen',
        parameters=[nav2_params],
    )

    controller_server = Node(
        package='nav2_controller',
        executable='controller_server',
        name='controller_server',
        output='screen',
        parameters=[nav2_params],
    )

    planner_server = Node(
        package='nav2_planner',
        executable='planner_server',
        name='planner_server',
        output='screen',
        parameters=[nav2_params],
    )

    behavior_server = Node(
        package='nav2_behaviors',
        executable='behavior_server',
        name='behavior_server',
        output='screen',
        parameters=[nav2_params],
    )

    bt_navigator = Node(
        package='nav2_bt_navigator',
        executable='bt_navigator',
        name='bt_navigator',
        output='screen',
        parameters=[nav2_params],
    )

    lifecycle_nodes = [
        'map_server',
        'amcl',
        'controller_server',
        'planner_server',
        'behavior_server',
        'bt_navigator',
    ]

    lifecycle_manager = Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_navigation',
        output='screen',
        parameters=[{
            'use_sim_time': True,
            'autostart': True,
            'node_names': lifecycle_nodes,
        }],
    )

    rviz = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        output='screen',
        arguments=[
            '-d',
            os.path.join(robot_share, 'config', 'navigation.rviz'),
        ],
        parameters=[{'use_sim_time': True}],
    )

    nav2_stack = [
        map_server,
        amcl,
        controller_server,
        planner_server,
        behavior_server,
        bt_navigator,
        lifecycle_manager,
        rviz,
    ]

    def spawn_after_world_ready(event, _context):
        if event.returncode != 0:
            return [
                LogInfo(msg='Gazebo world readiness check failed; navigation not started.'),
                EmitEvent(event=Shutdown(reason='Gazebo world did not become ready')),
            ]
        return [
            LogInfo(msg='Gazebo world is ready; spawning the robot once.'),
            spawn_launch,
            wait_for_robot,
        ]

    def start_nav2_after_robot_ready(event, _context):
        if event.returncode != 0:
            return [
                LogInfo(msg='Robot readiness check failed; Nav2 not started.'),
                EmitEvent(event=Shutdown(reason='Robot interfaces did not become ready')),
            ]
        return [
            LogInfo(msg='Robot interfaces are ready; starting saved-map Nav2 and RViz.'),
            *nav2_stack,
        ]

    return LaunchDescription([
        DeclareLaunchArgument(
            'world_file',
            default_value='',
            description=(
                'Optional competition .world path. Empty uses the packaged '
                'example world; scene contents are never parsed by this launch.'
            ),
        ),
        DeclareLaunchArgument(
            'world_name',
            default_value='robocup_home',
            description='Gazebo world name used for services and robot spawning.',
        ),
        DeclareLaunchArgument(
            'spawn_x',
            default_value='-4.8523360944520624',
            description='Robot start x position in Gazebo world coordinates.',
        ),
        DeclareLaunchArgument(
            'spawn_y',
            default_value='-0.53251986452829558',
            description='Robot start y position in Gazebo world coordinates.',
        ),
        DeclareLaunchArgument(
            'spawn_z',
            default_value='0.1749999628074342',
            description='Robot start z position in Gazebo world coordinates.',
        ),
        DeclareLaunchArgument(
            'spawn_yaw',
            default_value='0.014066953117588583',
            description='Robot start yaw in Gazebo world coordinates.',
        ),
        # SDFormat resolves package://franka_description as a model:// URI.
        # Add the directory containing that package before starting Gazebo;
        # the upstream package exports its own share directory instead.
        SetEnvironmentVariable(
            'GZ_SIM_RESOURCE_PATH',
            [
                franka_share_parent,
                os.pathsep,
                os.path.join(world_share, 'models'),
                os.pathsep,
                EnvironmentVariable('GZ_SIM_RESOURCE_PATH', default_value=''),
            ],
        ),
        SetEnvironmentVariable(
            'IGN_GAZEBO_RESOURCE_PATH',
            [
                franka_share_parent,
                os.pathsep,
                os.path.join(world_share, 'models'),
                os.pathsep,
                EnvironmentVariable(
                    'IGN_GAZEBO_RESOURCE_PATH', default_value=''
                ),
            ],
        ),
        world_launch,
        RegisterEventHandler(
            OnProcessExit(
                target_action=wait_for_world,
                on_exit=spawn_after_world_ready,
            )
        ),
        RegisterEventHandler(
            OnProcessExit(
                target_action=wait_for_robot,
                on_exit=start_nav2_after_robot_ready,
            )
        ),
        wait_for_world,
    ])
