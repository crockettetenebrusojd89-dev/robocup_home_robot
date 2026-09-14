# RoboCup@Home 启动教程

本教程面向当前东南大学 2026 RoboCup@Home 校赛工程，覆盖日常构建、RViz
建图、静态地图导航、视觉基础系统、正式 `.world` 文件加载、验证和退出流程。

本文只记录仓库中真实存在的入口。比赛正式计时后不得使用键盘、鼠标、RViz
交互或人工 `teleop` 控制；建图与手动调试命令只用于赛前开发。

## 1. 环境和目录

已验证环境：

- Ubuntu 22.04
- ROS 2 Humble
- Gazebo Fortress / Gazebo Sim
- Nav2、SLAM Toolbox、RViz2
- 工作空间：`~/wpr_ros2_ws`
- 本仓库：`~/wpr_ros2_ws/src/robocup_home_robot`
- Franka 工作空间：`~/franka_ros2_ws`
- 视觉虚拟环境：`~/robocup_vision_venv`

本仓库不是完整的系统安装包。启动前应确保 `wpr_simulation_ros2` 已位于同一
ROS 工作空间，并且 Franka 工作空间已经成功构建。

## 2. 获取仓库

已有工作空间不需要重复克隆。新建工作空间时可执行：

```bash
mkdir -p ~/wpr_ros2_ws/src
cd ~/wpr_ros2_ws/src
git clone git@github.com:crockettetenebrusojd89-dev/robocup_home_robot.git
```

然后补齐项目所需的 `wpr_simulation_ros2`、Franka 和 ROS 依赖。不要用这一步
覆盖已经配置好的工作空间。

## 3. 构建

在普通终端中执行：

```bash
cd ~/wpr_ros2_ws
source /opt/ros/humble/setup.bash
source ~/franka_ros2_ws/install/setup.bash
colcon build --packages-select robocup_home_robot --symlink-install
source install/setup.bash
```

成功标准：终端最后出现：

```text
Summary: 1 package finished
```

每次打开新终端，都需要重新执行环境准备：

```bash
cd ~/wpr_ros2_ws
source /opt/ros/humble/setup.bash
source ~/franka_ros2_ws/install/setup.bash
source install/setup.bash
```

如果终端提示找不到 `robocup_home_robot`，优先检查是否漏掉最后一条
`source install/setup.bash`，以及上一次构建是否成功。

## 4. 最常用：在 RViz 打开已有地图

当前已经保存并用于导航的地图是：

```text
maps/example_map_v1.yaml
maps/example_map_v1.pgm
```

只想查看这张已有地图时，不要启动 `mapping.launch.py`。准备普通 ROS 环境后
执行：

```bash
ros2 launch robocup_home_robot base_system.launch.py start_vision:=false
```

系统会加载 `example_map_v1.yaml`，启动 AMCL、Nav2 和
`config/navigation.rviz`。它不会运行 SLAM，也不会覆盖已保存地图。日志出现
`Managed nodes are active` 后，RViz 中应显示完整静态地图、机器人、激光、TF 和
代价地图。

## 5. 重新建图

建图仅用于赛前制作或更新离线地图，正式比赛不运行 SLAM。

### 终端 1：启动 Gazebo、机器人、SLAM 和建图 RViz

准备普通 ROS 环境后执行：

```bash
ros2 launch robocup_home_robot mapping.launch.py
```

成功时会依次看到：

```text
Gazebo world is ready; spawning the robot once.
Robot interfaces are ready; starting SLAM and RViz once.
Registering sensor: [Custom Described Lidar]
```

随后 Gazebo 和 RViz 会自动打开。RViz 使用 `config/mapping.rviz`，地图应随着
机器人移动和激光扫描逐步增长。

### 终端 2：赛前人工驾驶建图

新开终端并准备普通 ROS 环境，然后执行：

```bash
ros2 run teleop_twist_keyboard teleop_twist_keyboard
```

采用低速前进和缓慢转弯，尽量形成闭环。不要在正式比赛计时期间运行该命令。

### 终端 3：保存地图

保持建图系统运行，新开终端并准备普通 ROS 环境：

```bash
cd ~/wpr_ros2_ws
./src/robocup_home_robot/scripts/save_map.sh <new_map_name>
```

地图会保存到 `src/robocup_home_robot/maps/`。脚本会拒绝覆盖同名文件。只有看到
下面的信息才表示栅格地图和 SLAM pose graph 均已保存：

```text
Map and pose graph saved successfully with name: <new_map_name>
```

## 6. 使用已有地图导航

只验证导航、不启动视觉时，准备普通 ROS 环境后执行：

```bash
ros2 launch robocup_home_robot base_system.launch.py start_vision:=false
```

该入口会启动场景、一台机器人、静态地图、AMCL、Nav2 和导航 RViz，但不会
主动让机器人移动。等待日志出现 `Managed nodes are active` 后，新开终端并准备
普通 ROS 环境：

```bash
ros2 run robocup_home_robot go_to_living_room
```

成功标准：

```text
Living room navigation succeeded.
```

不要同时启动第二套 world、`spawn_robot.launch.py` 或 Nav2。

## 7. 导航与视觉基础系统

视觉节点需要项目视觉虚拟环境。在终端 1 中执行：

```bash
cd ~/wpr_ros2_ws
source /opt/ros/humble/setup.bash
source ~/franka_ros2_ws/install/setup.bash
source ~/robocup_vision_venv/bin/activate
source install/setup.bash
ros2 launch robocup_home_robot base_system.launch.py
```

这个统一入口会等待 RGB、Depth、CameraInfo 和相机到 `map` 的 TF 就绪，然后
启动组合式 YOLO + RGB-D 三维定位节点。不要再并行启动旧的独立
`yolo_detector`，否则会重复推理和重复发布图像。

机器人默认停在起点。开发阶段可在另一个普通 ROS 终端依次运行：

```bash
ros2 run robocup_home_robot go_to_living_room
ros2 run robocup_home_robot scan_living_room
ros2 run robocup_home_robot reinspect_far_object
```

这些任务节点不要同时运行。当前分终端流程是开发验证流程，不等同于正式比赛的
完整无人干预 runner。

## 8. 加载老师下发的正式 world

`work/formal-world-loader` 分支支持把绝对路径直接传给统一入口：

```bash
ros2 launch robocup_home_robot base_system.launch.py \
  world_file:=/absolute/path/to/teacher_provided.world
```

默认 Gazebo world 名称为 `robocup_home`。只有老师明确给出其他名称时才增加：

```bash
ros2 launch robocup_home_robot base_system.launch.py \
  world_file:=/absolute/path/to/teacher_provided.world \
  world_name:=documented_world_name
```

不得读取或解析正式场景文件来获取物品类别或坐标。更详细的赛场检查清单见
[`FORMAL_WORLD_RUNBOOK.md`](FORMAL_WORLD_RUNBOOK.md)。

## 9. 快速验证

系统运行时可在新的普通 ROS 终端检查关键话题：

```bash
ros2 topic list
```

至少应存在：

```text
/scan
/odom
/imu
/camera/color/image_raw
/camera/depth/image_raw
/camera/camera_info
/map
/tf
```

导航模式还应确认：

```bash
ros2 lifecycle get /bt_navigator
```

预期输出：

```text
active [3]
```

构建并运行仓库测试：

```bash
cd ~/wpr_ros2_ws
colcon build --packages-select robocup_home_robot \
  --symlink-install --cmake-args -DBUILD_TESTING=ON
colcon test --packages-select robocup_home_robot
colcon test-result --verbose
```

成功标准是 `0 errors, 0 failures`。环境中已知不适用的检查可能显示为 skipped。

## 10. 正确退出

先停止单独运行的导航、扫描、复检或 teleop 节点，再在主 launch 终端按一次
`Ctrl+C`。等待 Gazebo、RViz 和 ROS 节点退出后再重新启动，避免残留两套系统。

手动停止 GUI 时，Gazebo 或 RViz 可能记录由中断产生的非零退出码；判断一次运行
是否成功，应以中断前 world、机器人接口、SLAM/Nav2 和目标任务是否正常就绪为准。

## 11. 常见问题

### 找不到 ROS package

重新构建，并在当前终端执行 `source ~/wpr_ros2_ws/install/setup.bash`。

### 一直等待 world service

确认 Gazebo 已正常启动。使用老师下发的文件时，确认文件是绝对路径、后缀为
`.world`，并向老师确认 Gazebo world 名称。

### 没有激光、里程计或相机话题

不要继续启动导航或视觉任务。先看主 launch 中第一个失败的 readiness check，
确认 Gazebo 里只有一台机器人，再检查 bridge 和 sensors-system 日志。

### RViz 没有地图

建图模式确认 `slam_toolbox` 已启动并注册雷达；导航模式确认 map server 已加载
地图、AMCL 已启动、Fixed Frame 为 `map`。

### Gazebo 报告 FR3 mesh 资源路径警告

先确认启动前已经 source Franka 工作空间。该警告与底盘 SLAM/RViz 建图是否正常
是两个独立检查项；不要通过反复安装软件来掩盖真正的首个失败模块。

## 12. 文档维护规则

任何修改下列内容的提交，都必须在同一功能分支或 Pull Request 中同步更新本文：

- 安装依赖或工作空间路径；
- 构建命令；
- launch 文件、启动顺序或 launch 参数；
- 关键 ROS topic、服务或生命周期状态；
- 模型路径、视觉环境或运行设备；
- 正式比赛操作步骤和成功标准。

提交前应重新执行受影响的启动流程或测试，并把新的可复现实测结果写入对应文档。
