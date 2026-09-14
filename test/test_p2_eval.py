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
from run_trial import build_runtime_command
from run_trial import build_scorer_command


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


if __name__ == "__main__":
    unittest.main()
