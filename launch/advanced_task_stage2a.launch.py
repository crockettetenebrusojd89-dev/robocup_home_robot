"""Run visual target to collision-checked FR3 safe pre-grasp, then stop."""

import os
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    EmitEvent,
    IncludeLaunchDescription,
    LogInfo,
    RegisterEventHandler,
    TimerAction,
    SetEnvironmentVariable,
)
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import Command, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
import yaml


def _yaml(package, relative):
    path = os.path.join(get_package_share_directory(package), relative)
    with open(path, 'r', encoding='utf-8') as stream:
        return yaml.safe_load(stream)


def generate_launch_description():
    robot_share = get_package_share_directory('robocup_home_robot')
    xacro_file = os.path.join(robot_share, 'urdf', 'robot.urdf.xacro')
    controller_config = os.path.join(
        robot_share, 'config', 'advanced_stage2a_ros2_controllers.yaml'
    )
    moveit_controller_config = _yaml(
        'robocup_home_robot', 'config/advanced_stage2a_moveit_controllers.yaml'
    )
    semantic_path = os.path.join(robot_share, 'config', 'mobile_fr3.srdf')
    semantic_description = Path(semantic_path).read_text(encoding='utf-8')
    robot_description = {
        'robot_description': ParameterValue(
            Command([
                'xacro ', xacro_file,
                ' arm_control:=true controller_config:=', controller_config,
            ]),
            value_type=str,
        )
    }
    robot_description_semantic = {
        'robot_description_semantic': semantic_description
    }
    kinematics = _yaml('franka_fr3_moveit_config', 'config/kinematics.yaml')
    ompl = _yaml('franka_fr3_moveit_config', 'config/ompl_planning.yaml')
    ompl['fr3_arm'] = {'planner_configs': list(ompl['planner_configs'].keys())}
    planning_pipeline = {
        'move_group': {
            'planning_plugin': 'ompl_interface/OMPLPlanner',
            'request_adapters': (
                'default_planner_request_adapters/AddTimeOptimalParameterization '
                'default_planner_request_adapters/ResolveConstraintFrames '
                'default_planner_request_adapters/FixWorkspaceBounds '
                'default_planner_request_adapters/FixStartStateBounds '
                'default_planner_request_adapters/FixStartStateCollision '
                'default_planner_request_adapters/FixStartStatePathConstraints'
            ),
            'start_state_max_bounds_error': 0.1,
            **ompl,
        }
    }
    moveit_controllers = {
        'moveit_simple_controller_manager': moveit_controller_config,
        'moveit_controller_manager': (
            'moveit_simple_controller_manager/MoveItSimpleControllerManager'
        ),
    }
    move_group = Node(
        package='moveit_ros_move_group',
        executable='move_group',
        name='move_group',
        output='screen',
        parameters=[
            robot_description,
            robot_description_semantic,
            kinematics,
            planning_pipeline,
            moveit_controllers,
            {
                'use_sim_time': True,
                'moveit_manage_controllers': False,
                'trajectory_execution.allowed_execution_duration_scaling': 5.0,
                'trajectory_execution.allowed_goal_duration_margin': 5.0,
                'trajectory_execution.allowed_start_tolerance': 0.03,
                'publish_planning_scene': True,
                'publish_geometry_updates': True,
                'publish_state_updates': True,
                'publish_transforms_updates': True,
            },
        ],
    )
    common_spawner_arguments = [
        '--controller-manager', '/controller_manager',
        '--controller-manager-timeout', '90',
        '--param-file', controller_config,
    ]
    arm_spawner = Node(
        package='controller_manager',
        executable='spawner',
        arguments=[
            'fr3_arm_controller',
            '--controller-type',
            'joint_trajectory_controller/JointTrajectoryController',
            *common_spawner_arguments,
        ],
        output='screen',
    )
    stage1 = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(robot_share, 'launch', 'advanced_task_stage1.launch.py')
        ),
        launch_arguments={
            'world_file': LaunchConfiguration('world_file'),
            'world_name': LaunchConfiguration('world_name'),
            'model_path': LaunchConfiguration('model_path'),
            'target_image_evidence_path': LaunchConfiguration(
                'target_image_evidence_path'
            ),
            'standalone_navigate_to_p2': LaunchConfiguration(
                'standalone_navigate_to_p2'
            ),
            'skip_dining_navigation': LaunchConfiguration(
                'skip_dining_navigation'
            ),
            'arm_control': 'true',
            'controller_config': controller_config,
            'use_rviz': 'false',
            'shutdown_on_success': 'false',
            'stage_timeout_seconds': LaunchConfiguration('stage_timeout_seconds'),
            'use_dining_entry_waypoint': LaunchConfiguration(
                'use_dining_entry_waypoint'
            ),
            'spawn_x': LaunchConfiguration('spawn_x'),
            'spawn_y': LaunchConfiguration('spawn_y'),
            'spawn_yaw': LaunchConfiguration('spawn_yaw'),
            'initial_pose_x': LaunchConfiguration('initial_pose_x'),
            'initial_pose_y': LaunchConfiguration('initial_pose_y'),
            'initial_pose_yaw': LaunchConfiguration('initial_pose_yaw'),
        }.items(),
    )
    approach = Node(
        package='robocup_home_robot',
        executable='advanced_stage2a_approach.py',
        name='advanced_stage2a_approach',
        output='screen',
        parameters=[{
            'table_clearance_m': LaunchConfiguration('table_clearance_m')
        }],
    )
    pregrasp = Node(
        package='robocup_home_robot',
        executable='advanced_stage2a_pregrasp',
        name='advanced_stage2a_pregrasp',
        output='screen',
        parameters=[
            robot_description,
            robot_description_semantic,
            kinematics,
            {'use_sim_time': True},
        ],
    )

    def finish_pregrasp(event, _context):
        passed = event.returncode == 0
        message = 'Advanced Stage 2A PASS.' if passed else (
            f'Advanced Stage 2A FAIL; pre-grasp exit code {event.returncode}.'
        )
        return [LogInfo(msg=message), EmitEvent(event=Shutdown(reason=message))]

    def finish_approach(event, _context):
        if event.returncode == 0:
            return [
                LogInfo(
                    msg=(
                        'Manipulation approach complete; starting MoveIt for FR3.'
                    )
                ),
                move_group,
            ]
        message = f'Advanced Stage 2A approach failed with code {event.returncode}.'
        return [LogInfo(msg=message), EmitEvent(event=Shutdown(reason=message))]

    return LaunchDescription([
        DeclareLaunchArgument('world_file', default_value=''),
        DeclareLaunchArgument('world_name', default_value='robocup_home'),
        DeclareLaunchArgument(
            'model_path',
            default_value=str(
                Path.home()
                / 'robocup_assets/training_runs/formal_objects_v2_yolo11n_finetune'
                / 'weights/epoch30.pt'
            ),
        ),
        DeclareLaunchArgument('target_image_evidence_path', default_value=''),
        DeclareLaunchArgument('standalone_navigate_to_p2', default_value='true'),
        DeclareLaunchArgument('skip_dining_navigation', default_value='false'),
        DeclareLaunchArgument('use_dining_entry_waypoint', default_value='true'),
        DeclareLaunchArgument('spawn_x', default_value='-4.8523360944520624'),
        DeclareLaunchArgument('spawn_y', default_value='-0.53251986452829558'),
        DeclareLaunchArgument('spawn_yaw', default_value='0.014066953117588583'),
        DeclareLaunchArgument('initial_pose_x', default_value='-4.828'),
        DeclareLaunchArgument('initial_pose_y', default_value='-0.477'),
        DeclareLaunchArgument('initial_pose_yaw', default_value='0.010'),
        DeclareLaunchArgument('table_clearance_m', default_value='0.45'),
        DeclareLaunchArgument('stage_timeout_seconds', default_value='600.0'),
        SetEnvironmentVariable('OMP_NUM_THREADS', '2'),
        SetEnvironmentVariable('MKL_NUM_THREADS', '2'),
        SetEnvironmentVariable('OPENBLAS_NUM_THREADS', '2'),
        stage1,
        arm_spawner,
        approach,
        pregrasp,
        RegisterEventHandler(OnProcessExit(target_action=approach, on_exit=finish_approach)),
        RegisterEventHandler(OnProcessExit(target_action=pregrasp, on_exit=finish_pregrasp)),
        TimerAction(
            period=LaunchConfiguration('stage_timeout_seconds'),
            actions=[
                LogInfo(msg='Advanced Stage 2A exceeded its watchdog limit.'),
                EmitEvent(event=Shutdown(reason='Advanced Stage 2A timeout')),
            ],
        ),
    ])
