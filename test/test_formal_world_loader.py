#!/usr/bin/env python3
"""Deterministic checks for competition-world launch boundaries."""

from contextlib import redirect_stderr
import importlib.util
from io import StringIO
from pathlib import Path
import tempfile
import unittest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def load_module(name, relative_path):
    """Load one repository script without requiring an installed package."""
    spec = importlib.util.spec_from_file_location(
        name,
        PACKAGE_ROOT / relative_path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


navigation = load_module('navigation_launch', 'launch/navigation.launch.py')
world_wait = load_module(
    'wait_for_gazebo_world',
    'scripts/wait_for_gazebo_world.py',
)
sensors = load_module(
    'load_sensors_system',
    'scripts/load_sensors_system.py',
)


class TestFormalWorldLoader(unittest.TestCase):
    """Keep path selection independent of scene contents and object truth."""

    def test_empty_world_file_keeps_example_default(self):
        self.assertIsNone(navigation._resolve_world_file('  '))

    def test_existing_world_path_is_resolved_without_content_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            world_path = Path(directory) / 'teacher formal.world'
            world_path.write_text('not parsed by launcher', encoding='utf-8')

            result = navigation._resolve_world_file(str(world_path))

            self.assertEqual(result, world_path.resolve())

    def test_missing_world_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, 'does not exist'):
            navigation._resolve_world_file('/tmp/absent_competition.world')

    def test_non_world_extension_fails_closed(self):
        with tempfile.NamedTemporaryFile(suffix='.sdf') as temporary:
            with self.assertRaisesRegex(RuntimeError, 'must end in .world'):
                navigation._resolve_world_file(temporary.name)

    def test_competition_world_uses_managed_server_only(self):
        self.assertEqual(
            navigation._gazebo_command(Path('/tmp/formal.world')),
            [
                'ign',
                'gazebo',
                '-r',
                '-s',
                '-v',
                '2',
                '/tmp/formal.world',
                '--force-version',
                '6',
            ],
        )

    def test_world_name_is_validated_by_service_helpers(self):
        self.assertEqual(
            world_wait.parse_arguments(['--world-name', 'robocup_home']).world_name,
            'robocup_home',
        )
        self.assertEqual(
            sensors.parse_arguments(['--world-name', 'formal-2026']).world_name,
            'formal-2026',
        )
        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                world_wait.parse_arguments(['--world-name', '../unsafe'])
            with self.assertRaises(SystemExit):
                sensors.parse_arguments(['--world-name', 'two words'])


if __name__ == '__main__':
    unittest.main()
