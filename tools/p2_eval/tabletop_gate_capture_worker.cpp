#include <algorithm>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include <ignition/msgs/annotated_axis_aligned_2d_box_v.pb.h>
#include <ignition/msgs/boolean.pb.h>
#include <ignition/msgs/image.pb.h>
#include <ignition/msgs/pose.pb.h>
#include <ignition/transport/Node.hh>

#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

namespace fs = std::filesystem;

namespace
{
constexpr int kWidth = 640;
constexpr int kHeight = 480;
constexpr double kCameraForwardOffset = 0.20;
constexpr double kCameraHeight = 0.90;
constexpr double kCameraPitch = 0.1745329252;
constexpr double kHiddenZ = -5.0;
constexpr int kDefaultYawSamples = 24;
constexpr int kFreshFrames = 2;

struct Viewpoint
{
  int index;
  double x;
  double y;
  double yaw;
};

struct Placement
{
  std::string id;
  std::string className;
  std::string entityName;
  int gazeboLabel;
  double localX;
  double localY;
  double worldX;
  double worldY;
  double worldZ;
  double worldYaw;
  std::string region;
};

struct Bounds
{
  double x1{0.0};
  double y1{0.0};
  double x2{0.0};
  double y2{0.0};
  bool valid{false};
};

struct Plan
{
  std::string worldName;
  std::string cameraName;
  int yawSamples{kDefaultYawSamples};
  std::vector<Viewpoint> viewpoints;
  std::vector<std::string> hiddenEntities;
  std::vector<Placement> placements;
};

ignition::msgs::Pose MakePose(
  const std::string & _name, double _x, double _y, double _z,
  double _roll, double _pitch, double _yaw)
{
  const double cr = std::cos(_roll * 0.5);
  const double sr = std::sin(_roll * 0.5);
  const double cp = std::cos(_pitch * 0.5);
  const double sp = std::sin(_pitch * 0.5);
  const double cy = std::cos(_yaw * 0.5);
  const double sy = std::sin(_yaw * 0.5);
  ignition::msgs::Pose pose;
  pose.set_name(_name);
  pose.mutable_position()->set_x(_x);
  pose.mutable_position()->set_y(_y);
  pose.mutable_position()->set_z(_z);
  pose.mutable_orientation()->set_w(cr * cp * cy + sr * sp * sy);
  pose.mutable_orientation()->set_x(sr * cp * cy - cr * sp * sy);
  pose.mutable_orientation()->set_y(cr * sp * cy + sr * cp * sy);
  pose.mutable_orientation()->set_z(cr * cp * sy - sr * sp * cy);
  return pose;
}

Plan ReadPlan(const fs::path & _path)
{
  std::ifstream stream(_path);
  if (!stream) {
    throw std::runtime_error("cannot open capture plan " + _path.string());
  }
  Plan plan;
  std::string line;
  while (std::getline(stream, line)) {
    if (line.empty() || line.front() == '#') {
      continue;
    }
    std::istringstream values(line);
    std::string kind;
    values >> kind;
    if (kind == "WORLD") {
      values >> plan.worldName >> plan.cameraName;
    } else if (kind == "YAW_SAMPLES") {
      values >> plan.yawSamples;
    } else if (kind == "VIEW") {
      Viewpoint viewpoint{};
      values >> viewpoint.index >> viewpoint.x >> viewpoint.y >> viewpoint.yaw;
      plan.viewpoints.push_back(viewpoint);
    } else if (kind == "HIDE") {
      std::string entity;
      values >> entity;
      plan.hiddenEntities.push_back(entity);
    } else if (kind == "PLACEMENT") {
      Placement placement{};
      values >> placement.id >> placement.className >> placement.entityName >>
      placement.gazeboLabel >> placement.localX >> placement.localY >>
      placement.worldX >> placement.worldY >> placement.worldZ >>
      placement.worldYaw >> placement.region;
      plan.placements.push_back(placement);
    } else {
      throw std::runtime_error("unknown plan record: " + kind);
    }
    if (!values) {
      throw std::runtime_error("malformed capture plan record: " + line);
    }
  }
  if (plan.worldName.empty() || plan.cameraName.empty() ||
    plan.viewpoints.size() < 2 || plan.placements.empty() ||
    plan.yawSamples <= 0)
  {
    throw std::runtime_error("capture plan is incomplete");
  }
  return plan;
}

class CaptureWorker
{
public:
  CaptureWorker(fs::path output, Plan plan)
  : output_(std::move(output)), plan_(std::move(plan))
  {
    if (!node_.Subscribe("/p2_gate/rgb", &CaptureWorker::OnImage, this)) {
      throw std::runtime_error("failed to subscribe /p2_gate/rgb");
    }
    if (!node_.Subscribe("/p2_gate/boxes", &CaptureWorker::OnBoxes, this)) {
      throw std::runtime_error("failed to subscribe /p2_gate/boxes");
    }
  }

  void Run()
  {
    fs::create_directories(output_ / "frames");
    manifest_.open(output_ / "frames.tsv");
    if (!manifest_) {
      throw std::runtime_error("cannot create frames.tsv");
    }
    manifest_ << "image\tplacement_id\tclass_name\tregion\tlocal_x\tlocal_y\t"
      "world_x\tworld_y\tviewpoint\tyaw_index\tcamera_base_x\t"
      "camera_base_y\tcamera_yaw\ttruth_visible\ttruth_x1\ttruth_y1\t"
      "truth_x2\ttruth_y2\n";
    WaitForSensors();
    for (const auto & entity : plan_.hiddenEntities) {
      SetPose(MakePose(entity, 0.0, 0.0, kHiddenZ, 0.0, 0.0, 0.0));
    }
    const std::size_t total = plan_.placements.size();
    for (std::size_t index = 0; index < total; ++index) {
      CapturePlacement(plan_.placements[index]);
      std::cout << "PROGRESS " << (index + 1) << '/' << total << std::endl;
    }
  }

private:
  void OnImage(const ignition::msgs::Image & _message)
  {
    std::lock_guard<std::mutex> lock(mutex_);
    image_ = _message;
    ++imageSequence_;
    condition_.notify_all();
  }

  void OnBoxes(
    const ignition::msgs::AnnotatedAxisAligned2DBox_V & _message)
  {
    std::lock_guard<std::mutex> lock(mutex_);
    boxes_ = _message;
    ++boxSequence_;
    condition_.notify_all();
  }

  void WaitForSensors()
  {
    std::unique_lock<std::mutex> lock(mutex_);
    if (!condition_.wait_for(
        lock, std::chrono::seconds(45), [this]
        {return imageSequence_ > 0 && boxSequence_ > 0;}))
    {
      throw std::runtime_error("timed out waiting for evaluation camera");
    }
  }

  std::pair<std::uint64_t, std::uint64_t> Sequences()
  {
    std::lock_guard<std::mutex> lock(mutex_);
    return {imageSequence_, boxSequence_};
  }

  void WaitForFreshFrames(
    std::uint64_t _imageStart, std::uint64_t _boxStart, int _count)
  {
    std::unique_lock<std::mutex> lock(mutex_);
    if (!condition_.wait_for(
        lock, std::chrono::seconds(5), [this, _imageStart, _boxStart, _count]
        {
          return imageSequence_ >= _imageStart + _count &&
          boxSequence_ >= _boxStart + _count;
        }))
    {
      throw std::runtime_error("timed out waiting for fresh camera frames");
    }
  }

  void SetPose(const ignition::msgs::Pose & _pose)
  {
    ignition::msgs::Boolean reply;
    bool result = false;
    const std::string service = "/world/" + plan_.worldName + "/set_pose";
    for (int attempt = 0; attempt < 20; ++attempt) {
      const bool executed = node_.Request(
        service, _pose, 1000u, reply, result);
      if (executed && result && reply.data()) {
        return;
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(250));
    }
    throw std::runtime_error("set_pose failed for entity " + _pose.name());
  }

  Bounds TruthBounds(int _label, const ignition::msgs::AnnotatedAxisAligned2DBox_V & _boxes)
  {
    Bounds merged;
    for (const auto & annotated : _boxes.annotated_box()) {
      if (static_cast<int>(annotated.label()) != _label) {
        continue;
      }
      const auto & box = annotated.box();
      const double x1 = std::clamp(box.min_corner().x(), 0.0, 640.0);
      const double y1 = std::clamp(box.min_corner().y(), 0.0, 480.0);
      const double x2 = std::clamp(box.max_corner().x(), 0.0, 640.0);
      const double y2 = std::clamp(box.max_corner().y(), 0.0, 480.0);
      if (x2 <= x1 || y2 <= y1) {
        continue;
      }
      if (!merged.valid) {
        merged = {x1, y1, x2, y2, true};
      } else {
        merged.x1 = std::min(merged.x1, x1);
        merged.y1 = std::min(merged.y1, y1);
        merged.x2 = std::max(merged.x2, x2);
        merged.y2 = std::max(merged.y2, y2);
      }
    }
    return merged;
  }

  void CapturePlacement(const Placement & _placement)
  {
    for (const auto & entity : plan_.hiddenEntities) {
      SetPose(MakePose(entity, 0.0, 0.0, kHiddenZ, 0.0, 0.0, 0.0));
    }
    auto start = Sequences();
    SetPose(
      MakePose(
        _placement.entityName, _placement.worldX, _placement.worldY,
        _placement.worldZ, 0.0, 0.0, _placement.worldYaw));
    WaitForFreshFrames(start.first, start.second, 4);

    for (const auto & viewpoint : plan_.viewpoints) {
      for (int yawIndex = 0; yawIndex < plan_.yawSamples; ++yawIndex) {
        const double yaw = viewpoint.yaw +
          yawIndex * 2.0 * M_PI / plan_.yawSamples;
        const double cameraX = viewpoint.x + kCameraForwardOffset * std::cos(yaw);
        const double cameraY = viewpoint.y + kCameraForwardOffset * std::sin(yaw);
        start = Sequences();
        SetPose(
          MakePose(
            plan_.cameraName, cameraX, cameraY, kCameraHeight,
            0.0, kCameraPitch, yaw));
        WaitForFreshFrames(start.first, start.second, kFreshFrames);
        SaveFrame(_placement, viewpoint, yawIndex, yaw);
      }
    }
  }

  void SaveFrame(
    const Placement & _placement, const Viewpoint & _viewpoint,
    int _yawIndex, double _cameraYaw)
  {
    ignition::msgs::Image image;
    ignition::msgs::AnnotatedAxisAligned2DBox_V boxes;
    {
      std::lock_guard<std::mutex> lock(mutex_);
      image = image_;
      boxes = boxes_;
    }
    if (image.width() != kWidth || image.height() != kHeight ||
      image.step() < kWidth * 3 || image.data().size() <
      static_cast<std::size_t>(image.step()) * kHeight)
    {
      throw std::runtime_error("unexpected RGB image layout");
    }
    cv::Mat rgb(
      kHeight, kWidth, CV_8UC3, const_cast<char *>(image.data().data()),
      image.step());
    cv::Mat bgr;
    cv::cvtColor(rgb, bgr, cv::COLOR_RGB2BGR);
    std::ostringstream name;
    name << _placement.id << "_v" << _viewpoint.index << "_y" <<
      std::setw(2) << std::setfill('0') << _yawIndex << ".png";
    const fs::path path = output_ / "frames" / name.str();
    if (!cv::imwrite(path.string(), bgr)) {
      throw std::runtime_error("failed to save " + path.string());
    }
    const Bounds truth = TruthBounds(_placement.gazeboLabel, boxes);
    manifest_ << std::setprecision(12) << path.string() << '\t' <<
      _placement.id << '\t' << _placement.className << '\t' <<
      _placement.region << '\t' << _placement.localX << '\t' <<
      _placement.localY << '\t' << _placement.worldX << '\t' <<
      _placement.worldY << '\t' << _viewpoint.index << '\t' <<
      _yawIndex << '\t' << _viewpoint.x << '\t' << _viewpoint.y << '\t' <<
      _cameraYaw << '\t' << (truth.valid ? 1 : 0) << '\t' << truth.x1 <<
      '\t' << truth.y1 << '\t' << truth.x2 << '\t' << truth.y2 << '\n';
  }

  fs::path output_;
  Plan plan_;
  ignition::transport::Node node_;
  std::mutex mutex_;
  std::condition_variable condition_;
  ignition::msgs::Image image_;
  ignition::msgs::AnnotatedAxisAligned2DBox_V boxes_;
  std::uint64_t imageSequence_{0};
  std::uint64_t boxSequence_{0};
  std::ofstream manifest_;
};
}  // namespace

int main(int argc, char ** argv)
{
  if (argc != 3) {
    std::cerr << "usage: tabletop_gate_capture_worker OUTPUT PLAN" << std::endl;
    return 2;
  }
  try {
    CaptureWorker worker(argv[1], ReadPlan(argv[2]));
    worker.Run();
    return 0;
  } catch (const std::exception & error) {
    std::cerr << "ERROR " << error.what() << std::endl;
    return 1;
  }
}
