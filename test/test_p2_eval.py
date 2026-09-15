#!/usr/bin/env python3
"""Regression tests for the isolated, deterministic P2 evaluation boundary."""

import json
from pathlib import Path
import tempfile
import unittest

from p2_eval_core import EvaluationConfigError
from p2_eval_core import generate_trial
from p2_eval_core import load_table_config
from p2_eval_core import table_distance_bounds
from run_trial import MATCH_THRESHOLD_M
from run_trial import _class_seen
from run_trial import _cluster_seen
from run_trial import _observation_window
from run_trial import _stage_from_log
from run_trial import _vision_telemetry
from run_trial import _pipeline_state
from run_trial import build_runtime_command
from run_trial import build_scorer_command
from run_repeatability import aggregate_summaries
from run_repeatability import repeatability_row


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TABLE_CONFIG = PACKAGE_ROOT / "tools/p2_eval/tables.json"
SCENARIO = PACKAGE_ROOT / "tools/p2_eval/scenarios/smoke_multitable.json"
MANIFEST = PACKAGE_ROOT / "tools/formal_dataset/classes.json"


class P2EvaluationTest(unittest.TestCase):
    def _base_world(self, directory: Path) -> Path:
        path = directory / "base.world"
        path.write_text(
            """<?xml version='1.0'?>
<sdf version='1.8'>
  <world name='robocup_home'>
    <model name='floor'><static>true</static></model>
    <include>
      <uri>model://apple</uri><name>old_apple</name>
      <pose>0 0 0 0 0 0</pose>
    </include>
    <include>
      <uri>model://chair</uri><name>keep_chair</name>
      <pose>1 1 0 0 0 0</pose>
    </include>
  </world>
</sdf>
""",
            encoding="utf-8",
        )
        return path

    def test_generation_is_reproducible_and_removes_old_official_objects(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = self._base_world(root)
            first = generate_trial(
                base, TABLE_CONFIG, SCENARIO, MANIFEST, root / "first"
            )
            second = generate_trial(
                base, TABLE_CONFIG, SCENARIO, MANIFEST, root / "second"
            )
            first_metadata = json.loads(
                first["metadata"].read_text(encoding="utf-8")
            )
            second_metadata = json.loads(
                second["metadata"].read_text(encoding="utf-8")
            )
            self.assertEqual(first_metadata["objects"], second_metadata["objects"])
            generated_world = first["world"].read_text(encoding="utf-8")
            self.assertNotIn("old_apple", generated_world)
            self.assertIn("keep_chair", generated_world)
            self.assertEqual(generated_world.count("<include>"), 4)

    def test_generated_truth_and_runtime_inputs_are_separate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = generate_trial(
                self._base_world(root),
                TABLE_CONFIG,
                SCENARIO,
                MANIFEST,
                root / "trial",
            )
            runtime_inputs = json.loads(
                paths["runtime_inputs"].read_text(encoding="utf-8")
            )
            ground_truth = json.loads(
                paths["ground_truth"].read_text(encoding="utf-8")
            )
            self.assertEqual(
                set(runtime_inputs),
                {
                    "world_file",
                    "world_name",
                    "target_1",
                    "target_2",
                    "target_3",
                    "group_number",
                },
            )
            self.assertNotIn("objects", runtime_inputs)
            self.assertIn("objects", ground_truth)

    def test_runtime_command_rejects_any_extra_ground_truth_field(self):
        runtime_inputs = {
            "world_file": "/tmp/scenario.world",
            "world_name": "robocup_home",
            "target_1": "apple",
            "target_2": "coke_can",
            "target_3": "banana",
            "group_number": 201,
            "ground_truth": {"x": 1.0, "y": 2.0},
        }
        with self.assertRaisesRegex(EvaluationConfigError, "exactly"):
            build_runtime_command(
                runtime_inputs,
                Path("/tmp/submission"),
                Path("/tmp/model.pt"),
                "cpu",
                450.0,
                (),
            )

    def test_runtime_command_allows_only_explicit_p2_viewpoint_override(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "model.pt"
            model.touch()
            runtime_inputs = {
                "world_file": "/tmp/scenario.world",
                "world_name": "robocup_home",
                "target_1": "apple",
                "target_2": "coke_can",
                "target_3": "banana",
                "group_number": 201,
            }
            command = build_runtime_command(
                runtime_inputs,
                root / "submission",
                model,
                "cpu",
                450.0,
                (),
                {
                    "runner_executable": "p2_viewpoint_task_runner",
                    "observation_plan_json": '[{"x":0,"y":0,"yaw":0}]',
                },
            )
            self.assertIn(
                "runner_executable:=p2_viewpoint_task_runner", command[-1]
            )
            self.assertIn("observation_plan_json:=", command[-1])
            with self.assertRaisesRegex(EvaluationConfigError, "unsupported"):
                build_runtime_command(
                    runtime_inputs,
                    root / "submission",
                    model,
                    "cpu",
                    450.0,
                    (),
                    {"ground_truth": "forbidden"},
                )

    def test_scorer_command_explicitly_uses_ten_centimeters(self):
        self.assertEqual(MATCH_THRESHOLD_M, 0.10)
        with tempfile.TemporaryDirectory() as temporary:
            scorer = Path(temporary) / "score_submission.py"
            scorer.write_text("pass\n", encoding="utf-8")
            command = build_scorer_command(
                scorer,
                Path(temporary) / "submissions",
                Path(temporary) / "truth.json",
                Path(temporary) / "scores.csv",
                Path(temporary) / "details.json",
            )
        threshold_index = command.index("--match-threshold")
        self.assertEqual(command[threshold_index + 1], "0.10")

    def test_stage_parser_reports_nav2_after_robot_is_ready(self):
        log = "\n".join(
            (
                "Gazebo world is ready; spawning the robot once.",
                "Robot interfaces are ready; starting saved-map Nav2 and RViz.",
                "Vision inputs unavailable after 120s",
            )
        )
        self.assertEqual(
            _stage_from_log(log, False),
            ("nav2_ready", "Nav2 did not become active"),
        )

    def test_stage_parser_identifies_missing_map_transform(self):
        log = "Timed out waiting for transform from base_link to map to become available"
        self.assertEqual(
            _stage_from_log(log, False),
            (
                "nav2_map_tf",
                "Nav2 could not obtain the map-to-base_link transform",
            ),
        )

    def test_explicit_navigation_failure_wins_over_transient_map_warning(self):
        log = "\n".join((
            "Timed out waiting for transform from base_link to map",
            "Nav2 lifecycle stack is active.",
            "Goal accepted: navigating to living room.",
            "Living room navigation failed. Status: ABORTED (6).",
        ))
        self.assertEqual(
            _stage_from_log(log, False),
            ("navigation", "navigation did not report success"),
        )

    def test_explicit_scan_failure_wins_over_transient_map_warning(self):
        log = "\n".join((
            "Timed out waiting for transform from base_link to map",
            "Living room navigation succeeded.",
            "Scan step 1/12 failed. Spin status: ABORTED (6).",
        ))
        self.assertEqual(
            _stage_from_log(log, False),
            ("scan", "living-room scan did not complete"),
        )

    def test_prefixed_ros_log_evidence_is_recognized(self):
        log = "\n".join(
            (
                "[localizer-1] apple: conf=0.900, depth=1.0m",
                "[localizer-1] [INFO] Tracked objects:",
                "[localizer-1] apple:",
                "[localizer-1]   #0 observations=5 confirmed=true",
            )
        )
        self.assertTrue(_class_seen(log, "apple"))
        self.assertTrue(_cluster_seen(log, "apple"))
        self.assertFalse(_class_seen(log, "banana"))

    def test_observation_evidence_excludes_pre_reset_detections(self):
        log = "\n".join(
            (
                "[localizer-1] coke_can: conf=0.900, depth=1.0m",
                "[localizer-1] Reset visual tracking; removed 1 clusters.",
                "[localizer-1] apple: conf=0.900, depth=1.0m",
            )
        )
        window = _observation_window(log)
        self.assertFalse(_class_seen(window, "coke_can"))
        self.assertTrue(_class_seen(window, "apple"))

    def test_structured_telemetry_separates_visual_pipeline_stages(self):
        before = {
            "schema_version": 1,
            "inference_frames": 2,
            "classes": {"apple": {"detection_count": 99}},
        }
        after = {
            "schema_version": 1,
            "inference_frames": 42,
            "classes": {
                "apple": {
                    "detection_count": 7,
                    "depth_valid_count": 5,
                    "depth_invalid_count": 2,
                    "tf_success_count": 4,
                    "tf_failure_count": 1,
                    "clusters": [{"observations": 4, "confirmed": True}],
                },
                "banana": {
                    "detection_count": 0,
                    "depth_valid_count": 0,
                    "depth_invalid_count": 0,
                    "tf_success_count": 0,
                    "tf_failure_count": 0,
                    "clusters": [],
                },
            },
        }
        log = "\n".join((
            "VISION_TELEMETRY " + json.dumps(before),
            "Reset visual tracking; removed 1 clusters.",
            "[localizer] VISION_TELEMETRY " + json.dumps(after),
        ))
        telemetry = _vision_telemetry(log)
        apple = _pipeline_state(telemetry, "apple", 0)
        banana = _pipeline_state(telemetry, "banana", 0)
        self.assertEqual(apple["detection_status"], "detected")
        self.assertEqual(apple["depth_status"], "valid")
        self.assertEqual(apple["tf_status"], "success")
        self.assertEqual(apple["cluster_status"], "formed")
        self.assertEqual(apple["maximum_cluster_observations"], 4)
        self.assertEqual(banana["detection_status"], "not_detected")
        self.assertEqual(banana["depth_status"], "not_reached")
        self.assertEqual(banana["tf_status"], "not_reached")
        self.assertEqual(telemetry["inference_frames"], 42)
        not_evaluated = _pipeline_state(None, "apple", 0, False)
        self.assertEqual(
            not_evaluated["detection_status"],
            "not_evaluated",
        )

    def test_all_four_tables_have_nonempty_legal_regions_and_distance_bounds(self):
        config = load_table_config(TABLE_CONFIG)
        scan_xy = (config["scan_pose_map"]["x"], config["scan_pose_map"]["y"])
        self.assertEqual(len(config["tables"]), 4)
        for table in config["tables"]:
            nearest, farthest = table_distance_bounds(
                table,
                config["placement_policy"],
                scan_xy,
            )
            self.assertGreater(nearest, 0.0)
            self.assertGreater(farthest, nearest)
            self.assertLess(farthest, config["camera"]["depth_max_m"])

    def test_repeatability_aggregation_keeps_missing_raw_detection_unknown(self):
        def summary(run_id, apple_error, coke_success):
            return {
                "run_id": run_id,
                "trial_id": "fixed",
                "seed": 7,
                "targets": ["apple", "coke_can"],
                "startup_success": True,
                "nav2_startup_success": True,
                "navigation_success": True,
                "scan_completed": True,
                "failure_stage": "success",
                "scorer_return_code": 0,
                "base_task_score": 50.0 if not coke_success else 60.0,
                "runtime_wall_seconds": 100.0,
                "maximum_localization_error_m": apple_error,
                "vision_score": 10.0 if not coke_success else 20.0,
                "navigation_score": 40.0,
                "classes": {
                    "apple": {
                        "TP": 1, "FP": 0, "FN": 0,
                        "matches": [{"distance_m": apple_error}],
                    },
                    "coke_can": {
                        "TP": int(coke_success), "FP": 0,
                        "FN": int(not coke_success),
                        "matches": ([{"distance_m": 0.04}] if coke_success else []),
                    },
                },
                "objects": [
                    {
                        "class_name": "apple",
                        "localization_pipeline_success": True,
                        "entered_final_answer": True,
                        "true_positive": True,
                        "localization_error_m": apple_error,
                    },
                    {
                        "class_name": "coke_can",
                        "localization_pipeline_success": coke_success,
                        "entered_final_answer": coke_success,
                        "true_positive": coke_success,
                        "localization_error_m": 0.04 if coke_success else None,
                    },
                ],
            }

        summaries = [summary("run_01", 0.09, False), summary("run_02", 0.08, True)]
        aggregate = aggregate_summaries(summaries)
        apple = aggregate["class_statistics"]["apple"]
        coke = aggregate["class_statistics"]["coke_can"]
        self.assertIsNone(coke["raw_detection_success_rate"])
        self.assertEqual(coke["visual_stage_final_answer_success_rate"], 0.5)
        self.assertAlmostEqual(apple["mean_localization_error_m"], 0.085)
        self.assertEqual(aggregate["complete_runtime_success_rate"], 1.0)
        self.assertEqual(repeatability_row(summaries[0])["apple_TP"], 1)


if __name__ == "__main__":
    unittest.main()
