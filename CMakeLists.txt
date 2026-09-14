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
  FILES tools/formal_dataset/classes.json
  DESTINATION share/${PROJECT_NAME}/config
  RENAME formal_object_classes.json
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
  PROGRAMS scripts/formal_base_task_runner.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME formal_base_task_runner
)

install(
  FILES
    scripts/formal_runtime_config.py
    scripts/go_to_living_room.py
    scripts/scan_living_room.py
    scripts/vision_final_dedup.py
  DESTINATION lib/${PROJECT_NAME}
)

install(
  FILES scripts/formal_runtime_config.py
  DESTINATION share/${PROJECT_NAME}/launch
)

install(
  PROGRAMS scripts/offset_joint_states.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME offset_joint_states
)

if(BUILD_TESTING)
  find_package(Python3 REQUIRED COMPONENTS Interpreter)
  find_package(ament_lint_auto REQUIRED)
  # the following line skips the linter which checks for copyrights
  # comment the line when a copyright and license is added to all source files
  set(ament_cmake_copyright_FOUND TRUE)
  # the following line skips cpplint (only works in a git repo)
  # comment the line when this package is in a git repo and when
  # a copyright and license is added to all source files
  set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()
  add_test(
    NAME vision_final_dedup
    COMMAND ${Python3_EXECUTABLE}
      ${CMAKE_CURRENT_SOURCE_DIR}/test/test_vision_final_dedup.py
  )
  set_tests_properties(
    vision_final_dedup
    PROPERTIES ENVIRONMENT
      "PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR}/scripts"
  )
  add_test(
    NAME formal_dataset_tools
    COMMAND ${Python3_EXECUTABLE}
      ${CMAKE_CURRENT_SOURCE_DIR}/test/test_formal_dataset_tools.py
  )
  set_tests_properties(
    formal_dataset_tools
    PROPERTIES ENVIRONMENT
      "PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR}/tools/formal_dataset/scripts"
  )
  add_test(
    NAME formal_world_loader
    COMMAND ${Python3_EXECUTABLE}
      ${CMAKE_CURRENT_SOURCE_DIR}/test/test_formal_world_loader.py
  )
  add_test(
    NAME formal_runtime
    COMMAND ${Python3_EXECUTABLE}
      ${CMAKE_CURRENT_SOURCE_DIR}/test/test_formal_runtime.py
  )
  set_tests_properties(
    formal_runtime
    PROPERTIES ENVIRONMENT
      "PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR}/scripts"
  )
  add_test(
    NAME p2_evaluation
    COMMAND ${Python3_EXECUTABLE}
      ${CMAKE_CURRENT_SOURCE_DIR}/test/test_p2_eval.py
  )
  set_tests_properties(
    p2_evaluation
    PROPERTIES ENVIRONMENT
      "PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR}/tools/p2_eval"
  )
endif()

ament_package()
