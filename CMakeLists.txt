cmake_minimum_required(VERSION 3.8)
project(robocup_home_robot)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# find dependencies
find_package(ament_cmake REQUIRED)

install(
  DIRECTORY urdf
  DESTINATION share/${PROJECT_NAME}
)

install(
  DIRECTORY launch
  DESTINATION share/${PROJECT_NAME}
)

install(
  DIRECTORY config
  DESTINATION share/${PROJECT_NAME}
)

install(
  DIRECTORY maps
  DESTINATION share/${PROJECT_NAME}
)

install(
  DIRECTORY models
  DESTINATION share/${PROJECT_NAME}
)

install(
  PROGRAMS
    scripts/load_sensors_system.py
    scripts/generate_spawn_sdf.py
    scripts/wait_for_gazebo_world.py
    scripts/wait_for_gazebo_robot.py
    scripts/wait_for_vision_ready.py
    scripts/save_map.sh
  DESTINATION share/${PROJECT_NAME}/lib/${PROJECT_NAME}
)

install(
  PROGRAMS scripts/go_to_living_room.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME go_to_living_room
)

install(
  PROGRAMS scripts/scan_living_room.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME scan_living_room
)

install(
  PROGRAMS scripts/reinspect_far_object.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME reinspect_far_object
)

install(
  PROGRAMS scripts/yolo_detector.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME yolo_detector
)

install(
  PROGRAMS scripts/rgbd_object_localizer.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME rgbd_object_localizer
)

install(
  PROGRAMS scripts/offset_joint_states.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME offset_joint_states
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  # the following line skips the linter which checks for copyrights
  # comment the line when a copyright and license is added to all source files
  set(ament_cmake_copyright_FOUND TRUE)
  # the following line skips cpplint (only works in a git repo)
  # comment the line when this package is in a git repo and when
  # a copyright and license is added to all source files
  set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
