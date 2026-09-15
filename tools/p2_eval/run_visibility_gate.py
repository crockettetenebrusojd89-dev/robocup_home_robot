#!/usr/bin/env python3
"""Run 2-3 immutable trials with read-only visibility capture and analysis."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence

from analyze_visibility import analyze_capture
from p2_eval_core import EvaluationConfigError
from run_repeatability import input_hashes
from run_trial import _read_json
from run_trial import build_runtime_command
from run_trial import build_scorer_command
from run_trial import run_logged
from run_trial import summarize_trial


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _capture_command(
    capture_script: Path,
    capture_dir: Path,
    setup_files: Sequence[Path],
    capture_hz: float,
    stop_file: Path,
) -> list[str]:
    shell_parts = [f"source {shlex.quote(str(path))}" for path in setup_files]
    command = [
        sys.executable,
        str(capture_script.resolve()),
        "--output-dir",
        str(capture_dir.resolve()),
        "--capture-hz",
        str(capture_hz),
        "--stop-file",
        str(stop_file.resolve()),
    ]
    shell_parts.append("exec " + shlex.join(command))
    return ["bash", "-lc", " && ".join(shell_parts)]


def _start_capture(
    command: Sequence[str], log_path: Path, ready_path: Path, timeout: float
):
    log = log_path.open("w", encoding="utf-8")
    log.write("COMMAND: " + shlex.join(command) + "\n\n")
    log.flush()
    process = subprocess.Popen(
        list(command),
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ready_path.is_file():
            return process, log
        code = process.poll()
        if code is not None:
            log.close()
            raise EvaluationConfigError(
                f"read-only capture exited before readiness with code {code}"
            )
        time.sleep(0.05)
    os.killpg(process.pid, signal.SIGINT)
    process.wait(timeout=10.0)
    log.close()
    raise EvaluationConfigError("read-only capture did not report readiness")


def _stop_capture(process, log, stop_file: Path) -> int:
    if process.poll() is None:
        stop_file.write_text("stop\n", encoding="utf-8")
        try:
            code = process.wait(timeout=20.0)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGINT)
            try:
                code = process.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                code = process.wait(timeout=10.0)
    else:
        code = int(process.returncode)
    log.write(f"\nCAPTURE RETURN CODE: {code}\n")
    log.close()
    return code


def run_one(
    run_index: int,
    source_trial_dir: Path,
    output_dir: Path,
    runtime_inputs: Mapping[str, Any],
    model_path: Path,
    scorer_path: Path,
    device: str,
    max_runtime_seconds: float,
    harness_timeout_seconds: float,
    setup_files: Sequence[Path],
    expected_hashes: Mapping[str, str],
    capture_hz: float,
    confidence_floor: float,
) -> dict[str, Any]:
    run_id = f"run_{run_index:02d}"
    run_dir = output_dir / run_id
    run_dir.mkdir()
    answer_dir = run_dir / "submission"
    answer_dir.mkdir()
    capture_dir = run_dir / "capture"
    capture_stop_file = run_dir / "capture.stop"
    capture_script = Path(__file__).with_name("capture_visibility.py")
    before_hashes = input_hashes(source_trial_dir, model_path)
    if before_hashes != expected_hashes:
        raise EvaluationConfigError(f"{run_id}: immutable inputs changed")

    runtime_command = build_runtime_command(
        runtime_inputs,
        answer_dir,
        model_path,
        device,
        max_runtime_seconds,
        setup_files,
    )
    capture_command = _capture_command(
        capture_script,
        capture_dir,
        setup_files,
        capture_hz,
        capture_stop_file,
    )
    audit = {
        "schema_version": 1,
        "run_id": run_id,
        "runtime_boundary": (
            "formal runtime receives only judge-equivalent inputs and frozen "
            "model/runtime settings"
        ),
        "capture_boundary": (
            "independent process only subscribes to existing RGB, annotated RGB, "
            "CameraInfo, rosout, and TF; it publishes nothing, calls no service, "
            "and receives no ground truth"
        ),
        "runtime_command": shlex.join(runtime_command),
        "capture_command": shlex.join(capture_command),
        "ground_truth_opened_for_scoring_and_analysis_after_runtime_exit": True,
        "immutable_input_hashes": before_hashes,
    }
    _write_json(run_dir / "isolation_audit.json", audit)

    capture_process, capture_log = _start_capture(
        capture_command,
        run_dir / "capture_process.log",
        capture_dir / "ready.json",
        15.0,
    )
    started = time.monotonic()
    runtime_log = run_dir / "runtime.log"
    try:
        runtime_code, runtime_seconds, timed_out = run_logged(
            runtime_command,
            runtime_log,
            harness_timeout_seconds,
        )
    finally:
        capture_code = _stop_capture(
            capture_process, capture_log, capture_stop_file
        )

    # Only after the formal runtime and the truth-blind capture have exited.
    metadata = _read_json(source_trial_dir / "scenario_metadata.json")
    answer_path = answer_dir / f"{runtime_inputs['group_number']}_answer.json"
    scores_path = run_dir / "scores.csv"
    details_path = run_dir / "scorer_details.json"
    scorer_log = run_dir / "scorer_output.txt"
    scorer_command = build_scorer_command(
        scorer_path,
        answer_dir,
        source_trial_dir / "ground_truth.json",
        scores_path,
        details_path,
    )
    scorer_code, scorer_seconds, _ = run_logged(
        scorer_command, scorer_log, 60.0
    )
    total_seconds_before_analysis = time.monotonic() - started
    summary = summarize_trial(
        metadata,
        answer_path,
        details_path,
        runtime_log,
        scorer_log,
        runtime_code,
        runtime_seconds,
        total_seconds_before_analysis,
        timed_out,
    )
    log_text = runtime_log.read_text(encoding="utf-8", errors="replace")
    summary.update({
        "run_id": run_id,
        "startup_success": (
            "Vision inputs are ready" in log_text
            and "Nav2 lifecycle stack is active" in log_text
        ),
        "nav2_startup_success": "Nav2 lifecycle stack is active" in log_text,
        "scorer_return_code": scorer_code,
        "scorer_wall_seconds": scorer_seconds,
        "capture_return_code": capture_code,
        "input_hashes_before": before_hashes,
        "input_hashes_after": input_hashes(source_trial_dir, model_path),
    })
    summary["immutable_inputs_unchanged"] = (
        summary["input_hashes_after"] == expected_hashes
    )
    _write_json(
        run_dir / "vision_telemetry.json",
        summary.get("vision_telemetry") or {"telemetry_available": False},
    )
    offline = None
    if (capture_dir / "camera_info.json").is_file():
        offline = analyze_capture(
            capture_dir,
            source_trial_dir / "scenario_metadata.json",
            model_path,
            run_dir / "offline",
            device=device,
            decision_threshold=0.50,
            confidence_floor=confidence_floor,
        )
    summary["offline_visibility_analysis"] = offline
    summary["total_wall_seconds_with_offline_analysis"] = (
        time.monotonic() - started
    )
    summary["artifacts"].update({
        "capture_directory": str(capture_dir.resolve()),
        "capture_log": str((run_dir / "capture_process.log").resolve()),
        "offline_summary": str(
            (run_dir / "offline/offline_summary.json").resolve()
        ),
        "isolation_audit": str((run_dir / "isolation_audit.json").resolve()),
    })
    _write_json(run_dir / "summary.json", summary)
    (run_dir / "wall_clock_seconds.txt").write_text(
        f"runtime={runtime_seconds:.6f}\n"
        f"scorer={scorer_seconds:.6f}\n"
        f"through_scoring={total_seconds_before_analysis:.6f}\n"
        f"including_offline_analysis={summary['total_wall_seconds_with_offline_analysis']:.6f}\n",
        encoding="utf-8",
    )
    (run_dir / "failure_stage.txt").write_text(
        f"{summary['failure_stage']}\n", encoding="utf-8"
    )
    return summary


def aggregate(summaries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    targets = summaries[0]["targets"]
    classes = {}
    for target in targets:
        classes[target] = {
            "runtime_detection_counts": [
                summary["classes"][target]["pipeline_telemetry"].get(
                    "detection_count"
                )
                for summary in summaries
            ],
            "offline_max_confidence_all_frames": [
                summary.get("offline_visibility_analysis", {})
                .get("classes", {}).get(target, {})
                .get("candidate_confidence_all_frames", {}).get("maximum")
                for summary in summaries
            ],
            "offline_above_threshold_frames_all": [
                summary.get("offline_visibility_analysis", {})
                .get("classes", {}).get(target, {})
                .get("above_threshold_frame_count_all")
                for summary in summaries
            ],
            "offline_above_threshold_frames_runtime": [
                summary.get("offline_visibility_analysis", {})
                .get("classes", {}).get(target, {})
                .get("above_threshold_frame_count_runtime")
                for summary in summaries
            ],
            "runtime_vs_offline_detection_consistent": [
                summary.get("offline_visibility_analysis", {})
                .get("classes", {}).get(target, {})
                .get("runtime_vs_offline_detection_consistent")
                for summary in summaries
            ],
            "TP": [summary["classes"][target]["TP"] for summary in summaries],
            "FP": [summary["classes"][target]["FP"] for summary in summaries],
            "FN": [summary["classes"][target]["FN"] for summary in summaries],
            "localization_errors_m": [
                summary["classes"][target]["matches"][0].get("distance_m")
                if summary["classes"][target]["matches"] else None
                for summary in summaries
            ],
        }
    return {
        "schema_version": 1,
        "trial_id": summaries[0]["trial_id"],
        "seed": summaries[0]["seed"],
        "run_count": len(summaries),
        "failure_stages": [summary["failure_stage"] for summary in summaries],
        "startup_success": [summary["startup_success"] for summary in summaries],
        "navigation_success": [
            summary["navigation_success"] for summary in summaries
        ],
        "scores": [summary["base_task_score"] for summary in summaries],
        "runtime_seconds": [
            summary["runtime_wall_seconds"] for summary in summaries
        ],
        "classes": classes,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-trial-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--runs", type=int, choices=(2, 3), default=3)
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
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--max-runtime-seconds", type=float, default=450.0)
    parser.add_argument("--harness-timeout-seconds", type=float, default=480.0)
    parser.add_argument("--capture-hz", type=float, default=10.0)
    parser.add_argument("--confidence-floor", type=float, default=0.001)
    args = parser.parse_args(argv)
    try:
        if args.output_dir.exists():
            raise EvaluationConfigError(
                f"output directory already exists: {args.output_dir}"
            )
        runtime_inputs = _read_json(args.source_trial_dir / "runtime_inputs.json")
        if Path(runtime_inputs["world_file"]).resolve() != (
            args.source_trial_dir / "scenario.world"
        ).resolve():
            raise EvaluationConfigError(
                "runtime world is not the immutable fixed scenario.world"
            )
        expected_hashes = input_hashes(args.source_trial_dir, args.model)
        setup_files = [
            Path("/opt/ros/humble/setup.bash"),
            Path("/home/hao/franka_ros2_ws/install/setup.bash"),
            Path("/home/hao/robocup_vision_venv/bin/activate"),
            Path("/home/hao/wpr_ros2_ws/install/setup.bash"),
        ]
        args.output_dir.mkdir(parents=True)
        _write_json(
            args.output_dir / "input_lock.json",
            {
                "schema_version": 1,
                "source_trial_directory": str(args.source_trial_dir.resolve()),
                "runs": args.runs,
                "runtime_inputs": runtime_inputs,
                "model_path": str(args.model.resolve()),
                "device": args.device,
                "decision_threshold": 0.50,
                "diagnostic_confidence_floor": args.confidence_floor,
                "capture_hz": args.capture_hz,
                "match_threshold_m": 0.10,
                "input_hashes": expected_hashes,
                "frozen_runtime_parameters_changed": False,
            },
        )
        summaries = []
        for run_index in range(1, args.runs + 1):
            print(f"Starting visibility trial {run_index}/{args.runs}", flush=True)
            summary = run_one(
                run_index,
                args.source_trial_dir,
                args.output_dir,
                runtime_inputs,
                args.model,
                args.scorer,
                args.device,
                args.max_runtime_seconds,
                args.harness_timeout_seconds,
                setup_files,
                expected_hashes,
                args.capture_hz,
                args.confidence_floor,
            )
            summaries.append(summary)
            print(
                f"Completed {summary['run_id']}: stage={summary['failure_stage']} "
                f"score={summary['base_task_score']:.1f} "
                f"runtime={summary['runtime_wall_seconds']:.1f}s",
                flush=True,
            )
        combined = aggregate(summaries)
        _write_json(args.output_dir / "visibility_gate_summary.json", combined)
        print(json.dumps(combined, indent=2))
        return 0
    except (
        EvaluationConfigError,
        OSError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as error:
        print(f"P2 visibility gate failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
