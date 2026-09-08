"""Start the saved-map Nav2 stack with the existing simulation and robot."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    EmitEvent,
    ExecuteProcess,
    IncludeLaunchDescription,
    LogInfo,
    RegisterEventHandler,
    SetEnvironmentVariable,
)
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import EnvironmentVariable, LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    """Start each subsystem once, gated by observable world and robot readiness."""
    robot_share = get_package_share_directory('robocup_home_robot')
    world_share = get_package_share_directory('wpr_simulation_ros2')
    franka_share_parent = os.path.dirname(
        get_package_share_directory('franka_description')
    )
    nav2_params = os.path.join(robot_share, 'config', 'nav2_params.yaml')
    map_yaml = os.path.join(robot_share, 'maps', 'example_map_v1.yaml')

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
        launch_arguments={
            'x': LaunchConfiguration('spawn_x'),
            'y': LaunchConfiguration('spawn_y'),
            'z': LaunchConfiguration('spawn_z'),
            'yaw': LaunchConfiguration('spawn_yaw'),
        }.items(),
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
                EnvironmentVariable('GZ_SIM_RESOURCE_PATH', default_value=''),
            ],
        ),
        SetEnvironmentVariable(
            'IGN_GAZEBO_RESOURCE_PATH',
            [
                franka_share_parent,
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
