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
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include <ignition/msgs/annotated_axis_aligned_2d_box_v.pb.h>
#include <ignition/msgs/boolean.pb.h>
#include <ignition/msgs/image.pb.h>
#include <ignition/msgs/light.pb.h>
#include <ignition/msgs/pose.pb.h>
#include <ignition/transport/Node.hh>

#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

namespace fs = std::filesystem;

namespace
{
constexpr int kWidth = 640;
constexpr int kHeight = 480;
constexpr double kHiddenZ = -5.0;
constexpr int kFramesAfterChange = 6;
constexpr int kPlanFields = 28;

struct Bounds
{
  double x1{kWidth};
  double y1{kHeight};
  double x2{0.0};
  double y2{0.0};
  bool valid{false};
};

struct Scene
{
  std::string sampleId;
  std::string split;
  int primaryId;
  int secondaryId;
  double primaryX;
  double primaryY;
  double primaryZ;
  double primaryYaw;
  double secondaryX;
  double secondaryY;
  double secondaryZ;
  double secondaryYaw;
  double cameraX;
  double cameraY;
  double cameraZ;
  double cameraPitch;
  double cameraYaw;
  double mainR;
  double mainG;
  double mainB;
  double mainIntensity;
  double mainDx;
  double mainDy;
  double mainDz;
  double fillR;
  double fillG;
  double fillB;
  double fillIntensity;
};

std::vector<std::string> SplitTabs(const std::string & line)
{
  std::vector<std::string> fields;
  std::stringstream stream(line);
  std::string field;
  while (std::getline(stream, field, '\t')) {
    fields.push_back(field);
  }
  return fields;
}

double Number(const std::string & value)
{
  std::size_t consumed = 0;
  const double result = std::stod(value, &consumed);
  if (consumed != value.size() || !std::isfinite(result)) {
    throw std::runtime_error("invalid finite number in capture plan: " + value);
  }
  return result;
}

int Integer(const std::string & value)
{
  std::size_t consumed = 0;
  const int result = std::stoi(value, &consumed);
  if (consumed != value.size()) {
    throw std::runtime_error("invalid integer in capture plan: " + value);
  }
  return result;
}

Scene ParseScene(const std::string & line, int lineNumber)
{
  const auto fields = SplitTabs(line);
  if (fields.size() != kPlanFields) {
    throw std::runtime_error(
            "capture plan line " + std::to_string(lineNumber) + " has " +
            std::to_string(fields.size()) + " fields; expected " +
            std::to_string(kPlanFields));
  }
  if (fields[1] != "train" && fields[1] != "val") {
    throw std::runtime_error("invalid split in capture plan: " + fields[1]);
  }
  return {
    fields[0], fields[1], Integer(fields[2]), Integer(fields[3]),
    Number(fields[4]), Number(fields[5]), Number(fields[6]), Number(fields[7]),
    Number(fields[8]), Number(fields[9]), Number(fields[10]), Number(fields[11]),
    Number(fields[12]), Number(fields[13]), Number(fields[14]), Number(fields[15]),
    Number(fields[16]), Number(fields[17]), Number(fields[18]), Number(fields[19]),
    Number(fields[20]), Number(fields[21]), Number(fields[22]), Number(fields[23]),
    Number(fields[24]), Number(fields[25]), Number(fields[26]), Number(fields[27])};
}

std::vector<Scene> LoadPlan(const fs::path & path)
{
  std::ifstream stream(path);
  if (!stream) {
    throw std::runtime_error("cannot open capture plan: " + path.string());
  }
  std::string line;
  if (!std::getline(stream, line)) {
    throw std::runtime_error("capture plan is empty");
  }
  std::vector<Scene> scenes;
  int lineNumber = 1;
  while (std::getline(stream, line)) {
    ++lineNumber;
    if (!line.empty()) {
      scenes.push_back(ParseScene(line, lineNumber));
    }
  }
  if (scenes.empty()) {
    throw std::runtime_error("capture plan contains no scenes");
  }
  return scenes;
}

class CaptureWorker
{
public:
  CaptureWorker(
    fs::path output, double minBoxArea, std::vector<std::string> classNames)
  : output_(std::move(output)), minBoxArea_(minBoxArea),
    classNames_(std::move(classNames))
  {
    if (!node_.Subscribe("/training/rgb", &CaptureWorker::OnImage, this)) {
      throw std::runtime_error("failed to subscribe /training/rgb");
    }
    if (!node_.Subscribe("/training/boxes", &CaptureWorker::OnBoxes, this)) {
      throw std::runtime_error("failed to subscribe /training/boxes");
    }
  }

  void Run(const std::vector<Scene> & scenes)
  {
    WaitForSensors();
    for (std::size_t index = 0; index < scenes.size(); ++index) {
      Capture(scenes[index]);
      std::cout << "PROGRESS " << (index + 1) << '/' << scenes.size()
                << ' ' << scenes[index].sampleId << std::endl;
    }
  }

private:
  void OnImage(const ignition::msgs::Image & message)
  {
    std::lock_guard<std::mutex> lock(mutex_);
    image_ = message;
    ++imageSequence_;
    condition_.notify_all();
  }

  void OnBoxes(const ignition::msgs::AnnotatedAxisAligned2DBox_V & message)
  {
    std::lock_guard<std::mutex> lock(mutex_);
    boxes_ = message;
    ++boxSequence_;
    condition_.notify_all();
  }

  void WaitForSensors()
  {
    std::unique_lock<std::mutex> lock(mutex_);
    if (!condition_.wait_for(
        lock, std::chrono::seconds(30),
        [this] {return imageSequence_ > 0 && boxSequence_ > 0;}))
    {
      throw std::runtime_error("timed out waiting for Gazebo RGB / bbox topics");
    }
  }

  static ignition::msgs::Pose MakePose(
    const std::string & name, double x, double y, double z,
    double roll, double pitch, double yaw)
  {
    const double cr = std::cos(roll * 0.5);
    const double sr = std::sin(roll * 0.5);
    const double cp = std::cos(pitch * 0.5);
    const double sp = std::sin(pitch * 0.5);
    const double cy = std::cos(yaw * 0.5);
    const double sy = std::sin(yaw * 0.5);
    ignition::msgs::Pose pose;
    pose.set_name(name);
    pose.mutable_position()->set_x(x);
    pose.mutable_position()->set_y(y);
    pose.mutable_position()->set_z(z);
    pose.mutable_orientation()->set_w(cr * cp * cy + sr * sp * sy);
    pose.mutable_orientation()->set_x(sr * cp * cy - cr * sp * sy);
    pose.mutable_orientation()->set_y(cr * sp * cy + sr * cp * sy);
    pose.mutable_orientation()->set_z(cr * cp * sy - sr * sp * cy);
    return pose;
  }

  void SetPose(const ignition::msgs::Pose & pose)
  {
    ignition::msgs::Boolean reply;
    bool result = false;
    for (int attempt = 0; attempt < 20; ++attempt) {
      const bool executed = node_.Request(
        "/world/formal_objects_dataset_v2/set_pose", pose, 1000u, reply, result);
      if (executed && result && reply.data()) {
        return;
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(200));
    }
    throw std::runtime_error("set_pose failed for entity " + pose.name());
  }

  void SetLight(
    const std::string & name, double r, double g, double b,
    double intensity, double dx, double dy, double dz, bool shadows)
  {
    ignition::msgs::Light light;
    light.set_name(name);
    light.set_type(ignition::msgs::Light::DIRECTIONAL);
    light.mutable_diffuse()->set_r(r);
    light.mutable_diffuse()->set_g(g);
    light.mutable_diffuse()->set_b(b);
    light.mutable_diffuse()->set_a(1.0);
    light.mutable_specular()->set_r(r * 0.2);
    light.mutable_specular()->set_g(g * 0.2);
    light.mutable_specular()->set_b(b * 0.2);
    light.mutable_specular()->set_a(1.0);
    light.mutable_direction()->set_x(dx);
    light.mutable_direction()->set_y(dy);
    light.mutable_direction()->set_z(dz);
    light.set_intensity(intensity);
    light.set_cast_shadows(shadows);
    ignition::msgs::Boolean reply;
    bool result = false;
    const bool executed = node_.Request(
      "/world/formal_objects_dataset_v2/light_config", light, 2000u, reply, result);
    if (!executed || !result || !reply.data()) {
      throw std::runtime_error("light_config failed for " + name);
    }
  }

  std::pair<std::uint64_t, std::uint64_t> Sequences()
  {
    std::lock_guard<std::mutex> lock(mutex_);
    return {imageSequence_, boxSequence_};
  }

  void WaitForFreshFrames(std::uint64_t imageStart, std::uint64_t boxStart)
  {
    std::unique_lock<std::mutex> lock(mutex_);
    if (!condition_.wait_for(
        lock, std::chrono::seconds(8),
        [this, imageStart, boxStart]
        {
          return imageSequence_ >= imageStart + kFramesAfterChange &&
                 boxSequence_ >= boxStart + kFramesAfterChange;
        }))
    {
      throw std::runtime_error("timed out waiting for fresh sensor frames");
    }
  }

  void HidePreviousObjects()
  {
    for (const int classId : activeClasses_) {
      SetPose(MakePose(classNames_.at(classId), 0.0, 0.0, kHiddenZ, 0.0, 0.0, 0.0));
    }
    activeClasses_.clear();
  }

  void Capture(const Scene & scene)
  {
    HidePreviousObjects();
    const auto [imageStart, boxStart] = Sequences();
    if (scene.primaryId >= 0) {
      SetPose(MakePose(
          classNames_.at(scene.primaryId), scene.primaryX, scene.primaryY,
          scene.primaryZ, 0.0, 0.0, scene.primaryYaw));
      activeClasses_.push_back(scene.primaryId);
    }
    if (scene.secondaryId >= 0) {
      SetPose(MakePose(
          classNames_.at(scene.secondaryId), scene.secondaryX, scene.secondaryY,
          scene.secondaryZ, 0.0, 0.0, scene.secondaryYaw));
      activeClasses_.push_back(scene.secondaryId);
    }
    SetLight(
      "sun", scene.mainR, scene.mainG, scene.mainB, scene.mainIntensity,
      scene.mainDx, scene.mainDy, scene.mainDz, true);
    SetLight(
      "ambient_fill", scene.fillR, scene.fillG, scene.fillB,
      scene.fillIntensity, -scene.mainDx, -scene.mainDy, scene.mainDz, false);
    SetPose(MakePose(
        "training_camera", scene.cameraX, scene.cameraY, scene.cameraZ,
        0.0, scene.cameraPitch, scene.cameraYaw));
    WaitForFreshFrames(imageStart, boxStart);

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
      throw std::runtime_error("unexpected RGB layout for " + scene.sampleId);
    }

    std::map<int, Bounds> merged;
    for (const auto & annotated : boxes.annotated_box()) {
      const int label = static_cast<int>(annotated.label());
      if (label < 1 || label > static_cast<int>(classNames_.size())) {
        continue;
      }
      const auto & box = annotated.box();
      const double x1 = std::clamp(box.min_corner().x(), 0.0, static_cast<double>(kWidth));
      const double y1 = std::clamp(box.min_corner().y(), 0.0, static_cast<double>(kHeight));
      const double x2 = std::clamp(box.max_corner().x(), 0.0, static_cast<double>(kWidth));
      const double y2 = std::clamp(box.max_corner().y(), 0.0, static_cast<double>(kHeight));
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
        throw std::runtime_error("planned object is not visible in " + scene.sampleId);
      }
      const Bounds & box = found->second;
      if ((box.x2 - box.x1) * (box.y2 - box.y1) < minBoxArea_) {
        throw std::runtime_error("planned bbox is below minimum area in " + scene.sampleId);
      }
    }

    cv::Mat rgb(
      kHeight, kWidth, CV_8UC3, const_cast<char *>(image.data().data()), image.step());
    cv::Mat bgr;
    cv::cvtColor(rgb, bgr, cv::COLOR_RGB2BGR);
    const fs::path imagePath = output_ / "images" / scene.split / (scene.sampleId + ".png");
    const fs::path labelPath = output_ / "labels" / scene.split / (scene.sampleId + ".txt");
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
      labelFile << classId << ' '
                << ((box.x1 + box.x2) * 0.5) / kWidth << ' '
                << ((box.y1 + box.y2) * 0.5) / kHeight << ' '
                << (box.x2 - box.x1) / kWidth << ' '
                << (box.y2 - box.y1) / kHeight << '\n';
    }
  }

  fs::path output_;
  double minBoxArea_;
  std::vector<std::string> classNames_;
  std::vector<int> activeClasses_;
  ignition::transport::Node node_;
  std::mutex mutex_;
  std::condition_variable condition_;
  ignition::msgs::Image image_;
  ignition::msgs::AnnotatedAxisAligned2DBox_V boxes_;
  std::uint64_t imageSequence_{0};
  std::uint64_t boxSequence_{0};
};
}  // namespace

int main(int argc, char ** argv)
{
  try {
    if (argc < 6) {
      throw std::runtime_error(
              "usage: capture_worker_v2 PLAN OUTPUT MIN_AREA CLASS_COUNT CLASS_NAMES...");
    }
    const int classCount = Integer(argv[4]);
    if (classCount < 2 || argc != 5 + classCount) {
      throw std::runtime_error("class count does not match class names");
    }
    std::vector<std::string> classNames;
    for (int index = 0; index < classCount; ++index) {
      classNames.emplace_back(argv[5 + index]);
    }
    const auto scenes = LoadPlan(argv[1]);
    CaptureWorker worker(argv[2], Number(argv[3]), std::move(classNames));
    worker.Run(scenes);
    return 0;
  } catch (const std::exception & error) {
    std::cerr << "ERROR " << error.what() << std::endl;
    return 1;
  }
}
