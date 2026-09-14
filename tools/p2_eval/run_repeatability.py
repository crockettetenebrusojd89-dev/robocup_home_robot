#!/usr/bin/env python3
"""Repeat one immutable P2 trial and aggregate run-to-run stability evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import shlex
import statistics
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence

from p2_eval_core import EvaluationConfigError
from run_trial import MATCH_THRESHOLD_M
from run_trial import _read_json
from run_trial import build_runtime_command
from run_trial import build_scorer_command
from run_trial import run_logged
from run_trial import summarize_trial


REQUIRED_SOURCE_FILES = (
    "scenario.world",
    "scenario_metadata.json",
    "runtime_inputs.json",
    "ground_truth.json",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def input_hashes(source_trial_dir: Path, model_path: Path) -> dict[str, str]:
    paths = {name: source_trial_dir / name for name in REQUIRED_SOURCE_FILES}
    paths["model"] = model_path
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise EvaluationConfigError(f"repeatability inputs are missing: {missing}")
    return {name: sha256_file(path) for name, path in paths.items()}


def class_row(summary: Mapping[str, Any], class_name: str) -> dict[str, Any]:
    report = summary["classes"][class_name]
    matches = report.get("matches", [])
    return {
        "TP": int(report["TP"]),
        "FP": int(report["FP"]),
        "FN": int(report["FN"]),
        "error_m": matches[0].get("distance_m") if matches else None,
    }


def repeatability_row(summary: Mapping[str, Any]) -> dict[str, Any]:
    row = {
        "run_id": summary["run_id"],
        "startup_success": summary["startup_success"],
        "nav2_startup_success": summary["nav2_startup_success"],
        "navigation_success": summary["navigation_success"],
        "vision_evaluated": summary["scan_completed"],
        "scorer_success": summary["scorer_return_code"] == 0,
    }
    for class_name in summary["targets"]:
        values = class_row(summary, class_name)
        for field, value in values.items():
            row[f"{class_name}_{field}"] = value
    row.update({
        "max_localization_error_m": summary["maximum_localization_error_m"],
        "vision_score": summary["vision_score"],
        "navigation_score": summary["navigation_score"],
        "total_score": summary["base_task_score"],
        "runtime_seconds": summary["runtime_wall_seconds"],
        "failure_stage": summary["failure_stage"],
    })
    return row


def _rate(flags: Sequence[bool]) -> float:
    return sum(bool(flag) for flag in flags) / len(flags)


def aggregate_summaries(summaries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not summaries:
        raise EvaluationConfigError("at least one summary is required")
    targets = list(summaries[0]["targets"])
    class_statistics = {}
    for class_name in targets:
        object_evidence = [
            next(
                item for item in summary["objects"]
                if item["class_name"] == class_name
            )
            for summary in summaries
        ]
        errors = [
            float(item["localization_error_m"])
            for item in object_evidence
            if item["localization_error_m"] is not None
        ]
        vision_evidence = [
            item
            for item, summary in zip(object_evidence, summaries)
            if summary["scan_completed"]
        ]
        class_statistics[class_name] = {
            "raw_detection_success_rate": None,
            "raw_detection_observability": (
                "not independently observable: a missing localization cannot "
                "be separated into detector, depth, or TF failure"
            ),
            "visual_stage_evaluable_runs": len(vision_evidence),
            "end_to_end_localization_success_rate": _rate([
                bool(item["localization_pipeline_success"])
                for item in object_evidence
            ]),
            "end_to_end_final_answer_success_rate": _rate([
                bool(item["entered_final_answer"])
                for item in object_evidence
            ]),
            "visual_stage_localization_success_rate": (
                _rate([
                    bool(item["localization_pipeline_success"])
                    for item in vision_evidence
                ])
                if vision_evidence else None
            ),
            "visual_stage_final_answer_success_rate": (
                _rate([
                    bool(item["entered_final_answer"])
                    for item in vision_evidence
                ])
                if vision_evidence else None
            ),
            "true_positive_rate": _rate([
                bool(item["true_positive"])
                for item in object_evidence
            ]),
            "TP_by_run": [summary["classes"][class_name]["TP"] for summary in summaries],
            "FP_by_run": [summary["classes"][class_name]["FP"] for summary in summaries],
            "FN_by_run": [summary["classes"][class_name]["FN"] for summary in summaries],
            "localization_errors_m": errors,
            "mean_localization_error_m": statistics.fmean(errors) if errors else None,
            "maximum_localization_error_m": max(errors) if errors else None,
        }

    scores = [float(summary["base_task_score"]) for summary in summaries]
    runtimes = [float(summary["runtime_wall_seconds"]) for summary in summaries]
    return {
        "schema_version": 1,
        "trial_id": summaries[0]["trial_id"],
        "seed": summaries[0]["seed"],
        "run_count": len(summaries),
        "match_threshold_m": MATCH_THRESHOLD_M,
        "complete_runtime_success_rate": _rate([
            summary["failure_stage"] == "success" for summary in summaries
        ]),
        "perfect_70_score_rate": _rate([
            float(summary["base_task_score"]) == 70.0 for summary in summaries
        ]),
        "startup_success_rate": _rate([
            bool(summary["startup_success"]) for summary in summaries
        ]),
        "nav2_startup_success_rate": _rate([
            bool(summary["nav2_startup_success"]) for summary in summaries
        ]),
        "class_statistics": class_statistics,
        "total_scores": scores,
        "mean_total_score": statistics.fmean(scores),
        "minimum_total_score": min(scores),
        "runtime_seconds": runtimes,
        "mean_runtime_seconds": statistics.fmean(runtimes),
        "maximum_runtime_seconds": max(runtimes),
        "failure_stages": [summary["failure_stage"] for summary in summaries],
    }


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _write_table(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run_once(
    run_index: int,
    source_trial_dir: Path,
    output_dir: Path,
    runtime_inputs: Mapping[str, Any],
    metadata: Mapping[str, Any],
    model_path: Path,
    scorer_path: Path,
    device: str,
    max_runtime_seconds: float,
    harness_timeout_seconds: float,
    setup_files: Sequence[Path],
    expected_hashes: Mapping[str, str],
) -> dict[str, Any]:
    run_id = f"run_{run_index:02d}"
    run_dir = output_dir / run_id
    run_dir.mkdir()
    answer_dir = run_dir / "submission"
    answer_dir.mkdir()

    before_hashes = input_hashes(source_trial_dir, model_path)
    if before_hashes != expected_hashes:
        raise EvaluationConfigError(
            f"{run_id}: immutable input hash changed before runtime"
        )

    runtime_command = build_runtime_command(
        runtime_inputs,
        answer_dir,
        model_path,
        device,
        max_runtime_seconds,
        setup_files,
    )
    audit = {
        "run_id": run_id,
        "source_trial_directory": str(source_trial_dir.resolve()),
        "input_hashes_before": before_hashes,
        "runtime_boundary": (
            "formal runtime receives only the immutable world path/name, three "
            "target strings, group number, model/device, output directory, and timeout"
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
    audit_path = run_dir / "isolation_audit.json"
    _write_json(audit_path, audit)

    started = time.monotonic()
    runtime_log = run_dir / "runtime.log"
    runtime_code, runtime_seconds, timed_out = run_logged(
        runtime_command,
        runtime_log,
        harness_timeout_seconds,
    )
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
    scorer_code, _scorer_seconds, _ = run_logged(
        scorer_command,
        scorer_log,
        60.0,
    )

    total_seconds = time.monotonic() - started
    summary = summarize_trial(
        metadata,
        answer_path,
        details_path,
        runtime_log,
        scorer_log,
        runtime_code,
        runtime_seconds,
        total_seconds,
        timed_out,
    )
    log = runtime_log.read_text(encoding="utf-8", errors="replace")
    summary.update({
        "run_id": run_id,
        "startup_success": (
            "Vision inputs are ready" in log
            and "Nav2 lifecycle stack is active" in log
        ),
        "nav2_startup_success": "Nav2 lifecycle stack is active" in log,
        "scorer_return_code": scorer_code,
        "scorer_command": shlex.join(scorer_command),
        "input_hashes_before": before_hashes,
        "input_hashes_after": input_hashes(source_trial_dir, model_path),
    })
    summary["immutable_inputs_unchanged"] = (
        summary["input_hashes_after"] == expected_hashes
    )
    summary["artifacts"].update({
        "scenario_world": str((source_trial_dir / "scenario.world").resolve()),
        "ground_truth": str((source_trial_dir / "ground_truth.json").resolve()),
        "scenario_metadata": str(
            (source_trial_dir / "scenario_metadata.json").resolve()
        ),
        "isolation_audit": str(audit_path.resolve()),
    })
    _write_json(run_dir / "summary.json", summary)
    (run_dir / "wall_clock_seconds.txt").write_text(
        f"runtime={runtime_seconds:.6f}\ntotal={total_seconds:.6f}\n",
        encoding="utf-8",
    )
    (run_dir / "failure_stage.txt").write_text(
        f"{summary['failure_stage']}\n",
        encoding="utf-8",
    )
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-trial-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--runs", type=int, default=5)
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
    args = parser.parse_args(argv)

    try:
        if args.runs < 1:
            raise EvaluationConfigError("runs must be positive")
        if args.output_dir.exists():
            raise EvaluationConfigError(
                f"output directory already exists: {args.output_dir}"
            )
        runtime_inputs = _read_json(args.source_trial_dir / "runtime_inputs.json")
        metadata = _read_json(args.source_trial_dir / "scenario_metadata.json")
        if Path(runtime_inputs["world_file"]).resolve() != (
            args.source_trial_dir / "scenario.world"
        ).resolve():
            raise EvaluationConfigError(
                "runtime_inputs world_file is not the immutable source scenario.world"
            )
        expected_hashes = input_hashes(args.source_trial_dir, args.model)
        args.output_dir.mkdir(parents=True)
        setup_files = [
            Path("/opt/ros/humble/setup.bash"),
            Path("/home/hao/franka_ros2_ws/install/setup.bash"),
            Path("/home/hao/robocup_vision_venv/bin/activate"),
            Path("/home/hao/wpr_ros2_ws/install/setup.bash"),
        ]
        input_lock = {
            "schema_version": 1,
            "source_trial_directory": str(args.source_trial_dir.resolve()),
            "trial_id": metadata["trial_id"],
            "seed": metadata["seed"],
            "runs": args.runs,
            "runtime_inputs": runtime_inputs,
            "model_path": str(args.model.resolve()),
            "device": args.device,
            "max_runtime_seconds": args.max_runtime_seconds,
            "harness_timeout_seconds": args.harness_timeout_seconds,
            "match_threshold_m": MATCH_THRESHOLD_M,
            "input_hashes": expected_hashes,
        }
        _write_json(args.output_dir / "input_lock.json", input_lock)

        summaries = []
        for run_index in range(1, args.runs + 1):
            print(f"Starting repeatability run {run_index}/{args.runs}", flush=True)
            summary = run_once(
                run_index,
                args.source_trial_dir,
                args.output_dir,
                runtime_inputs,
                metadata,
                args.model,
                args.scorer,
                args.device,
                args.max_runtime_seconds,
                args.harness_timeout_seconds,
                setup_files,
                expected_hashes,
            )
            summaries.append(summary)
            print(
                f"Completed {summary['run_id']}: "
                f"stage={summary['failure_stage']} "
                f"score={summary['base_task_score']:.1f} "
                f"runtime={summary['runtime_wall_seconds']:.1f}s",
                flush=True,
            )

        rows = [repeatability_row(summary) for summary in summaries]
        aggregate = aggregate_summaries(summaries)
        _write_json(args.output_dir / "repeatability_table.json", rows)
        _write_table(args.output_dir / "repeatability_table.csv", rows)
        _write_json(args.output_dir / "aggregate_summary.json", aggregate)
        print(json.dumps(aggregate, indent=2))
        return 0
    except (EvaluationConfigError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"P2 repeatability gate failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
