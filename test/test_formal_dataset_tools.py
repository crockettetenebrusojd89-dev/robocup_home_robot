#!/usr/bin/env python3
"""Regression tests for the offline formal-object dataset contract."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import generate_dataset
import validate_dataset


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TOOL_ROOT = PACKAGE_ROOT / 'tools' / 'formal_dataset'
EXPECTED_NAMES = [
    'apple',
    'banana',
    'beer',
    'bleach_cleanser',
    'bowl',
    'chips_can',
    'coke_can',
    'cracker_box',
    'gelatin_box',
    'master_chef_can',
    'mustard_bottle',
    'pitcher_base',
    'potted_meat_can',
    'pudding_box',
    'sugar_box',
    'tomato_soup_can',
    'tuna_fish_can',
    'windex_bottle',
]


class FormalDatasetToolsTest(unittest.TestCase):
    """Protect class identity and generator-to-worker configuration wiring."""

    @classmethod
    def setUpClass(cls):
        cls.manifest_path = TOOL_ROOT / 'classes.json'
        cls.config_path = TOOL_ROOT / 'config' / 'smoke.json'
        cls.classes = generate_dataset.load_manifest(cls.manifest_path)
        cls.config = generate_dataset.load_config(
            cls.config_path, len(cls.classes)
        )

    def test_exact_formal_class_order(self):
        self.assertEqual(
            [item['name'] for item in self.classes], EXPECTED_NAMES
        )
        self.assertEqual(validate_dataset.load_classes(self.manifest_path),
                         self.classes)

    def test_world_and_models_match_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            models = Path(temporary)
            for name in EXPECTED_NAMES:
                model = models / name
                model.mkdir()
                (model / 'model.config').touch()
                (model / 'model.sdf').touch()
            generate_dataset.check_world_and_models(self.classes, models)

    def test_every_randomization_range_reaches_worker(self):
        command = generate_dataset.worker_command(
            Path('/tmp/capture_worker'),
            Path('/tmp/formal_dataset_output'),
            self.config,
            self.classes,
        )
        self.assertEqual(len(command), 25 + len(self.classes))
        self.assertEqual(
            command[11:13],
            [str(value) for value in
             self.config['randomization']['object_yaw_rad']],
        )
        self.assertEqual(command[24], str(len(self.classes)))
        self.assertEqual(command[25:], EXPECTED_NAMES)

    def test_invalid_fraction_is_rejected(self):
        invalid = deepcopy(self.config)
        invalid['secondary_object_fraction'] = 1.01
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'invalid.json'
            path.write_text(json.dumps(invalid), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, r'must be in \[0, 1\]'):
                generate_dataset.load_config(path, len(self.classes))


if __name__ == '__main__':
    unittest.main()
