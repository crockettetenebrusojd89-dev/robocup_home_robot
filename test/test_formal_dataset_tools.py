#!/usr/bin/env python3
"""Regression tests for the offline formal-object dataset contract."""

from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

import generate_dataset
import compose_dataset_v2
import evaluation_core
import prepare_v2_assets
import validate_dataset
import v2_common


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

    def test_v2_smoke_plan_is_targeted_and_split_before_capture(self):
        config = v2_common.load_v2_config(
            TOOL_ROOT / 'config' / 'v2_smoke.json', EXPECTED_NAMES
        )
        asset_manifest = {
            'classes': {
                name: {'tree_sha256': f'{index:064x}'}
                for index, name in enumerate(EXPECTED_NAMES, start=1)
            }
        }
        first = v2_common.build_scenario_plan(
            config, self.classes, asset_manifest
        )
        second = v2_common.build_scenario_plan(
            config, self.classes, asset_manifest
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first), 45)
        train_groups = {
            item['scene_group_id'] for item in first if item['split'] == 'train'
        }
        val_groups = {
            item['scene_group_id'] for item in first if item['split'] == 'val'
        }
        self.assertFalse(train_groups & val_groups)
        banana_train = [
            item for item in first
            if item['split'] == 'train'
            and item['primary']
            and item['primary']['class_name'] == 'banana'
        ]
        self.assertEqual(len(banana_train), 6)
        self.assertEqual(
            sum(item['camera']['distance_band'] == 'far' for item in banana_train),
            3,
        )
        self.assertGreaterEqual(
            sum(item['placement_category'] in {'edge', 'corner'} for item in banana_train),
            5,
        )
        self.assertEqual(sum(item['negative'] for item in first), 6)

    def test_v2_quota_rounding_is_exact_and_deterministic(self):
        weights = {'near': 1.0, 'mid': 2.0, 'far': 4.0}
        self.assertEqual(
            v2_common.quota_counts(6, weights),
            {'near': 1, 'mid': 2, 'far': 3},
        )
        self.assertEqual(sum(v2_common.quota_counts(288, weights).values()), 288)

    def test_v2_formal_plan_has_only_the_approved_targeted_supplement(self):
        config = v2_common.load_v2_config(
            TOOL_ROOT / 'config' / 'v2_formal.json', EXPECTED_NAMES
        )
        asset_manifest = {
            'classes': {
                name: {'tree_sha256': f'{index:064x}'}
                for index, name in enumerate(EXPECTED_NAMES, start=1)
            }
        }
        plan = v2_common.build_scenario_plan(
            config, self.classes, asset_manifest
        )
        self.assertEqual(len(plan), 724)
        expected = {
            'train': {
                'beer': 180, 'banana': 144, 'master_chef_can': 108,
                'coke_can': 36, 'pudding_box': 36,
                'tomato_soup_can': 36,
            },
            'val': {
                'beer': 45, 'banana': 36, 'master_chef_can': 27,
                'coke_can': 12, 'pudding_box': 12,
                'tomato_soup_can': 12,
            },
        }
        for split, expected_counts in expected.items():
            actual = {}
            for name in expected_counts:
                actual[name] = sum(
                    item['split'] == split
                    and item['primary'] is not None
                    and item['primary']['class_name'] == name
                    for item in plan
                )
            self.assertEqual(actual, expected_counts)
            self.assertEqual(
                sum(item['split'] == split and item['negative'] for item in plan),
                config['negative_samples'][split],
            )
        for item in plan:
            if item['secondary'] is None:
                continue
            self.assertTrue(v2_common.secondary_preserves_primary_visibility(
                item['camera']['position_world_m'][:2],
                item['primary']['position_world_m'][:2],
                item['secondary']['position_world_m'][:2],
                0.18,
            ))

    def test_secondary_visibility_guard_rejects_the_formal_failure_geometry(self):
        camera = (38.5652032469, -0.2009922575)
        primary = (40.4734802972, -0.0423429749)
        occluding_secondary = (39.5247707569, -0.0891949644)
        self.assertFalse(v2_common.secondary_preserves_primary_visibility(
            camera, primary, occluding_secondary, 0.18
        ))
        self.assertTrue(v2_common.secondary_preserves_primary_visibility(
            camera, primary, (39.6, 0.25), 0.18
        ))

    def test_v2_lighting_values_must_match_the_declared_profile(self):
        config = v2_common.load_v2_config(
            TOOL_ROOT / 'config' / 'v2_smoke.json', EXPECTED_NAMES
        )
        profile = config['lighting_profiles'][0]
        direction_length = math.sqrt(sum(
            value * value for value in profile['direction_xyz']
        ))
        lighting = {
            'seed': 1,
            'profile_id': profile['id'],
            'main_rgb': profile['main_rgb'],
            'main_intensity': sum(profile['main_intensity']) / 2,
            'direction_xyz': [
                value / direction_length for value in profile['direction_xyz']
            ],
            'ambient_fill_rgb': profile['ambient_fill_rgb'],
            'ambient_fill_intensity': sum(profile['ambient_fill_intensity']) / 2,
        }
        validate_dataset._validate_lighting(
            'sample', lighting, {profile['id']: profile}
        )
        lighting['main_intensity'] = 99.0
        with self.assertRaisesRegex(ValueError, 'intensity is outside'):
            validate_dataset._validate_lighting(
                'sample', lighting, {profile['id']: profile}
            )

    def test_empty_v2_label_is_parseable_for_declared_negatives(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'negative.txt'
            path.write_text('', encoding='utf-8')
            self.assertEqual(validate_dataset._read_boxes(path, set(range(18))), [])

    def test_dataset_view_uses_symlinks_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = root / 'source'
            for kind in ('images', 'labels'):
                for split in ('train', 'val'):
                    directory = dataset / kind / split
                    directory.mkdir(parents=True)
                    suffix = '.png' if kind == 'images' else '.txt'
                    (directory / f'sample{suffix}').write_text(
                        f'{kind}-{split}', encoding='utf-8'
                    )
            (dataset / 'classes.json').write_text(
                json.dumps({'classes': self.classes}), encoding='utf-8'
            )
            before = sorted(str(path.relative_to(dataset)) for path in dataset.rglob('*'))
            data_yaml = evaluation_core.create_dataset_view(dataset, root / 'view')
            after = sorted(str(path.relative_to(dataset)) for path in dataset.rglob('*'))
            self.assertEqual(before, after)
            self.assertTrue((root / 'view/images/train/sample.png').is_symlink())
            self.assertEqual(
                json.loads(data_yaml.read_text())['path'], str((root / 'view').resolve())
            )

    def test_subset_reader_maps_to_view_and_rejects_duplicates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = root / 'source'
            view = root / 'view'
            for base in (dataset, view):
                image = base / 'images' / 'val' / 'one.png'
                image.parent.mkdir(parents=True)
                image.touch()
            subset = root / 'subset.txt'
            subset.write_text('images/val/one.png\n', encoding='utf-8')
            self.assertEqual(
                evaluation_core.load_subset_images(dataset, subset, view),
                [view.resolve() / 'images' / 'val' / 'one.png'],
            )
            subset.write_text(
                'images/val/one.png\nimages/val/one.png\n', encoding='utf-8'
            )
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                evaluation_core.load_subset_images(dataset, subset, view)

    def test_negative_detection_summary_records_class_and_confidence(self):
        class FakeValues:
            def __init__(self, values):
                self.values = values

            def tolist(self):
                return self.values

        class FakeBoxes:
            cls = FakeValues([2.0, 1.0])
            conf = FakeValues([0.75, 0.51])

        class FakeResult:
            path = '/tmp/negative.png'
            boxes = FakeBoxes()

        summary = evaluation_core.negative_detection_document(
            [FakeResult()], {1: 'banana', 2: 'beer'}, 10
        )
        self.assertEqual(summary['detection_count'], 2)
        self.assertEqual(summary['images_with_detections'], 1)
        self.assertEqual(summary['detections'][0]['class_name'], 'beer')
        self.assertEqual(summary['detections'][1]['confidence'], 0.51)

    def test_subset_map50_95_uses_class_id_when_a_class_is_absent(self):
        class Box:
            p = [0.8, 0.9]
            r = [0.7, 0.95]
            ap50 = [0.75, 0.97]
            maps = [0.61, 0.22, 0.88]
            mp = 0.85
            mr = 0.825
            map50 = 0.86
            map = 0.745

        class Metrics:
            box = Box()
            ap_class_index = [0, 2]
            names = {0: 'apple', 1: 'banana', 2: 'beer'}
            nt_per_class = [1, 0, 2]

        document = evaluation_core.metrics_document(Metrics(), 3)
        by_name = {item['name']: item for item in document['per_class']}
        self.assertEqual(by_name['apple']['map50_95'], 0.61)
        self.assertIsNone(by_name['banana']['map50_95'])
        self.assertEqual(by_name['beer']['map50_95'], 0.88)

    def test_composition_removes_whole_beer_images_and_preserves_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            v1 = root / 'v1'
            targeted = root / 'targeted'
            output = root / 'final'
            class_document = {'classes': self.classes}
            for dataset in (v1, targeted):
                for split in ('train', 'val'):
                    (dataset / 'images' / split).mkdir(parents=True)
                    (dataset / 'labels' / split).mkdir(parents=True)
                (dataset / 'classes.json').write_text(
                    json.dumps(class_document, indent=2) + '\n', encoding='utf-8'
                )
                (dataset / 'generation_config.json').write_text('{}\n', encoding='utf-8')

            def sample(dataset, split, stem, label, payload):
                (dataset / 'images' / split / f'{stem}.png').write_bytes(payload)
                (dataset / 'labels' / split / f'{stem}.txt').write_text(
                    label, encoding='utf-8'
                )

            sample(v1, 'train', 'sample', '0 0.5 0.5 0.2 0.2\n', b'v1-train-clean')
            sample(v1, 'train', 'old_beer', '2 0.5 0.5 0.2 0.2\n', b'v1-train-beer')
            sample(v1, 'val', 'sample', '3 0.5 0.5 0.2 0.2\n', b'v1-val-clean')
            sample(v1, 'val', 'old_beer', '0 0.2 0.2 0.1 0.1\n2 0.6 0.6 0.2 0.2\n', b'v1-val-beer')
            sample(targeted, 'train', 'sample', '', b'v2-train-negative')
            sample(targeted, 'val', 'val_sample', '1 0.5 0.5 0.2 0.2\n', b'v2-val-positive')
            scenarios = [
                {'sample_id': 'sample', 'split': 'train', 'negative': True,
                 'scene_group_id': 'train:negative:0'},
                {'sample_id': 'val_sample', 'split': 'val', 'negative': False,
                 'scene_group_id': 'val:banana:0'},
            ]
            (targeted / 'scenario_manifest.jsonl').write_text(
                ''.join(json.dumps(item) + '\n' for item in scenarios), encoding='utf-8'
            )
            (targeted / 'asset_manifest.json').write_text('{}\n', encoding='utf-8')
            (targeted / 'capture_plan.tsv').write_text('header\n', encoding='utf-8')

            counts = {
                'EXPECTED_V1_IMAGES': {'train': 2, 'val': 2},
                'EXPECTED_REMOVED_BEER_IMAGES': {'train': 1, 'val': 1},
                'EXPECTED_CLEAN_REPLAY': {'train': 1, 'val': 1},
                'EXPECTED_TARGETED': {'train': 1, 'val': 1},
                'EXPECTED_FINAL': {'train': 2, 'val': 2},
            }
            with mock.patch.multiple(compose_dataset_v2, **counts), mock.patch.object(
                compose_dataset_v2.subprocess, 'run'
            ):
                summary = compose_dataset_v2.compose(
                    v1, targeted, output, self.manifest_path
                )

            records = compose_dataset_v2._read_jsonl(
                output / 'dataset_composition_manifest.jsonl'
            )
            self.assertEqual(summary['actual']['final_images'], {'train': 2, 'val': 2})
            self.assertEqual(len(records), 4)
            self.assertEqual(
                {record['source'] for record in records},
                {'legacy_v1_replay', 'v2_targeted'},
            )
            self.assertFalse(any('old_beer' in record['sample_id'] for record in records))
            self.assertTrue((output / 'images' / 'train' / 'legacy_v1_train_sample.png').is_file())
            self.assertTrue(
                (output / 'images' / 'train' / 'v2_targeted_train_sample.png').is_file()
            )
            excluded = compose_dataset_v2._read_jsonl(
                output / 'metadata' / 'excluded_legacy_beer.jsonl'
            )
            self.assertEqual(len(excluded), 2)
            self.assertTrue(all(2 in record['class_ids'] for record in excluded))
            self.assertEqual(
                (output / 'metadata' / 'validation_subsets' / 'negative_val.txt').read_text(),
                '',
            )
            self.assertEqual(
                (output / 'metadata' / 'validation_subsets' / 'targeted_val.txt').read_text(),
                'images/val/v2_targeted_val_val_sample.png\n',
            )

    def test_prepare_v2_assets_preserves_source_and_installs_pbr_beer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'v1'
            for name in EXPECTED_NAMES:
                model = source / name
                model.mkdir(parents=True)
                (model / 'model.config').write_text(name, encoding='utf-8')
                (model / 'model.sdf').write_text('<sdf/>', encoding='utf-8')
            original_beer = (source / 'beer' / 'model.sdf').read_bytes()
            archive_path = root / 'beer.zip'
            with zipfile.ZipFile(archive_path, 'w') as archive:
                archive.writestr(
                    'beer/model.sdf',
                    '<sdf version="1.6"><pbr><albedo_map>beer.png</albedo_map></pbr></sdf>',
                )
                archive.writestr('beer/model.config', 'beer-v2')
                archive.writestr('beer/materials/textures/beer.png', b'png-bytes')
            output = root / 'v2'
            provenance = prepare_v2_assets.prepare(
                source, archive_path, output, EXPECTED_NAMES
            )
            self.assertEqual((source / 'beer' / 'model.sdf').read_bytes(), original_beer)
            self.assertIn('<pbr>', (output / 'beer' / 'model.sdf').read_text())
            self.assertEqual(provenance['schema_version'], 2)
            self.assertTrue((output / 'asset_provenance.json').is_file())

    def test_prepare_v2_assets_rejects_archive_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / 'beer.zip'
            with zipfile.ZipFile(archive_path, 'w') as archive:
                archive.writestr('../escape', 'bad')
            with zipfile.ZipFile(archive_path) as archive:
                with self.assertRaisesRegex(ValueError, 'unsafe'):
                    prepare_v2_assets._safe_members(archive)


if __name__ == '__main__':
    unittest.main()
