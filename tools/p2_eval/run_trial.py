#!/usr/bin/env python3
"""Generate, run, score, and summarize one frozen-baseline P2 trial."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence

from p2_eval_core import EvaluationConfigError, generate_trial


MATCH_THRESHOLD_M = 0.10
VISION_TELEMETRY_MARKER = "VISION_TELEMETRY "
RUNTIME_INPUT_KEYS = {
    "world_file",
    "world_name",
    "target_1",
    "target_2",
    "target_3",
    "group_number",
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_runtime_command(
    runtime_inputs: Mapping[str, Any],
    answer_output_dir: Path,
    model_path: Path,
    device: str,
    max_runtime_seconds: float,
    setup_files: Sequence[Path],
    evaluation_overrides: Mapping[str, str] | None = None,
) -> list[str]:
    """
    Build the only process boundary into the formal competition runtime.

    Deliberately accepts only judge-equivalent inputs. Ground truth, scenario
    metadata, table geometry, and object coordinates cannot cross this API.
    """
    if set(runtime_inputs) != RUNTIME_INPUT_KEYS:
        raise EvaluationConfigError(
            f"runtime inputs must be exactly {sorted(RUNTIME_INPUT_KEYS)}"
        )
    for setup in setup_files:
        if not setup.is_file():
            raise EvaluationConfigError(f"missing environment setup: {setup}")
    if not model_path.is_file() or model_path.suffix != ".pt":
        raise EvaluationConfigError(f"missing formal YOLO model: {model_path}")
    if not device:
        raise EvaluationConfigError("device must not be empty")
    if not math.isfinite(max_runtime_seconds) or max_runtime_seconds <= 0.0:
        raise EvaluationConfigError("max_runtime_seconds must be positive and finite")
    evaluation_overrides = dict(evaluation_overrides or {})
    if set(evaluation_overrides) - {
        "runner_executable",
        "observation_plan_json",
    }:
        raise EvaluationConfigError("unsupported P2 runtime evaluation override")
    if evaluation_overrides and evaluation_overrides.get(
        "runner_executable"
    ) != "p2_viewpoint_task_runner":
        raise EvaluationConfigError("P2 runner override must use the evaluation runner")
    if bool(evaluation_overrides.get("observation_plan_json")) != bool(
        evaluation_overrides
    ):
        raise EvaluationConfigError(
            "P2 evaluation runner and observation plan must be supplied together"
        )

    launch_values = [
        "ros2",
        "launch",
        "robocup_home_robot",
        "formal_base_task.launch.py",
        f"world_file:={runtime_inputs['world_file']}",
        f"world_name:={runtime_inputs['world_name']}",
        f"target_1:={runtime_inputs['target_1']}",
        f"target_2:={runtime_inputs['target_2']}",
        f"target_3:={runtime_inputs['target_3']}",
        f"group_number:={runtime_inputs['group_number']}",
        f"model_path:={model_path.resolve()}",
        f"answer_output_dir:={answer_output_dir.resolve()}",
        f"device:={device}",
        f"max_runtime_seconds:={max_runtime_seconds}",
    ]
    launch_values.extend(
        f"{name}:={value}" for name, value in evaluation_overrides.items()
    )
    shell_parts = [f"source {shlex.quote(str(path))}" for path in setup_files]
    shell_parts.append("exec " + " ".join(shlex.quote(value) for value in launch_values))
    return ["bash", "-lc", " && ".join(shell_parts)]


def build_scorer_command(
    scorer_path: Path,
    submission_directory: Path,
    ground_truth_path: Path,
    scores_path: Path,
    details_path: Path,
) -> list[str]:
    if not scorer_path.is_file():
        raise EvaluationConfigError(f"official scorer does not exist: {scorer_path}")
    return [
        sys.executable,
        str(scorer_path.resolve()),
        str(submission_directory.resolve()),
        str(ground_truth_path.resolve()),
        "--match-threshold",
        f"{MATCH_THRESHOLD_M:.2f}",
        "--scores-output",
        str(scores_path.resolve()),
        "--details-output",
        str(details_path.resolve()),
    ]


def run_logged(
    command: Sequence[str],
    log_path: Path,
    timeout_seconds: float,
) -> tuple[int, float, bool]:
    start = time.monotonic()
    timed_out = False
    with log_path.open("w", encoding="utf-8") as log:
        log.write("COMMAND: " + shlex.join(command) + "\n\n")
        log.flush()
        process = subprocess.Popen(
            list(command),
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            return_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGINT)
            try:
                return_code = process.wait(timeout=15.0)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                return_code = process.wait(timeout=10.0)
            log.write(
                f"\nEVALUATION HARNESS TIMEOUT after "
                f"{timeout_seconds:.1f}s\n"
            )
    return return_code, time.monotonic() - start, timed_out


def _stage_from_log(log: str, timed_out: bool) -> tuple[str, str | None]:
    if timed_out or "Formal task timeout" in log:
        return "timeout", "formal runtime exceeded its configured time limit"
    if "Formal base task succeeded:" in log:
        return "success", None
    if "Living room navigation failed." in log:
        return "navigation", "navigation did not report success"
    if re.search(r"(?:Observation point \d+/\d+ scan|Scan step \d+/\d+) failed", log):
        return "scan", "living-room scan did not complete"
    if (
        "Timed out waiting for transform from base_link to map" in log
        or 'Invalid frame ID "map"' in log
    ):
        return (
            "nav2_map_tf",
            "Nav2 could not obtain the map-to-base_link transform",
        )
    checks = [
        ("Gazebo world is ready", "world_load", "Gazebo world did not become ready"),
        (
            "Robot interfaces are ready",
            "robot_spawn",
            "robot spawn/readiness did not complete",
        ),
        (
            "Nav2 lifecycle stack is active",
            "nav2_ready",
            "Nav2 did not become active",
        ),
        (
            "Living room navigation succeeded",
            "navigation",
            "navigation did not report success",
        ),
        (
            "Reset visual tracking",
            "vision_reset",
            "visual tracking reset did not complete",
        ),
        ("Living room scan completed", "scan", "scan did not complete"),
        ("Answer JSON:", "save_answer", "answer was not saved and verified"),
    ]
    for marker, stage, reason in checks:
        if marker not in log:
            return stage, reason
    return "startup", "formal runtime exited without a recognized success marker"


def _class_seen(log: str, class_name: str) -> bool:
    return bool(
        re.search(
            rf"(?m)^\[[^\n]+\]\s+{re.escape(class_name)}: conf=",
            log,
        )
    )


def _cluster_seen(log: str, class_name: str) -> bool:
    return bool(
        re.search(
            rf"(?m)^\[[^\n]+\]\s+{re.escape(class_name)}:\s*$",
            log,
        )
    )


def _observation_window(log: str) -> str:
    """Return only evidence collected after the formal tracking reset."""
    marker = "Reset visual tracking;"
    start = log.rfind(marker)
    return log[start:] if start >= 0 else ""


def _vision_telemetry(log: str) -> Mapping[str, Any] | None:
    """Return the final post-reset, observational telemetry record."""
    records = []
    for line in _observation_window(log).splitlines():
        if VISION_TELEMETRY_MARKER not in line:
            continue
        payload = line.split(VISION_TELEMETRY_MARKER, 1)[1].strip()
        try:
            record = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records[-1] if records else None


def _pipeline_state(
    telemetry: Mapping[str, Any] | None,
    class_name: str,
    final_answer_count: int,
    vision_evaluated: bool = True,
) -> dict[str, Any]:
    """Convert exact stage counters into one class-level offline diagnosis."""
    if telemetry is None:
        status = "unknown" if vision_evaluated else "not_evaluated"
        return {
            "telemetry_available": False,
            "inference_frames": None,
            "detection_status": status,
            "depth_status": status,
            "tf_status": status,
            "cluster_status": status,
            "final_answer_status": (
                "present" if final_answer_count else "absent"
            ),
        }
    raw = telemetry.get("classes", {}).get(class_name, {})
    detections = int(raw.get("detection_count", 0))
    depth_valid = int(raw.get("depth_valid_count", 0))
    depth_invalid = int(raw.get("depth_invalid_count", 0))
    tf_success = int(raw.get("tf_success_count", 0))
    tf_failure = int(raw.get("tf_failure_count", 0))
    clusters = raw.get("clusters", [])
    cluster_observations = [
        int(cluster.get("observations", 0))
        for cluster in clusters
        if isinstance(cluster, dict)
    ]
    return {
        "telemetry_available": True,
        "inference_frames": int(telemetry.get("inference_frames", 0)),
        "detection_status": "detected" if detections else "not_detected",
        "detection_count": detections,
        "depth_status": (
            "valid" if depth_valid else
            "invalid" if detections else
            "not_reached"
        ),
        "depth_valid_count": depth_valid,
        "depth_invalid_count": depth_invalid,
        "tf_status": (
            "success" if tf_success else
            "failed" if depth_valid else
            "not_reached"
        ),
        "tf_success_count": tf_success,
        "tf_failure_count": tf_failure,
        "cluster_status": "formed" if clusters else "not_formed",
        "cluster_count": len(clusters),
        "confirmed_cluster_count": sum(
            bool(cluster.get("confirmed"))
            for cluster in clusters
            if isinstance(cluster, dict)
        ),
        "maximum_cluster_observations": (
            max(cluster_observations) if cluster_observations else 0
        ),
        "clusters": clusters,
        "final_answer_status": (
            "present" if final_answer_count else "absent"
        ),
        "final_answer_count": final_answer_count,
    }


def summarize_trial(
    metadata: Mapping[str, Any],
    answer_path: Path,
    scorer_details_path: Path,
    runtime_log_path: Path,
    scorer_log_path: Path,
    runtime_return_code: int,
    runtime_seconds: float,
    total_seconds: float,
    timed_out: bool,
) -> dict[str, Any]:
    log = runtime_log_path.read_text(encoding="utf-8", errors="replace")
    observation_log = _observation_window(log)
    telemetry = _vision_telemetry(log)
    failure_stage, failure_reason = _stage_from_log(log, timed_out)
    answer = _read_json(answer_path) if answer_path.is_file() else None
    details = (
        _read_json(scorer_details_path)
        if scorer_details_path.is_file()
        else None
    )
    group_report = None
    if (
        isinstance(details, dict)
        and isinstance(details.get("groups"), list)
        and details["groups"]
    ):
        group_report = details["groups"][0]

    navigation_success = "Living room navigation succeeded" in log
    scan_success = "Living room scan completed" in log
    reset_success = "Reset visual tracking" in log
    score_by_class = (
        group_report.get("classes", {})
        if isinstance(group_report, dict)
        else {}
    )
    submitted_objects = (
        answer.get("objects", {}) if isinstance(answer, dict) else {}
    )
    object_results = []
    for truth_index_global, truth in enumerate(metadata["objects"]):
        class_name = truth["class_name"]
        class_truths = [
            item
            for item in metadata["objects"]
            if item["class_name"] == class_name
        ]
        class_truth_index = class_truths.index(truth)
        class_report = score_by_class.get(class_name, {})
        match = next(
            (
                item for item in class_report.get("matches", [])
                if item.get("ground_truth_index") == class_truth_index
            ),
            None,
        )
        class_submitted = submitted_objects.get(class_name, [])
        pipeline = _pipeline_state(
            telemetry,
            class_name,
            len(class_submitted),
            scan_success,
        )
        telemetry_available = pipeline["telemetry_available"]
        localization_pipeline_success = (
            pipeline.get("tf_success_count", 0) > 0
            if telemetry_available
            else _class_seen(observation_log, class_name)
        )
        object_results.append(
            {
                "ground_truth_index": truth_index_global,
                "instance_name": truth["instance_name"],
                "class_name": class_name,
                "table_id": truth["table_id"],
                "table_local_position_m": truth["table_local_position_m"],
                "ground_truth_world_m": truth["world_position_m"],
                "scan_stand_distance_m": truth["scan_stand_distance_m"],
                "detection_success": (
                    pipeline.get("detection_count", 0) > 0
                    if telemetry_available else
                    (True if localization_pipeline_success else None)
                ),
                "depth_valid": (
                    pipeline.get("depth_valid_count", 0) > 0
                    if telemetry_available else
                    (True if localization_pipeline_success else None)
                ),
                "tf_success": (
                    pipeline.get("tf_success_count", 0) > 0
                    if telemetry_available else
                    (True if localization_pipeline_success else None)
                ),
                "localization_pipeline_success": (
                    localization_pipeline_success
                ),
                "cluster_formed": (
                    pipeline.get("cluster_count", 0) > 0
                    if telemetry_available else
                    (_cluster_seen(observation_log, class_name)
                     or bool(class_submitted))
                ),
                "entered_final_answer": (
                    bool(match)
                    or (len(class_truths) == 1 and bool(class_submitted))
                ),
                "true_positive": match is not None,
                "localization_error_m": (
                    match.get("distance_m") if match else None
                ),
                "pipeline_telemetry": pipeline,
                "evidence_scope_note": (
                    "Structured counters separate detection, depth, and TF "
                    "when telemetry is available. Cluster evidence is "
                    "class-level; TP/error remain scorer one-to-one evidence."
                    if telemetry_available else
                    "Without structured telemetry, a missing localization "
                    "cannot be separated into detector, depth, or TF failure."
                ),
            }
        )

    classes = {}
    total_tp = total_fp = total_fn = 0
    for class_name in metadata["targets"]:
        report = score_by_class.get(class_name, {})
        truth_count = sum(
            item["class_name"] == class_name
            for item in metadata["objects"]
        )
        entry = {
            "ground_truth_count": report.get("ground_truth_count", truth_count),
            "submitted_count": report.get(
                "submitted_count",
                len(submitted_objects.get(class_name, [])),
            ),
            "TP": report.get("true_positive", 0),
            "FP": report.get(
                "false_positive",
                len(submitted_objects.get(class_name, [])),
            ),
            "FN": report.get("false_negative", truth_count),
            "score": report.get("score", 0.0),
            "matches": report.get("matches", []),
            "pipeline_telemetry": _pipeline_state(
                telemetry,
                class_name,
                len(submitted_objects.get(class_name, [])),
                scan_success,
            ),
        }
        total_tp += entry["TP"]
        total_fp += entry["FP"]
        total_fn += entry["FN"]
        classes[class_name] = entry

    errors = [
        item["localization_error_m"]
        for item in object_results
        if item["localization_error_m"] is not None
    ]
    vision_score = (
        float(group_report.get("score", 0.0))
        if isinstance(group_report, dict)
        else 0.0
    )
    scorer_valid = (
        bool(group_report.get("valid"))
        if isinstance(group_report, dict)
        else False
    )
    if failure_stage == "success" and not scorer_valid:
        failure_stage = "scorer"
        failure_reason = (
            group_report.get(
                "error",
                "official scorer did not produce a valid result",
            )
            if isinstance(group_report, dict)
            else "official scorer output is missing"
        )
    collision_keyword = bool(
        re.search(r"(?i)\b(collision detected|contact detected|crash)\b", log)
    )
    return {
        "schema_version": 1,
        "trial_id": metadata["trial_id"],
        "seed": metadata["seed"],
        "scenario_world": metadata["generated_world"],
        "targets": metadata["targets"],
        "group_number": metadata["group_number"],
        "ground_truth_count": len(metadata["objects"]),
        "TP": total_tp,
        "FP": total_fp,
        "FN": total_fn,
        "classes": classes,
        "objects": object_results,
        "maximum_localization_error_m": max(errors) if errors else None,
        "navigation_success": navigation_success,
        "vision_reset_success": reset_success,
        "scan_completed": scan_success,
        "collision_observed_in_runtime_log": collision_keyword,
        "collision_observation_limit": (
            "No contact sensor is wired into the frozen runtime; false means "
            "no explicit collision/contact failure appeared in its log."
        ),
        "runtime_return_code": runtime_return_code,
        "runtime_wall_seconds": runtime_seconds,
        "total_wall_seconds": total_seconds,
        "match_threshold_m": MATCH_THRESHOLD_M,
        "vision_telemetry": telemetry,
        "vision_score": vision_score,
        "navigation_score": 40.0 if navigation_success else 0.0,
        "base_task_score": vision_score + (40.0 if navigation_success else 0.0),
        "failure_stage": failure_stage,
        "failure_reason": failure_reason,
        "artifacts": {
            "scenario_world": str(
                (runtime_log_path.parent / "scenario.world").resolve()
            ),
            "ground_truth": str(
                (runtime_log_path.parent / "ground_truth.json").resolve()
            ),
            "answer_json": str(answer_path.resolve()),
            "runtime_log": str(runtime_log_path.resolve()),
            "scorer_output": str(scorer_log_path.resolve()),
            "scorer_details": str(scorer_details_path.resolve()),
            "scores_csv": str(
                (runtime_log_path.parent / "scores.csv").resolve()
            ),
            "scenario_metadata": str(
                (runtime_log_path.parent / "scenario_metadata.json").resolve()
            ),
            "isolation_audit": str(
                (runtime_log_path.parent / "isolation_audit.json").resolve()
            ),
        },
    }


def main(argv=None) -> int:
    package_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-world",
        type=Path,
        default=Path(
            "/home/hao/wpr_ros2_ws/src/wpr_simulation_ros2/worlds/example.world"
        ),
    )
    parser.add_argument(
        "--table-config",
        type=Path,
        default=package_root / "tools/p2_eval/tables.json",
    )
    parser.add_argument(
        "--scenario",
        type=Path,
        default=package_root
        / "tools/p2_eval/scenarios/smoke_multitable.json",
    )
    parser.add_argument(
        "--class-manifest",
        type=Path,
        default=package_root / "tools/formal_dataset/classes.json",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=Path(
            "/home/hao/robocup_assets/training_runs/"
            "formal_objects_v1_yolo11n/weights/best.pt"
        ),
    )
    parser.add_argument(
        "--scorer",
        type=Path,
        default=Path("/home/hao/robocup_assets/scoring/score_submission.py"),
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--max-runtime-seconds", type=float, default=450.0)
    parser.add_argument("--harness-timeout-seconds", type=float, default=480.0)
    args = parser.parse_args(argv)
    started = time.monotonic()
    try:
        paths = generate_trial(
            args.base_world,
            args.table_config,
            args.scenario,
            args.class_manifest,
            args.output_dir,
        )
        answer_dir = args.output_dir / "submission"
        answer_dir.mkdir()
        runtime_inputs = _read_json(paths["runtime_inputs"])
        setup_files = [
            Path("/opt/ros/humble/setup.bash"),
            Path("/home/hao/franka_ros2_ws/install/setup.bash"),
            Path("/home/hao/robocup_vision_venv/bin/activate"),
            Path("/home/hao/wpr_ros2_ws/install/setup.bash"),
        ]
        runtime_command = build_runtime_command(
            runtime_inputs,
            answer_dir,
            args.model,
            args.device,
            args.max_runtime_seconds,
            setup_files,
        )
        audit = {
            "runtime_boundary": (
                "formal runtime receives only world path/name, three target "
                "strings, group number, model/device, output directory, "
                "and timeout"
            ),
            "forbidden_inputs_not_passed": [
                "ground_truth",
                "scenario_metadata",
                "table_config",
                "object_coordinates",
            ],
            "runtime_command": shlex.join(runtime_command),
            "scoring_starts_only_after_runtime_exit": True,
        }
        (args.output_dir / "isolation_audit.json").write_text(
            json.dumps(audit, indent=2) + "\n",
            encoding="utf-8",
        )

        runtime_log = args.output_dir / "runtime.log"
        runtime_code, runtime_seconds, timed_out = run_logged(
            runtime_command,
            runtime_log,
            args.harness_timeout_seconds,
        )
        answer_path = answer_dir / f"{runtime_inputs['group_number']}_answer.json"
        scores_path = args.output_dir / "scores.csv"
        details_path = args.output_dir / "scorer_details.json"
        scorer_log = args.output_dir / "scorer_output.txt"
        scorer_command = build_scorer_command(
            args.scorer,
            answer_dir,
            paths["ground_truth"],
            scores_path,
            details_path,
        )
        scorer_code = 1
        if answer_path.is_file():
            scorer_code, _scorer_seconds, _ = run_logged(
                scorer_command,
                scorer_log,
                60.0,
            )
        else:
            scorer_log.write_text(
                "scorer not run: formal runtime did not create an answer JSON\n",
                encoding="utf-8",
            )

        metadata = _read_json(paths["metadata"])
        summary = summarize_trial(
            metadata,
            answer_path,
            details_path,
            runtime_log,
            scorer_log,
            runtime_code,
            runtime_seconds,
            time.monotonic() - started,
            timed_out,
        )
        summary["scorer_return_code"] = scorer_code
        summary["scorer_command"] = shlex.join(scorer_command)
        summary_path = args.output_dir / "summary.json"
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2))
        return 0 if summary["failure_stage"] == "success" else 1
    except (EvaluationConfigError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"P2 trial failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
