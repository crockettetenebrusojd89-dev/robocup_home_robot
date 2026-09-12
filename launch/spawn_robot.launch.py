"""Publish the robot description and spawn it into an existing Gazebo Sim world."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, RegisterEventHandler
from launch.event_handlers import OnProcessExit
from launch.substitutions import Command, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    """Create the robot_state_publisher and Gazebo spawn actions."""
    package_share = get_package_share_directory('robocup_home_robot')
    xacro_file = os.path.join(package_share, 'urdf', 'robot.urdf.xacro')
    sensors_loader = os.path.join(
        package_share,
        'lib',
        'robocup_home_robot',
        'load_sensors_system.py',
    )
    spawn_sdf_generator = os.path.join(
        package_share,
        'lib',
        'robocup_home_robot',
        'generate_spawn_sdf.py',
    )

    robot_description = ParameterValue(
        Command(['xacro ', xacro_file]),
        value_type=str,
    )

    robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        output='screen',
        parameters=[{'robot_description': robot_description}],
    )

    spawn_robot = Node(
        package='ros_gz_sim',
        executable='create',
        output='screen',
        arguments=[
            '-world', 'robocup_home',
            '-name', 'robocup_home_robot',
            '-string', Command([spawn_sdf_generator, ' ', xacro_file]),
            '-x', LaunchConfiguration('x'),
            '-y', LaunchConfiguration('y'),
            '-z', LaunchConfiguration('z'),
            '-Y', LaunchConfiguration('yaw'),
        ],
    )

    ros_gz_bridge = Node(
        package='ros_gz_bridge',
        executable='parameter_bridge',
        output='screen',
        arguments=[
            '/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist',
            '/odom@nav_msgs/msg/Odometry[gz.msgs.Odometry',
            '/model/robocup_home_robot/tf@tf2_msgs/msg/TFMessage[gz.msgs.Pose_V',
            '/scan@sensor_msgs/msg/LaserScan[gz.msgs.LaserScan',
            '/imu@sensor_msgs/msg/Imu[gz.msgs.IMU',
            '/camera/image@sensor_msgs/msg/Image[gz.msgs.Image',
            '/camera/depth_image@sensor_msgs/msg/Image[gz.msgs.Image',
            '/camera/camera_info@sensor_msgs/msg/CameraInfo[gz.msgs.CameraInfo',
            '/model/robocup_home_robot/joint_state@sensor_msgs/msg/JointState[gz.msgs.Model',
        ],
        remappings=[
            ('/model/robocup_home_robot/tf', '/tf'),
            ('/camera/image', '/camera/color/image_raw'),
            ('/camera/depth_image', '/camera/depth/image_raw'),
            (
                '/model/robocup_home_robot/joint_state',
                '/gazebo_joint_states',
            ),
        ],
    )

    offset_joint_states = Node(
        package='robocup_home_robot',
        executable='offset_joint_states',
        output='screen',
    )

    load_sensors_system = ExecuteProcess(
        cmd=[sensors_loader],
        name='load_sensors_system',
        output='screen',
    )

    load_sensors_after_spawn = RegisterEventHandler(
        OnProcessExit(
            target_action=spawn_robot,
            on_exit=[load_sensors_system],
        )
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            'x',
            default_value='-4.8523360944520624',
            description='Initial x position in Gazebo world coordinates, in meters.',
        ),
        DeclareLaunchArgument(
            'y',
            default_value='-0.53251986452829558',
            description='Initial y position in Gazebo world coordinates, in meters.',
        ),
        DeclareLaunchArgument(
            'z',
            default_value='0.1749999628074342',
            description='Initial z position in Gazebo world coordinates, in meters.',
        ),
        DeclareLaunchArgument(
            'yaw',
            default_value='0.014066953117588583',
            description='Initial yaw angle in Gazebo world coordinates, in radians.',
        ),
        robot_state_publisher,
        spawn_robot,
        ros_gz_bridge,
        offset_joint_states,
        load_sensors_after_spawn,
    ])
