#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 MAP_NAME" >&2
  exit 2
fi

map_name="$1"
if [[ ! "$map_name" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || [[ "$map_name" == "." || "$map_name" == ".." ]]; then
  echo "Map name must use only letters, numbers, dot, underscore, or hyphen." >&2
  exit 2
fi

script_dir="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
package_dir="$(dirname "$script_dir")"
maps_dir="$package_dir/maps"
map_base="$maps_dir/$map_name"

mkdir -p "$maps_dir"

for suffix in .yaml .pgm .posegraph .data; do
  if [[ -e "${map_base}${suffix}" ]]; then
    echo "Refusing to overwrite existing map file: ${map_base}${suffix}" >&2
    exit 1
  fi
done

if ! command -v ros2 >/dev/null 2>&1; then
  echo "ros2 is unavailable; source ROS 2 Humble and the workspace first." >&2
  exit 1
fi

save_type="$(ros2 service type /slam_toolbox/save_map 2>/dev/null || true)"
serialize_type="$(ros2 service type /slam_toolbox/serialize_map 2>/dev/null || true)"

if [[ "$save_type" != "slam_toolbox/srv/SaveMap" ]]; then
  echo "/slam_toolbox/save_map is unavailable or has unexpected type: ${save_type:-not found}" >&2
  exit 1
fi
if [[ "$serialize_type" != "slam_toolbox/srv/SerializePoseGraph" ]]; then
  echo "/slam_toolbox/serialize_map is unavailable or has unexpected type: ${serialize_type:-not found}" >&2
  exit 1
fi

echo "Saving occupancy map to ${map_base}.{yaml,pgm}"
ros2 service call \
  /slam_toolbox/save_map \
  slam_toolbox/srv/SaveMap \
  "{name: {data: '$map_base'}}"

if [[ ! -s "${map_base}.yaml" || ! -s "${map_base}.pgm" ]]; then
  echo "Occupancy map service returned without both expected output files." >&2
  exit 1
fi

echo "Saving pose graph to ${map_base}.{posegraph,data}"
ros2 service call \
  /slam_toolbox/serialize_map \
  slam_toolbox/srv/SerializePoseGraph \
  "{filename: '$map_base'}"

if [[ ! -s "${map_base}.posegraph" || ! -s "${map_base}.data" ]]; then
  echo "Pose graph service returned without both expected output files." >&2
  exit 1
fi

echo "Map and pose graph saved successfully with name: $map_name"
