#include <algorithm>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <mutex>
#include <random>
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
constexpr double kTableTopZ = 0.75;
constexpr double kTargetZ = 0.82;
constexpr double kHiddenZ = -5.0;
constexpr int kFramesAfterPose = 5;

struct Pose2
{
  double x;
  double y;
  double yaw;
};

struct Bounds
{
  double x1{kWidth};
  double y1{kHeight};
  double x2{0.0};
  double y2{0.0};
  bool valid{false};
};

struct Range
{
  double low;
  double high;
};

struct Settings
{
  fs::path output;
  int trainCount;
  int valCount;
  std::uint32_t seed;
  double minBoxArea;
  double secondaryFraction;
  Range objectX;
  Range objectY;
  Range objectYaw;
  double minObjectSpacing;
  Range cameraDistance;
  Range cameraHeight;
  Range cameraLateral;
  Range cameraYawJitter;
  Range cameraPitchJitter;
  std::vector<std::string> classNames;
};

class CaptureWorker
{
public:
  explicit CaptureWorker(Settings settings)
  : settings_(std::move(settings)), rng_(settings_.seed),
    instanceCounts_(settings_.classNames.size(), 0)
  {
    if (!node_.Subscribe("/training/rgb", &CaptureWorker::OnImage, this)) {
      throw std::runtime_error("failed to subscribe /training/rgb");
    }
    if (!node_.Subscribe("/training/boxes", &CaptureWorker::OnBoxes, this)) {
      throw std::runtime_error("failed to subscribe /training/boxes");
    }
  }

  void Run()
  {
    WaitForSensors();
    GenerateSplit("train", settings_.trainCount);
    GenerateSplit("val", settings_.valCount);
    std::cout << "STATS train_images=" << settings_.trainCount
              << " val_images=" << settings_.valCount;
    for (std::size_t index = 0; index < settings_.classNames.size(); ++index) {
      std::cout << ' ' << settings_.classNames[index]
                << "_instances=" << instanceCounts_[index];
    }
    std::cout << std::endl;
  }

private:
  void OnImage(const ignition::msgs::Image & _msg)
  {
    std::lock_guard<std::mutex> lock(mutex_);
    image_ = _msg;
    ++imageSequence_;
    condition_.notify_all();
  }

  void OnBoxes(const ignition::msgs::AnnotatedAxisAligned2DBox_V & _msg)
  {
    std::lock_guard<std::mutex> lock(mutex_);
    boxes_ = _msg;
    ++boxSequence_;
    condition_.notify_all();
  }

  void WaitForSensors()
  {
    std::unique_lock<std::mutex> lock(mutex_);
    if (!condition_.wait_for(
        lock, std::chrono::seconds(30), [this]
        {return imageSequence_ > 0 && boxSequence_ > 0;}))
    {
      throw std::runtime_error("timed out waiting for Gazebo RGB / bbox topics");
    }
  }

  double Uniform(const Range & _range)
  {
    return std::uniform_real_distribution<double>(
      _range.low, _range.high)(rng_);
  }

  Pose2 RandomObjectPose()
  {
    return {
      Uniform(settings_.objectX), Uniform(settings_.objectY),
      Uniform(settings_.objectYaw)};
  }

  static ignition::msgs::Pose MakePose(
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

  void SetPose(const ignition::msgs::Pose & _pose)
  {
    ignition::msgs::Boolean reply;
    bool result = false;
    for (int attempt = 0; attempt < 20; ++attempt) {
      const bool executed = node_.Request(
        "/world/formal_objects_dataset/set_pose", _pose, 1000u,
        reply, result);
      if (executed && result && reply.data()) {
        return;
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(250));
    }
    throw std::runtime_error("set_pose failed for entity " + _pose.name());
  }

  std::pair<Pose2, Pose2> RandomObjectPair()
  {
    for (int attempt = 0; attempt < 100; ++attempt) {
      const Pose2 first = RandomObjectPose();
      const Pose2 second = RandomObjectPose();
      if (std::hypot(first.x - second.x, first.y - second.y) >=
        settings_.minObjectSpacing)
      {
        return {first, second};
      }
    }
    throw std::runtime_error("could not sample non-overlapping object poses");
  }

  std::pair<std::uint64_t, std::uint64_t> Sequences()
  {
    std::lock_guard<std::mutex> lock(mutex_);
    return {imageSequence_, boxSequence_};
  }

  void WaitForFreshFrames(std::uint64_t _imageStart, std::uint64_t _boxStart)
  {
    std::unique_lock<std::mutex> lock(mutex_);
    const bool ready = condition_.wait_for(
      lock, std::chrono::seconds(5), [this, _imageStart, _boxStart]
      {
        return imageSequence_ >= _imageStart + kFramesAfterPose &&
        boxSequence_ >= _boxStart + kFramesAfterPose;
      });
    if (!ready) {
      throw std::runtime_error("timed out waiting for fresh sensor frames");
    }
  }

  void HidePreviousObjects()
  {
    for (const int classId : activeClasses_) {
      SetPose(
        MakePose(
          settings_.classNames.at(classId), 0.0, 0.0, kHiddenZ,
          0.0, 0.0, 0.0));
    }
    activeClasses_.clear();
  }

  int RandomSecondaryClass(int _primaryClass)
  {
    std::uniform_int_distribution<int> distribution(
      0, static_cast<int>(settings_.classNames.size()) - 2);
    int selected = distribution(rng_);
    if (selected >= _primaryClass) {
      ++selected;
    }
    return selected;
  }

  bool CaptureOne(
    const std::string & _split, int _index, int _primaryClass,
    bool _wantSecondary)
  {
    HidePreviousObjects();
    const int secondaryClass = _wantSecondary ?
      RandomSecondaryClass(_primaryClass) : -1;
    const auto [primaryPose, secondaryPose] = RandomObjectPair();

    double targetX = primaryPose.x;
    double targetY = primaryPose.y;
    if (_wantSecondary) {
      targetX = (primaryPose.x + secondaryPose.x) * 0.5;
      targetY = (primaryPose.y + secondaryPose.y) * 0.5;
    }
    const double distance = Uniform(settings_.cameraDistance);
    const double cameraY = targetY + Uniform(settings_.cameraLateral);
    const double cameraX = targetX - distance;
    const double cameraZ = Uniform(settings_.cameraHeight);
    const double horizontal = std::hypot(
      targetX - cameraX, targetY - cameraY);
    const double yaw = std::atan2(
      targetY - cameraY, targetX - cameraX) +
      Uniform(settings_.cameraYawJitter);
    const double pitch = std::atan2(cameraZ - kTargetZ, horizontal) +
      Uniform(settings_.cameraPitchJitter);

    const auto [imageStart, boxStart] = Sequences();
    SetPose(
      MakePose(
        settings_.classNames.at(_primaryClass), primaryPose.x, primaryPose.y,
        kTableTopZ, 0.0, 0.0, primaryPose.yaw));
    activeClasses_.push_back(_primaryClass);
    if (_wantSecondary) {
      SetPose(
        MakePose(
          settings_.classNames.at(secondaryClass), secondaryPose.x,
          secondaryPose.y, kTableTopZ, 0.0, 0.0, secondaryPose.yaw));
      activeClasses_.push_back(secondaryClass);
    }
    SetPose(
      MakePose(
        "training_camera", cameraX, cameraY, cameraZ, 0.0, pitch, yaw));
    WaitForFreshFrames(imageStart, boxStart);

    ignition::msgs::Image image;
    ignition::msgs::AnnotatedAxisAligned2DBox_V boxes;
    {
      std::lock_guard<std::mutex> lock(mutex_);
      image = image_;
      boxes = boxes_;
    }
    if (image.width() != kWidth || image.height() != kHeight ||
      image.step() < kWidth * 3 ||
      image.data().size() <
      static_cast<std::size_t>(image.step()) * kHeight)
    {
      throw std::runtime_error("unexpected RGB image layout from Gazebo");
    }

    std::map<int, Bounds> merged;
    for (const auto & annotated : boxes.annotated_box()) {
      const int label = static_cast<int>(annotated.label());
      if (label < 1 ||
        label > static_cast<int>(settings_.classNames.size()))
      {
        continue;
      }
      const auto & box = annotated.box();
      const double x1 = std::clamp(
        box.min_corner().x(), 0.0, static_cast<double>(kWidth));
      const double y1 = std::clamp(
        box.min_corner().y(), 0.0, static_cast<double>(kHeight));
      const double x2 = std::clamp(
        box.max_corner().x(), 0.0, static_cast<double>(kWidth));
      const double y2 = std::clamp(
        box.max_corner().y(), 0.0, static_cast<double>(kHeight));
      if (x2 <= x1 || y2 <= y1) {
        continue;
      }
      auto & destination = merged[label];
      if (!destination.valid) {
        destination = {x1, y1, x2, y2, true};
      } else {
        destination.x1 = std::min(destination.x1, x1);
        destination.y1 = std::min(destination.y1, y1);
        destination.x2 = std::max(destination.x2, x2);
        destination.y2 = std::max(destination.y2, y2);
      }
    }

    for (const int classId : activeClasses_) {
      const auto found = merged.find(classId + 1);
      if (found == merged.end()) {
        return false;
      }
      const Bounds & box = found->second;
      if ((box.x2 - box.x1) * (box.y2 - box.y1) < settings_.minBoxArea) {
        return false;
      }
    }

    cv::Mat rgb(
      kHeight, kWidth, CV_8UC3, const_cast<char *>(image.data().data()),
      image.step());
    cv::Mat bgr;
    cv::cvtColor(rgb, bgr, cv::COLOR_RGB2BGR);

    std::ostringstream stem;
    stem << _split << '_' << std::setw(6) << std::setfill('0') << _index;
    const fs::path imagePath = settings_.output / "images" / _split /
      (stem.str() + ".png");
    const fs::path labelPath = settings_.output / "labels" / _split /
      (stem.str() + ".txt");
    if (!cv::imwrite(imagePath.string(), bgr)) {
      throw std::runtime_error("failed to write " + imagePath.string());
    }

    std::ofstream labelFile(labelPath);
    if (!labelFile) {
      throw std::runtime_error("failed to write " + labelPath.string());
    }
    labelFile << std::fixed << std::setprecision(8);
    for (const int classId : activeClasses_) {
      const Bounds & box = merged.at(classId + 1);
      const double centerX = ((box.x1 + box.x2) * 0.5) / kWidth;
      const double centerY = ((box.y1 + box.y2) * 0.5) / kHeight;
      const double width = (box.x2 - box.x1) / kWidth;
      const double height = (box.y2 - box.y1) / kHeight;
      labelFile << classId << ' ' << centerX << ' ' << centerY << ' '
                << width << ' ' << height << '\n';
      ++instanceCounts_.at(classId);
    }
    return true;
  }

  void GenerateSplit(const std::string & _split, int _count)
  {
    std::vector<int> primaryClasses(_count);
    for (int index = 0; index < _count; ++index) {
      primaryClasses[index] =
        index % static_cast<int>(settings_.classNames.size());
    }
    std::shuffle(primaryClasses.begin(), primaryClasses.end(), rng_);
    std::bernoulli_distribution useSecondary(settings_.secondaryFraction);

    for (int index = 0; index < _count; ++index) {
      const bool wantSecondary = useSecondary(rng_);
      bool saved = false;
      for (int attempt = 0; attempt < 20 && !saved; ++attempt) {
        saved = CaptureOne(
          _split, index, primaryClasses[index], wantSecondary);
      }
      if (!saved) {
        throw std::runtime_error(
                "could not produce a valid " + _split +
                " sample after 20 attempts");
      }
      if ((index + 1) % 20 == 0 || index + 1 == _count) {
        std::cout << "PROGRESS " << _split << ' ' << (index + 1)
                  << '/' << _count << std::endl;
      }
    }
  }

  Settings settings_;
  std::mt19937 rng_;
  ignition::transport::Node node_;
  std::mutex mutex_;
  std::condition_variable condition_;
  ignition::msgs::Image image_;
  ignition::msgs::AnnotatedAxisAligned2DBox_V boxes_;
  std::uint64_t imageSequence_{0};
  std::uint64_t boxSequence_{0};
  std::vector<int> activeClasses_;
  std::vector<int> instanceCounts_;
};

double Number(const char * _value)
{
  return std::stod(_value);
}

Settings ParseArguments(int argc, char ** argv)
{
  constexpr int fixedArgumentCount = 24;
  if (argc < fixedArgumentCount + 2) {
    throw std::runtime_error(
            "usage: capture_worker OUTPUT TRAIN VAL SEED MIN_AREA SECONDARY "
            "OBJ_X_MIN OBJ_X_MAX OBJ_Y_MIN OBJ_Y_MAX OBJ_YAW_MIN OBJ_YAW_MAX "
            "MIN_SPACING CAM_DIST_MIN CAM_DIST_MAX CAM_H_MIN CAM_H_MAX "
            "CAM_LAT_MIN CAM_LAT_MAX YAW_JITTER_MIN YAW_JITTER_MAX "
            "PITCH_JITTER_MIN PITCH_JITTER_MAX CLASS_COUNT CLASS_NAMES...");
  }
  const int classCount = std::stoi(argv[24]);
  if (classCount < 2 || argc != fixedArgumentCount + classCount + 1) {
    throw std::runtime_error("class count does not match class name arguments");
  }

  std::vector<std::string> classNames;
  classNames.reserve(classCount);
  for (int index = 0; index < classCount; ++index) {
    classNames.emplace_back(argv[25 + index]);
  }

  return {
    argv[1], std::stoi(argv[2]), std::stoi(argv[3]),
    static_cast<std::uint32_t>(std::stoul(argv[4])), Number(argv[5]),
    Number(argv[6]), {Number(argv[7]), Number(argv[8])},
    {Number(argv[9]), Number(argv[10])},
    {Number(argv[11]), Number(argv[12])}, Number(argv[13]),
    {Number(argv[14]), Number(argv[15])},
    {Number(argv[16]), Number(argv[17])},
    {Number(argv[18]), Number(argv[19])},
    {Number(argv[20]), Number(argv[21])},
    {Number(argv[22]), Number(argv[23])}, std::move(classNames)};
}
}  // namespace

int main(int argc, char ** argv)
{
  try {
    CaptureWorker worker(ParseArguments(argc, argv));
    worker.Run();
    return 0;
  } catch (const std::exception & error) {
    std::cerr << "ERROR " << error.what() << std::endl;
    return 1;
  }
}
