#include <algorithm>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <control_msgs/action/follow_joint_trajectory.hpp>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include <geometry_msgs/msg/pose_stamped.hpp>
#include <moveit/move_group_interface/move_group_interface.h>
#include <moveit/planning_scene_interface/planning_scene_interface.h>
#include <moveit_msgs/action/move_group.hpp>
#include <moveit_msgs/msg/collision_object.hpp>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp_action/rclcpp_action.hpp>
#include <shape_msgs/msg/solid_primitive.hpp>
#include <std_msgs/msg/string.hpp>
#include <tf2/LinearMath/Quaternion.h>
#include <tf2_geometry_msgs/tf2_geometry_msgs.hpp>
#include <tf2_ros/buffer.h>
#include <tf2_ros/transform_listener.h>

namespace
{
constexpr double kPregraspOffset = 0.18;
constexpr double kMaximumReach = 0.95;
constexpr double kTableSurfaceZ = 0.780;

struct Table
{
  const char * name;
  double x;
  double y;
};

constexpr Table kTables[] = {
  {"dinning_table_0", 1.5, 1.5},
  {"dinning_table_1", 1.5, 2.0},
  {"dinning_table_2", 2.7, 1.5},
  {"dinning_table_3", 2.7, 2.0},
};

bool Finite(const geometry_msgs::msg::Point & point)
{
  return std::isfinite(point.x) && std::isfinite(point.y) &&
         std::isfinite(point.z);
}

const Table & NearestTable(const geometry_msgs::msg::Point & point)
{
  const Table * best = &kTables[0];
  double best_distance = std::hypot(point.x - best->x, point.y - best->y);
  for (const auto & table : kTables) {
    const double distance = std::hypot(point.x - table.x, point.y - table.y);
    if (distance < best_distance) {
      best = &table;
      best_distance = distance;
    }
  }
  return *best;
}
}  // namespace

class Stage2APregrasp
{
public:
  explicit Stage2APregrasp(const rclcpp::Node::SharedPtr & node)
  : node_(node), tf_buffer_(node_->get_clock()), tf_listener_(tf_buffer_)
  {
    auto qos = rclcpp::QoS(1).reliable().transient_local();
    target_subscription_ = node_->create_subscription<geometry_msgs::msg::PoseStamped>(
      "/advanced/stage2a_target_map", qos,
      [this](geometry_msgs::msg::PoseStamped::SharedPtr message) {
        std::lock_guard<std::mutex> lock(mutex_);
        target_map_ = *message;
        target_ready_ = true;
        condition_.notify_all();
      });
    class_subscription_ = node_->create_subscription<std_msgs::msg::String>(
      "/advanced/stage2a_target_class", qos,
      [this](std_msgs::msg::String::SharedPtr message) {
        std::lock_guard<std::mutex> lock(mutex_);
        target_class_ = message->data;
        condition_.notify_all();
      });
  }

  int Run()
  {
    geometry_msgs::msg::PoseStamped target_map;
    std::string target_class;
    {
      std::unique_lock<std::mutex> lock(mutex_);
      const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(600);
      while (rclcpp::ok() && (!target_ready_ || target_class_.empty()) &&
        std::chrono::steady_clock::now() < deadline)
      {
        condition_.wait_for(lock, std::chrono::seconds(1));
      }
      if (!rclcpp::ok()) {
        return 130;
      }
      if (!target_ready_ || target_class_.empty()) {
        RCLCPP_ERROR(node_->get_logger(), "Timed out waiting for the Stage 2A target.");
        return 1;
      }
      target_map = target_map_;
      target_class = target_class_;
    }

    auto move_group_client = rclcpp_action::create_client<moveit_msgs::action::MoveGroup>(
      node_, "move_action");
    const auto move_group_deadline =
      std::chrono::steady_clock::now() + std::chrono::seconds(60);
    while (rclcpp::ok() && std::chrono::steady_clock::now() < move_group_deadline &&
      !move_group_client->wait_for_action_server(std::chrono::seconds(1)))
    {
      RCLCPP_INFO_THROTTLE(
        node_->get_logger(), *node_->get_clock(), 5000,
        "Target received; waiting for the post-navigation MoveIt server.");
    }
    if (!rclcpp::ok()) {
      return 130;
    }
    if (!move_group_client->action_server_is_ready()) {
      RCLCPP_ERROR(node_->get_logger(), "MoveIt did not become ready within 60 seconds.");
      return 1;
    }
    auto controller_client = rclcpp_action::create_client<
      control_msgs::action::FollowJointTrajectory>(
      node_, "/fr3_arm_controller/follow_joint_trajectory");
    if (!controller_client->wait_for_action_server(std::chrono::seconds(15))) {
      RCLCPP_ERROR(
        node_->get_logger(),
        "FR3 trajectory action server was not discoverable within 15 seconds.");
      return 1;
    }
    RCLCPP_INFO(
      node_->get_logger(),
      "FR3 trajectory action server is ready; allowing MoveIt discovery to settle.");
    std::this_thread::sleep_for(std::chrono::seconds(2));

    moveit::planning_interface::MoveGroupInterface move_group(node_, "fr3_arm");
    move_group.setEndEffectorLink("fr3_hand_tcp");
    move_group.setPlanningTime(10.0);
    move_group.setNumPlanningAttempts(10);
    move_group.setMaxVelocityScalingFactor(0.10);
    move_group.setMaxAccelerationScalingFactor(0.10);
    const std::string planning_frame = move_group.getPlanningFrame();
    RCLCPP_INFO(
      node_->get_logger(),
      "MoveIt ready: group=fr3_arm planning_frame=%s end_effector=%s",
      planning_frame.c_str(), move_group.getEndEffectorLink().c_str());
    if (!ExecuteSafeMotion(move_group)) {
      return 1;
    }

    geometry_msgs::msg::PoseStamped target;
    geometry_msgs::msg::PoseStamped target_fr3;
    try {
      target = tf_buffer_.transform(target_map, planning_frame, tf2::durationFromSec(2.0));
      target_fr3 = tf_buffer_.transform(target_map, "fr3_link0", tf2::durationFromSec(2.0));
    } catch (const tf2::TransformException & error) {
      RCLCPP_ERROR(
        node_->get_logger(), "Target TF to %s failed: %s",
        planning_frame.c_str(), error.what());
      return 1;
    }
    if (!Finite(target.pose.position) || target.pose.position.z < 0.45 ||
      target.pose.position.z > 1.10)
    {
      RCLCPP_ERROR(
        node_->get_logger(), "Target is non-finite or not at a plausible tabletop height.");
      return 1;
    }

    geometry_msgs::msg::TransformStamped arm_transform;
    try {
      arm_transform = tf_buffer_.lookupTransform(
        planning_frame, "fr3_link0", tf2::TimePointZero, tf2::durationFromSec(2.0));
    } catch (const tf2::TransformException & error) {
      RCLCPP_ERROR(node_->get_logger(), "FR3 base TF failed: %s", error.what());
      return 1;
    }
    const auto & arm = arm_transform.transform.translation;
    geometry_msgs::msg::PoseStamped pregrasp_map = target_map;
    pregrasp_map.header.stamp = node_->now();
    if (pregrasp_map.pose.position.z < kTableSurfaceZ) {
      RCLCPP_WARN(
        node_->get_logger(),
        "Visual target z=%.3f is below the verified table surface z=%.3f; "
        "clamping only the safe pre-grasp height to the support plane.",
        pregrasp_map.pose.position.z, kTableSurfaceZ);
    }
    pregrasp_map.pose.position.z =
      std::max(pregrasp_map.pose.position.z, kTableSurfaceZ) + kPregraspOffset;
    pregrasp_map.pose.orientation.x = 1.0;
    pregrasp_map.pose.orientation.y = 0.0;
    pregrasp_map.pose.orientation.z = 0.0;
    pregrasp_map.pose.orientation.w = 0.0;
    geometry_msgs::msg::PoseStamped pregrasp;
    try {
      pregrasp = tf_buffer_.transform(
        pregrasp_map, planning_frame, tf2::durationFromSec(2.0));
    } catch (const tf2::TransformException & error) {
      RCLCPP_ERROR(
        node_->get_logger(), "Pre-grasp TF to %s failed: %s",
        planning_frame.c_str(), error.what());
      return 1;
    }
    const double reach = std::sqrt(
      std::pow(pregrasp.pose.position.x - arm.x, 2) +
      std::pow(pregrasp.pose.position.y - arm.y, 2) +
      std::pow(pregrasp.pose.position.z - arm.z, 2));
    RCLCPP_INFO(
      node_->get_logger(),
      "Selected target: class=%s target_%s=[%.3f, %.3f, %.3f] "
      "target_fr3_link0=[%.3f, %.3f, %.3f] FR3_base=[%.3f, %.3f, %.3f] radial=%.3f m",
      target_class.c_str(), planning_frame.c_str(), target.pose.position.x,
      target.pose.position.y, target.pose.position.z, target_fr3.pose.position.x,
      target_fr3.pose.position.y, target_fr3.pose.position.z, arm.x, arm.y, arm.z, reach);
    if (reach > kMaximumReach) {
      RCLCPP_ERROR(
        node_->get_logger(),
        "Target remains outside the conservative FR3 workspace after approach (%.3f > %.3f m).",
        reach, kMaximumReach);
      return 1;
    }

    if (!AddTableCollision(target_map, planning_frame)) {
      return 1;
    }
    move_group.setStartStateToCurrentState();
    const bool ik_success = move_group.setJointValueTarget(pregrasp, "fr3_hand_tcp");
    RCLCPP_INFO(node_->get_logger(), "Pre-grasp IK: %s", ik_success ? "SUCCESS" : "FAILED");
    if (!ik_success) {
      return 1;
    }
    const bool pose_target_success = move_group.setPoseTarget(
      pregrasp, "fr3_hand_tcp");
    if (!pose_target_success) {
      RCLCPP_ERROR(node_->get_logger(), "Pre-grasp pose target was rejected.");
      return 1;
    }
    moveit::planning_interface::MoveGroupInterface::Plan plan;
    const bool plan_success =
      move_group.plan(plan) == moveit::core::MoveItErrorCode::SUCCESS;
    RCLCPP_INFO(node_->get_logger(), "Pre-grasp plan: %s", plan_success ? "SUCCESS" : "FAILED");
    if (!plan_success) {
      return 1;
    }
    const bool execute_success =
      move_group.execute(plan) == moveit::core::MoveItErrorCode::SUCCESS;
    RCLCPP_INFO(
      node_->get_logger(), "Pre-grasp execute: %s",
      execute_success ? "SUCCESS" : "FAILED");
    if (!execute_success) {
      return 1;
    }
    RCLCPP_INFO(
      node_->get_logger(),
      "STAGE2A_PASS pregrasp_%s=[%.3f, %.3f, %.3f] "
      "quaternion_map_xyzw=[1,0,0,0] offset=%.3f",
      planning_frame.c_str(), pregrasp.pose.position.x, pregrasp.pose.position.y,
      pregrasp.pose.position.z, kPregraspOffset);
    return 0;
  }

private:
  bool AddTableCollision(
    const geometry_msgs::msg::PoseStamped & target_map,
    const std::string & planning_frame)
  {
    const Table & table = NearestTable(target_map.pose.position);
    geometry_msgs::msg::PoseStamped table_map;
    table_map.header.frame_id = "map";
    table_map.header.stamp = node_->now();
    table_map.pose.position.x = table.x;
    table_map.pose.position.y = table.y;
    table_map.pose.position.z = 0.765;
    tf2::Quaternion orientation;
    orientation.setRPY(0.0, 0.0, 1.57);
    table_map.pose.orientation = tf2::toMsg(orientation);
    geometry_msgs::msg::PoseStamped table_pose;
    try {
      table_pose = tf_buffer_.transform(table_map, planning_frame, tf2::durationFromSec(2.0));
    } catch (const tf2::TransformException & error) {
      RCLCPP_ERROR(node_->get_logger(), "Dining-table TF failed: %s", error.what());
      return false;
    }

    moveit_msgs::msg::CollisionObject object;
    object.header.frame_id = planning_frame;
    object.id = table.name;
    shape_msgs::msg::SolidPrimitive primitive;
    primitive.type = shape_msgs::msg::SolidPrimitive::BOX;
    primitive.dimensions = {0.5, 1.2, 0.03};
    object.primitives.push_back(primitive);
    object.primitive_poses.push_back(table_pose.pose);
    object.operation = moveit_msgs::msg::CollisionObject::ADD;
    moveit::planning_interface::PlanningSceneInterface scene;
    const bool applied = scene.applyCollisionObject(object);
    RCLCPP_INFO(
      node_->get_logger(),
      "Table planning scene: %s id=%s size=[0.5,1.2,0.03] map_center=[%.3f,%.3f,0.765]",
      applied ? "APPLIED" : "FAILED", table.name, table.x, table.y);
    return applied;
  }

  bool ExecuteSafeMotion(moveit::planning_interface::MoveGroupInterface & move_group)
  {
    auto joints = move_group.getCurrentJointValues();
    if (joints.size() != 7) {
      RCLCPP_ERROR(
        node_->get_logger(), "Expected seven current FR3 joint values, got %zu.", joints.size());
      return false;
    }
    const double start_joint7 = joints[6];
    joints[6] -= 0.05;
    move_group.setStartStateToCurrentState();
    if (!move_group.setJointValueTarget(joints)) {
      RCLCPP_ERROR(node_->get_logger(), "Safe-motion joint target was rejected.");
      return false;
    }
    moveit::planning_interface::MoveGroupInterface::Plan plan;
    const bool planned = move_group.plan(plan) == moveit::core::MoveItErrorCode::SUCCESS;
    RCLCPP_INFO(
      node_->get_logger(), "Safe arm-only motion plan: %s",
      planned ? "SUCCESS" : "FAILED");
    if (!planned) {
      return false;
    }
    const bool executed = move_group.execute(plan) == moveit::core::MoveItErrorCode::SUCCESS;
    const auto resulting_joints = move_group.getCurrentJointValues();
    if (resulting_joints.size() == 7) {
      RCLCPP_INFO(
        node_->get_logger(),
        "Safe arm joint7: start=%.4f target=%.4f actual=%.4f delta=%.4f rad",
        start_joint7, joints[6], resulting_joints[6], resulting_joints[6] - start_joint7);
    }
    RCLCPP_INFO(
      node_->get_logger(), "Safe arm-only motion execute: %s", executed ? "SUCCESS" : "FAILED");
    return executed;
  }

  rclcpp::Node::SharedPtr node_;
  tf2_ros::Buffer tf_buffer_;
  tf2_ros::TransformListener tf_listener_;
  rclcpp::Subscription<geometry_msgs::msg::PoseStamped>::SharedPtr target_subscription_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr class_subscription_;
  std::mutex mutex_;
  std::condition_variable condition_;
  geometry_msgs::msg::PoseStamped target_map_;
  std::string target_class_;
  bool target_ready_{false};
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  auto options = rclcpp::NodeOptions().automatically_declare_parameters_from_overrides(true);
  auto node = rclcpp::Node::make_shared("advanced_stage2a_pregrasp", options);
  rclcpp::executors::MultiThreadedExecutor executor;
  executor.add_node(node);
  std::thread spinner([&executor]() {executor.spin();});
  int result = 1;
  try {
    Stage2APregrasp runner(node);
    result = runner.Run();
  } catch (const std::exception & error) {
    RCLCPP_ERROR(node->get_logger(), "Stage 2A pre-grasp failed: %s", error.what());
  }
  rclcpp::shutdown();
  spinner.join();
  return result;
}
