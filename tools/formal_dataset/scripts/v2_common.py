#!/usr/bin/env python3
"""Shared validation and planning helpers for the auditable V2 dataset."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import random
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 2
SPLITS = ("train", "val")
PLACEMENTS = ("center", "edge", "corner")


class V2ConfigError(ValueError):
    """A V2 dataset input does not satisfy the reproducibility contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(root: Path) -> str:
    """Hash file names and contents without depending on the absolute path."""
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not files:
        raise V2ConfigError(f"asset directory contains no files: {root}")
    for path in files:
        relative = path.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise V2ConfigError(f"cannot read JSON {path}: {error}") from error


def _object(value: Any, required: Sequence[str], where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise V2ConfigError(f"{where} must be an object")
    missing = set(required) - set(value)
    if missing:
        raise V2ConfigError(f"{where} is missing keys: {sorted(missing)}")
    return value


def _number(value: Any, where: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise V2ConfigError(f"{where} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise V2ConfigError(f"{where} must be finite")
    if minimum is not None and result < minimum:
        raise V2ConfigError(f"{where} must be >= {minimum}")
    return result


def _integer(value: Any, where: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise V2ConfigError(f"{where} must be an integer >= {minimum}")
    return value


def _range(value: Any, where: str, *, minimum: float | None = None) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise V2ConfigError(f"{where} must be a two-number list")
    low = _number(value[0], f"{where}[0]", minimum=minimum)
    high = _number(value[1], f"{where}[1]", minimum=minimum)
    if low > high:
        raise V2ConfigError(f"{where} must be ascending")
    return low, high


def validate_weights(
    value: Any,
    allowed: set[str],
    where: str,
) -> dict[str, float]:
    if not isinstance(value, dict) or not value:
        raise V2ConfigError(f"{where} must be a non-empty object")
    unknown = set(value) - allowed
    if unknown:
        raise V2ConfigError(f"{where} contains unknown keys: {sorted(unknown)}")
    result = {
        str(key): _number(weight, f"{where}.{key}", minimum=0.0)
        for key, weight in value.items()
    }
    if sum(result.values()) <= 0.0:
        raise V2ConfigError(f"{where} weights must have a positive sum")
    return result


def quota_counts(total: int, weights: Mapping[str, float]) -> dict[str, int]:
    """Turn relative weights into deterministic exact integer quotas."""
    if total < 0 or not weights or sum(weights.values()) <= 0:
        raise V2ConfigError("invalid quota input")
    weight_sum = float(sum(weights.values()))
    ideals = {key: total * float(value) / weight_sum for key, value in weights.items()}
    counts = {key: int(math.floor(value)) for key, value in ideals.items()}
    remainder = total - sum(counts.values())
    order = sorted(weights, key=lambda key: (-(ideals[key] - counts[key]), key))
    for key in order[:remainder]:
        counts[key] += 1
    return counts


def quota_sequence(
    total: int,
    weights: Mapping[str, float],
    rng: random.Random,
) -> list[str]:
    values = [key for key, count in quota_counts(total, weights).items() for _ in range(count)]
    rng.shuffle(values)
    return values


def load_v2_config(path: Path, class_names: Sequence[str]) -> dict[str, Any]:
    document = _object(
        load_json(path),
        (
            "schema_version", "seed", "image", "world", "asset_contract",
            "distance_bands_m", "backgrounds", "placement", "lighting_profiles",
            "split_policy", "negative_samples", "class_policies",
            "beer_visual_check",
        ),
        "V2 config",
    )
    if document["schema_version"] != SCHEMA_VERSION:
        raise V2ConfigError("unsupported V2 config schema_version")
    _integer(document["seed"], "seed")

    image = _object(document["image"], ("width", "height", "horizontal_fov_rad"), "image")
    if image != {"width": 640, "height": 480, "horizontal_fov_rad": 1.2217304764}:
        raise V2ConfigError("image settings must match the fixed V2 sensors")

    world = _object(
        document["world"],
        (
            "table_top_z_m", "target_z_m", "camera_height_m", "camera_bearing_deg",
            "camera_yaw_jitter_deg", "camera_pitch_jitter_deg",
            "minimum_bbox_area_px", "minimum_object_spacing_m",
        ),
        "world",
    )
    for key in ("table_top_z_m", "target_z_m"):
        _number(world[key], f"world.{key}")
    for key in (
        "camera_height_m", "camera_bearing_deg", "camera_yaw_jitter_deg",
        "camera_pitch_jitter_deg",
    ):
        _range(world[key], f"world.{key}")
    _number(world["minimum_bbox_area_px"], "world.minimum_bbox_area_px", minimum=1.0)
    _number(world["minimum_object_spacing_m"], "world.minimum_object_spacing_m", minimum=0.01)

    asset = _object(
        document["asset_contract"],
        ("provenance_filename", "beer"),
        "asset_contract",
    )
    if not isinstance(asset["provenance_filename"], str) or not asset["provenance_filename"]:
        raise V2ConfigError("asset_contract.provenance_filename must be non-empty")
    beer = _object(
        asset["beer"],
        ("model_sdf_sha256", "texture_sha256", "required_sdf_tokens"),
        "asset_contract.beer",
    )
    for key in ("model_sdf_sha256", "texture_sha256"):
        value = beer[key]
        if not isinstance(value, str) or len(value) != 64:
            raise V2ConfigError(f"asset_contract.beer.{key} must be SHA256")
    if not isinstance(beer["required_sdf_tokens"], list) or not all(
        isinstance(token, str) and token for token in beer["required_sdf_tokens"]
    ):
        raise V2ConfigError("asset_contract.beer.required_sdf_tokens is invalid")

    bands = document["distance_bands_m"]
    if not isinstance(bands, dict) or set(bands) != {"near", "mid", "far"}:
        raise V2ConfigError("distance_bands_m must define near, mid, and far")
    for key, value in bands.items():
        _range(value, f"distance_bands_m.{key}", minimum=0.1)

    backgrounds = document["backgrounds"]
    if not isinstance(backgrounds, list) or len(backgrounds) < 2:
        raise V2ConfigError("backgrounds must contain at least two variants")
    background_ids = set()
    for index, background in enumerate(backgrounds):
        background = _object(background, ("id", "world_origin_xy_m", "weight"), f"backgrounds[{index}]")
        background_id = background["id"]
        if not isinstance(background_id, str) or not background_id or background_id in background_ids:
            raise V2ConfigError(f"invalid or duplicate background id: {background_id}")
        background_ids.add(background_id)
        if not isinstance(background["world_origin_xy_m"], list) or len(background["world_origin_xy_m"]) != 2:
            raise V2ConfigError(f"backgrounds[{index}].world_origin_xy_m is invalid")
        for component in background["world_origin_xy_m"]:
            _number(component, f"backgrounds[{index}].world_origin_xy_m")
        _number(background["weight"], f"backgrounds[{index}].weight", minimum=0.0)

    placement = _object(
        document["placement"],
        ("table_size_xy_m", "object_inset_m", "center_fraction", "edge_band_m"),
        "placement",
    )
    if not isinstance(placement["table_size_xy_m"], list) or len(placement["table_size_xy_m"]) != 2:
        raise V2ConfigError("placement.table_size_xy_m is invalid")
    for value in placement["table_size_xy_m"]:
        _number(value, "placement.table_size_xy_m", minimum=0.1)
    _number(placement["object_inset_m"], "placement.object_inset_m", minimum=0.01)
    center_fraction = _number(placement["center_fraction"], "placement.center_fraction", minimum=0.01)
    if center_fraction >= 1.0:
        raise V2ConfigError("placement.center_fraction must be < 1")
    _number(placement["edge_band_m"], "placement.edge_band_m", minimum=0.0)

    profiles = document["lighting_profiles"]
    if not isinstance(profiles, list) or len(profiles) < 3:
        raise V2ConfigError("lighting_profiles must contain at least three profiles")
    profile_ids = set()
    for index, profile in enumerate(profiles):
        profile = _object(
            profile,
            (
                "id", "weight", "main_rgb", "main_intensity", "direction_xyz",
                "ambient_fill_rgb", "ambient_fill_intensity",
            ),
            f"lighting_profiles[{index}]",
        )
        profile_id = profile["id"]
        if not isinstance(profile_id, str) or not profile_id or profile_id in profile_ids:
            raise V2ConfigError(f"invalid or duplicate lighting profile: {profile_id}")
        profile_ids.add(profile_id)
        _number(profile["weight"], f"lighting_profiles[{index}].weight", minimum=0.0)
        for field in ("main_rgb", "direction_xyz", "ambient_fill_rgb"):
            value = profile[field]
            if not isinstance(value, list) or len(value) != 3:
                raise V2ConfigError(f"lighting_profiles[{index}].{field} is invalid")
            for component in value:
                _number(component, f"lighting_profiles[{index}].{field}")
        _range(profile["main_intensity"], f"lighting_profiles[{index}].main_intensity", minimum=0.0)
        _range(
            profile["ambient_fill_intensity"],
            f"lighting_profiles[{index}].ambient_fill_intensity",
            minimum=0.0,
        )

    split_policy = document["split_policy"]
    if not isinstance(split_policy, dict) or set(split_policy) != set(SPLITS):
        raise V2ConfigError("split_policy must define train and val")
    for split in SPLITS:
        policy = _object(split_policy[split], ("yaw_offset_deg", "seed_offset"), f"split_policy.{split}")
        _number(policy["yaw_offset_deg"], f"split_policy.{split}.yaw_offset_deg")
        _integer(policy["seed_offset"], f"split_policy.{split}.seed_offset")

    negatives = document["negative_samples"]
    if not isinstance(negatives, dict) or set(negatives) != set(SPLITS):
        raise V2ConfigError("negative_samples must define train and val")
    for split in SPLITS:
        _integer(negatives[split], f"negative_samples.{split}")

    policies = document["class_policies"]
    if not isinstance(policies, dict) or not policies:
        raise V2ConfigError("class_policies must be non-empty")
    unknown_classes = set(policies) - set(class_names)
    if unknown_classes:
        raise V2ConfigError(f"unknown class policies: {sorted(unknown_classes)}")
    for name, policy in policies.items():
        policy = _object(
            policy,
            (
                "samples", "distance_weights", "yaw_weights", "yaw_jitter_deg",
                "placement_weights", "background_weights", "lighting_weights",
                "secondary_object_probability",
            ),
            f"class_policies.{name}",
        )
        if not isinstance(policy["samples"], dict) or set(policy["samples"]) != set(SPLITS):
            raise V2ConfigError(f"class_policies.{name}.samples must define train and val")
        for split in SPLITS:
            _integer(policy["samples"][split], f"class_policies.{name}.samples.{split}")
        validate_weights(policy["distance_weights"], set(bands), f"class_policies.{name}.distance_weights")
        yaw_weights = validate_weights(
            policy["yaw_weights"],
            {str(value) for value in range(0, 360)},
            f"class_policies.{name}.yaw_weights",
        )
        for key in yaw_weights:
            yaw = _number(float(key), f"class_policies.{name}.yaw_weights.{key}")
            if not 0.0 <= yaw < 360.0:
                raise V2ConfigError(f"class_policies.{name} yaw must be in [0, 360)")
        _number(policy["yaw_jitter_deg"], f"class_policies.{name}.yaw_jitter_deg", minimum=0.0)
        validate_weights(policy["placement_weights"], set(PLACEMENTS), f"class_policies.{name}.placement_weights")
        validate_weights(policy["background_weights"], background_ids, f"class_policies.{name}.background_weights")
        validate_weights(policy["lighting_weights"], profile_ids, f"class_policies.{name}.lighting_weights")
        secondary = _number(
            policy["secondary_object_probability"],
            f"class_policies.{name}.secondary_object_probability",
            minimum=0.0,
        )
        if secondary > 1.0:
            raise V2ConfigError(f"class_policies.{name}.secondary_object_probability must be <= 1")

    visual = _object(
        document["beer_visual_check"],
        ("near_black_channel_threshold", "max_near_black_fraction"),
        "beer_visual_check",
    )
    threshold = _integer(visual["near_black_channel_threshold"], "beer_visual_check.near_black_channel_threshold")
    if threshold > 255:
        raise V2ConfigError("beer_visual_check.near_black_channel_threshold must be <= 255")
    fraction = _number(visual["max_near_black_fraction"], "beer_visual_check.max_near_black_fraction", minimum=0.0)
    if fraction > 1.0:
        raise V2ConfigError("beer_visual_check.max_near_black_fraction must be <= 1")
    return deepcopy(dict(document))


def build_asset_manifest(models: Path, class_names: Sequence[str]) -> dict[str, Any]:
    classes = {}
    for name in class_names:
        root = models / name
        if not root.is_dir():
            raise FileNotFoundError(f"missing asset directory: {root}")
        files = {
            path.relative_to(root).as_posix(): sha256_file(path)
            for path in sorted(root.rglob("*")) if path.is_file()
        }
        classes[name] = {"tree_sha256": sha256_tree(root), "files": files}
    return {
        "schema_version": SCHEMA_VERSION,
        "asset_root": str(models.resolve()),
        "classes": classes,
    }


def validate_asset_contract(
    models: Path,
    config: Mapping[str, Any],
    class_names: Sequence[str],
) -> dict[str, Any]:
    provenance_path = models / config["asset_contract"]["provenance_filename"]
    provenance = load_json(provenance_path)
    if not isinstance(provenance, dict) or provenance.get("schema_version") != SCHEMA_VERSION:
        raise V2ConfigError(f"invalid V2 asset provenance: {provenance_path}")
    manifest = build_asset_manifest(models, class_names)
    beer = config["asset_contract"]["beer"]
    model_path = models / "beer" / "model.sdf"
    texture_path = models / "beer" / "materials" / "textures" / "beer.png"
    if sha256_file(model_path) != beer["model_sdf_sha256"]:
        raise V2ConfigError("beer model.sdf hash does not match the V2 asset contract")
    if sha256_file(texture_path) != beer["texture_sha256"]:
        raise V2ConfigError("beer texture hash does not match the V2 asset contract")
    sdf = model_path.read_text(encoding="utf-8")
    missing = [token for token in beer["required_sdf_tokens"] if token not in sdf]
    if missing:
        raise V2ConfigError(f"beer model.sdf is not the required PBR asset; missing {missing}")
    recorded = provenance.get("classes", {})
    for name in class_names:
        actual = manifest["classes"][name]["tree_sha256"]
        if recorded.get(name, {}).get("tree_sha256") != actual:
            raise V2ConfigError(f"asset provenance hash mismatch for {name}")
    manifest["provenance_file"] = str(provenance_path.resolve())
    manifest["provenance_sha256"] = sha256_file(provenance_path)
    return manifest


def _sample_placement(
    category: str,
    origin: Sequence[float],
    placement: Mapping[str, Any],
    rng: random.Random,
) -> tuple[list[float], list[float]]:
    half_x = float(placement["table_size_xy_m"][0]) / 2 - float(placement["object_inset_m"])
    half_y = float(placement["table_size_xy_m"][1]) / 2 - float(placement["object_inset_m"])
    center_fraction = float(placement["center_fraction"])
    edge_band = float(placement["edge_band_m"])

    def central(half: float) -> float:
        return rng.uniform(-half * center_fraction, half * center_fraction)

    def boundary(half: float) -> float:
        magnitude = rng.uniform(max(0.0, half - edge_band), half)
        return magnitude if rng.random() < 0.5 else -magnitude

    if category == "center":
        local = [central(half_x), central(half_y)]
    elif category == "edge":
        local = [boundary(half_x), central(half_y)] if rng.random() < 0.5 else [central(half_x), boundary(half_y)]
    elif category == "corner":
        local = [boundary(half_x), boundary(half_y)]
    else:
        raise V2ConfigError(f"unknown placement category: {category}")
    return local, [float(origin[0]) + local[0], float(origin[1]) + local[1]]


def _sample_lighting(profile: Mapping[str, Any], rng: random.Random) -> dict[str, Any]:
    direction = [float(value) for value in profile["direction_xyz"]]
    length = math.sqrt(sum(value * value for value in direction))
    if length <= 0.0:
        raise V2ConfigError(f"lighting profile {profile['id']} has zero direction")
    direction = [value / length for value in direction]
    return {
        "profile_id": profile["id"],
        "main_rgb": [float(value) for value in profile["main_rgb"]],
        "main_intensity": rng.uniform(*profile["main_intensity"]),
        "direction_xyz": direction,
        "ambient_fill_rgb": [float(value) for value in profile["ambient_fill_rgb"]],
        "ambient_fill_intensity": rng.uniform(*profile["ambient_fill_intensity"]),
    }


def build_scenario_plan(
    config: Mapping[str, Any],
    classes: Sequence[Mapping[str, Any]],
    asset_manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Build all split assignments and quotas before Gazebo starts."""
    names = [item["name"] for item in classes]
    class_ids = {name: index for index, name in enumerate(names)}
    backgrounds = {item["id"]: item for item in config["backgrounds"]}
    profiles = {item["id"]: item for item in config["lighting_profiles"]}
    records = []

    for split in SPLITS:
        split_seed = int(config["seed"]) + int(config["split_policy"][split]["seed_offset"])
        rng = random.Random(split_seed)
        split_records = []
        for class_name, policy in config["class_policies"].items():
            count = int(policy["samples"][split])
            fields = {
                "distance_band": quota_sequence(count, policy["distance_weights"], rng),
                "yaw_bin": quota_sequence(count, policy["yaw_weights"], rng),
                "placement_category": quota_sequence(count, policy["placement_weights"], rng),
                "background_id": quota_sequence(count, policy["background_weights"], rng),
                "lighting_profile": quota_sequence(count, policy["lighting_weights"], rng),
            }
            for index in range(count):
                sample_seed = rng.randrange(0, 2**32)
                sample_rng = random.Random(sample_seed)
                background = backgrounds[fields["background_id"][index]]
                category = fields["placement_category"][index]
                local_xy, world_xy = _sample_placement(
                    category, background["world_origin_xy_m"], config["placement"], sample_rng
                )
                distance_band = fields["distance_band"][index]
                distance = sample_rng.uniform(*config["distance_bands_m"][distance_band])
                yaw_bin = float(fields["yaw_bin"][index])
                yaw_deg = (
                    yaw_bin
                    + float(config["split_policy"][split]["yaw_offset_deg"])
                    + sample_rng.uniform(-float(policy["yaw_jitter_deg"]), float(policy["yaw_jitter_deg"]))
                ) % 360.0
                bearing = math.radians(sample_rng.uniform(*config["world"]["camera_bearing_deg"]))
                camera_x = world_xy[0] - distance * math.cos(bearing)
                camera_y = world_xy[1] - distance * math.sin(bearing)
                camera_z = sample_rng.uniform(*config["world"]["camera_height_m"])
                horizontal = math.hypot(world_xy[0] - camera_x, world_xy[1] - camera_y)
                camera_yaw = math.atan2(world_xy[1] - camera_y, world_xy[0] - camera_x)
                camera_yaw += math.radians(sample_rng.uniform(*config["world"]["camera_yaw_jitter_deg"]))
                camera_pitch = math.atan2(camera_z - float(config["world"]["target_z_m"]), horizontal)
                camera_pitch += math.radians(sample_rng.uniform(*config["world"]["camera_pitch_jitter_deg"]))
                profile = profiles[fields["lighting_profile"][index]]
                lighting = _sample_lighting(profile, sample_rng)
                secondary = None
                if sample_rng.random() < float(policy["secondary_object_probability"]):
                    secondary_name = sample_rng.choice([name for name in names if name != class_name])
                    for _ in range(100):
                        secondary_local, secondary_world = _sample_placement(
                            sample_rng.choice(PLACEMENTS),
                            background["world_origin_xy_m"],
                            config["placement"],
                            sample_rng,
                        )
                        if math.hypot(secondary_world[0] - world_xy[0], secondary_world[1] - world_xy[1]) >= float(config["world"]["minimum_object_spacing_m"]):
                            break
                    else:
                        raise V2ConfigError("could not place a non-overlapping secondary object")
                    secondary = {
                        "class_id": class_ids[secondary_name],
                        "class_name": secondary_name,
                        "asset_tree_sha256": asset_manifest["classes"][secondary_name]["tree_sha256"],
                        "position_local_m": secondary_local,
                        "position_world_m": [secondary_world[0], secondary_world[1], float(config["world"]["table_top_z_m"])],
                        "yaw_deg": sample_rng.uniform(0.0, 360.0),
                    }
                split_records.append({
                    "schema_version": SCHEMA_VERSION,
                    "sample_id": "",
                    "image_path": "",
                    "label_path": "",
                    "split": split,
                    "scene_group_id": f"{split}:{class_name}:{index:06d}",
                    "random_seed": sample_seed,
                    "negative": False,
                    "primary": {
                        "class_id": class_ids[class_name],
                        "class_name": class_name,
                        "asset_tree_sha256": asset_manifest["classes"][class_name]["tree_sha256"],
                        "position_local_m": local_xy,
                        "position_world_m": [world_xy[0], world_xy[1], float(config["world"]["table_top_z_m"])],
                        "yaw_bin_deg": yaw_bin,
                        "yaw_deg": yaw_deg,
                    },
                    "secondary": secondary,
                    "background": {
                        "id": background["id"],
                        "world_origin_xy_m": list(background["world_origin_xy_m"]),
                    },
                    "placement_category": category,
                    "camera": {
                        "position_world_m": [camera_x, camera_y, camera_z],
                        "rpy_rad": [0.0, camera_pitch, camera_yaw],
                        "object_distance_m": distance,
                        "distance_band": distance_band,
                    },
                    "lighting": {"seed": sample_seed, **lighting},
                    "bboxes": [],
                    "image_sha256": None,
                })

        negative_count = int(config["negative_samples"][split])
        background_weights = {item["id"]: float(item["weight"]) for item in config["backgrounds"]}
        lighting_weights = {item["id"]: float(item["weight"]) for item in config["lighting_profiles"]}
        negative_backgrounds = quota_sequence(negative_count, background_weights, rng)
        negative_lights = quota_sequence(negative_count, lighting_weights, rng)
        for index in range(negative_count):
            sample_seed = rng.randrange(0, 2**32)
            sample_rng = random.Random(sample_seed)
            background = backgrounds[negative_backgrounds[index]]
            origin = background["world_origin_xy_m"]
            distance = sample_rng.uniform(*config["distance_bands_m"][sample_rng.choice(("mid", "far"))])
            bearing = math.radians(sample_rng.uniform(*config["world"]["camera_bearing_deg"]))
            camera_z = sample_rng.uniform(*config["world"]["camera_height_m"])
            camera_x = float(origin[0]) - distance * math.cos(bearing)
            camera_y = float(origin[1]) - distance * math.sin(bearing)
            camera_yaw = math.atan2(float(origin[1]) - camera_y, float(origin[0]) - camera_x)
            camera_pitch = math.atan2(camera_z - float(config["world"]["target_z_m"]), distance)
            lighting = _sample_lighting(profiles[negative_lights[index]], sample_rng)
            split_records.append({
                "schema_version": SCHEMA_VERSION,
                "sample_id": "",
                "image_path": "",
                "label_path": "",
                "split": split,
                "scene_group_id": f"{split}:negative:{index:06d}",
                "random_seed": sample_seed,
                "negative": True,
                "primary": None,
                "secondary": None,
                "background": {"id": background["id"], "world_origin_xy_m": list(origin)},
                "placement_category": "background_only",
                "camera": {
                    "position_world_m": [camera_x, camera_y, camera_z],
                    "rpy_rad": [0.0, camera_pitch, camera_yaw],
                    "object_distance_m": distance,
                    "distance_band": "background_only",
                },
                "lighting": {"seed": sample_seed, **lighting},
                "bboxes": [],
                "image_sha256": None,
            })

        rng.shuffle(split_records)
        for index, record in enumerate(split_records):
            sample_id = f"{split}_{index:06d}"
            record["sample_id"] = sample_id
            record["image_path"] = f"images/{split}/{sample_id}.png"
            record["label_path"] = f"labels/{split}/{sample_id}.txt"
        records.extend(split_records)
    return records


def policy_expected_counts(config: Mapping[str, Any], class_name: str, split: str) -> dict[str, Counter]:
    policy = config["class_policies"][class_name]
    total = int(policy["samples"][split])
    return {
        "distance_band": Counter(quota_counts(total, policy["distance_weights"])),
        "yaw_bin": Counter(quota_counts(total, policy["yaw_weights"])),
        "placement_category": Counter(quota_counts(total, policy["placement_weights"])),
        "background_id": Counter(quota_counts(total, policy["background_weights"])),
        "lighting_profile": Counter(quota_counts(total, policy["lighting_weights"])),
    }
