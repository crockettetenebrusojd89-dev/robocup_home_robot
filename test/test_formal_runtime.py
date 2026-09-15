#!/usr/bin/env python3
"""Regression tests for formal judge-input and output contracts."""

import json
from pathlib import Path
import tempfile
import unittest

from formal_runtime_config import load_aliases
from formal_runtime_config import load_class_manifest
from formal_runtime_config import parse_group_number
from formal_runtime_config import resolve_target_classes
from formal_runtime_config import validate_answer_document
from formal_runtime_config import validate_model_contract
from p2_viewpoint_plan import parse_observation_plan


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = PACKAGE_ROOT / 'tools' / 'formal_dataset' / 'classes.json'
ALIASES = PACKAGE_ROOT / 'config' / 'formal_class_aliases.json'


class FormalRuntimeTest(unittest.TestCase):
    """Keep competition input handling deterministic and fail closed."""

    @classmethod
    def setUpClass(cls):
        cls.classes = load_class_manifest(MANIFEST)
        cls.aliases = load_aliases(ALIASES, cls.classes)

    def test_manifest_is_exact_official_18_class_order(self):
        self.assertEqual(len(self.classes), 18)
        self.assertEqual(self.classes[0], 'apple')
        self.assertEqual(self.classes[-1], 'windex_bottle')

    def test_default_alias_file_makes_no_unconfirmed_assumptions(self):
        self.assertEqual(self.aliases, {})

    def test_three_exact_canonical_targets_are_accepted(self):
        resolved = resolve_target_classes(
            ['apple', 'chips_can', 'windex_bottle'],
            self.classes,
            self.aliases,
        )
        self.assertEqual(resolved, ('apple', 'chips_can', 'windex_bottle'))

    def test_surrounding_whitespace_is_removed_only(self):
        resolved = resolve_target_classes(
            [' apple ', 'chips_can', 'windex_bottle'],
            self.classes,
            self.aliases,
        )
        self.assertEqual(resolved[0], 'apple')
        with self.assertRaisesRegex(ValueError, 'Unknown judge target'):
            resolve_target_classes(
                ['APPLE', 'chips_can', 'windex_bottle'],
                self.classes,
                self.aliases,
            )

    def test_explicit_alias_is_applied(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'aliases.json'
            path.write_text(
                json.dumps({
                    'schema_version': 1,
                    'aliases': {'coke can': 'coke_can'},
                }),
                encoding='utf-8',
            )
            aliases = load_aliases(path, self.classes)
        resolved = resolve_target_classes(
            ['apple', 'coke can', 'banana'],
            self.classes,
            aliases,
        )
        self.assertEqual(resolved, ('apple', 'coke_can', 'banana'))

    def test_unknown_target_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unknown judge target'):
            resolve_target_classes(
                ['apple', 'not_official', 'banana'],
                self.classes,
                self.aliases,
            )

    def test_duplicate_after_resolution_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'three distinct'):
            resolve_target_classes(
                ['apple', 'apple', 'banana'],
                self.classes,
                self.aliases,
            )

    def test_positive_group_number_is_required(self):
        self.assertEqual(parse_group_number('17'), 17)
        for invalid in ('0', '-1', '1.5', '', True):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, 'positive integer'):
                    parse_group_number(invalid)

    def test_exact_model_contract_is_accepted(self):
        model_names = dict(enumerate(self.classes))
        result = validate_model_contract(
            model_names,
            self.classes,
            ('apple', 'banana', 'beer'),
        )
        self.assertEqual(result, self.classes)

    def test_reordered_or_incomplete_model_is_rejected(self):
        reordered = list(self.classes)
        reordered[0], reordered[1] = reordered[1], reordered[0]
        with self.assertRaisesRegex(ValueError, 'official manifest'):
            validate_model_contract(
                reordered,
                self.classes,
                ('apple', 'banana', 'beer'),
            )
        with self.assertRaisesRegex(ValueError, 'official manifest'):
            validate_model_contract(
                self.classes[:-1],
                self.classes,
                ('apple', 'banana', 'beer'),
            )

    def test_objects_only_answer_is_validated_and_counted(self):
        targets = ('apple', 'banana', 'beer')
        document = {
            'objects': {
                'apple': [{'x': 1.0, 'y': 2.0}],
                'banana': [],
                'beer': [
                    {'x': 3, 'y': 4},
                    {'x': 5.0, 'y': 6.0},
                ],
            }
        }
        self.assertEqual(
            validate_answer_document(document, targets),
            {'apple': 1, 'banana': 0, 'beer': 2},
        )

    def test_answer_with_wrong_keys_or_nonfinite_value_is_rejected(self):
        targets = ('apple', 'banana', 'beer')
        with self.assertRaisesRegex(ValueError, 'exactly the objects'):
            validate_answer_document(
                {'corners': {}, 'objects': {}},
                targets,
            )
        with self.assertRaisesRegex(ValueError, 'must be finite'):
            validate_answer_document({
                'objects': {
                    'apple': [{'x': float('nan'), 'y': 0.0}],
                    'banana': [],
                    'beer': [],
                }
            }, targets)

    def test_p2_observation_plan_is_small_explicit_and_finite(self):
        plan = parse_observation_plan(
            '[{"x":-2.085,"y":-2.415,"yaw":1.533}]'
        )
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["x"], -2.085)
        for invalid in (
            '[]',
            '[{"x":0,"y":0}]',
            '[{"x":0,"y":0,"yaw":NaN}]',
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    parse_observation_plan(invalid)


if __name__ == '__main__':
    unittest.main()
