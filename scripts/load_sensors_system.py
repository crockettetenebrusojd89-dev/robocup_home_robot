#!/usr/bin/env python3
"""Load the Gazebo Fortress sensor systems required by this robot."""

import subprocess
import sys
import time


WORLD_NAME = 'robocup_home'
SYSTEM_ADD_SERVICE = f'/world/{WORLD_NAME}/entity/system/add'
SCAN_TOPIC = '/scan'
IMU_TOPIC = '/imu'
POLL_PERIOD = 0.2
SERVICE_TIMEOUT = 60.0
EXISTING_TOPIC_TIMEOUT = 5.0
NEW_TOPIC_TIMEOUT = 30.0


def run_ign(arguments, timeout=5.0):
    """Run an Ignition CLI command without invoking a shell."""
    try:
        return subprocess.run(
            ['ign', *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        print(f'[sensors_loader] Ignition command failed: {error}', file=sys.stderr)
        return None


def listing_contains(arguments, expected):
    """Return true when an exact entry appears in an Ignition listing."""
    result = run_ign(arguments)
    if result is None or result.returncode != 0:
        return False
    return expected in {line.strip() for line in result.stdout.splitlines()}


def wait_until(predicate, timeout):
    """Poll an observable condition until it succeeds or times out."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(POLL_PERIOD)
    return False


def topic_available(topic):
    """Check for an exact Gazebo Transport topic."""
    return listing_contains(['topic', '-l'], topic)


def load_system(filename, name, innerxml=None):
    """Add one world system through Gazebo's runtime service."""
    plugin_fields = (
        f'filename: "{filename}", '
        f'name: "{name}"'
    )
    if innerxml is not None:
        plugin_fields += f', innerxml: "{innerxml}"'

    request = (
        f'entity: {{name: "{WORLD_NAME}", type: 9}} '
        f'plugins: {{{plugin_fields}}}'
    )
    result = run_ign([
        'service',
        '-s', SYSTEM_ADD_SERVICE,
        '--reqtype', 'ignition.msgs.EntityPlugin_V',
        '--reptype', 'ignition.msgs.Boolean',
        '--timeout', '5000',
        '--req', request,
    ], timeout=10.0)

    if result is None:
        return False
    response = f'{result.stdout}\n{result.stderr}'.strip()
    if result.returncode != 0 or 'data: true' not in response:
        print(
            f'[sensors_loader] Failed to load {name}:\n{response}',
            file=sys.stderr,
        )
        return False
    return True


def main():
    """Wait for Gazebo and add each missing sensor system exactly once."""
    print(f'[sensors_loader] Waiting for {SYSTEM_ADD_SERVICE}')
    service_ready = wait_until(
        lambda: listing_contains(['service', '-l'], SYSTEM_ADD_SERVICE),
        SERVICE_TIMEOUT,
    )
    if not service_ready:
        print(
            f'[sensors_loader] Service unavailable after {SERVICE_TIMEOUT:.0f}s: '
            f'{SYSTEM_ADD_SERVICE}',
            file=sys.stderr,
        )
        return 1

    # The loader starts after the spawn process exits. If /scan appears, the
    # world already has a working Sensors system and loading another is unsafe.
    if wait_until(lambda: topic_available(SCAN_TOPIC), EXISTING_TOPIC_TIMEOUT):
        print('[sensors_loader] /scan already exists; Sensors system not reloaded')
    else:
        loaded = load_system(
            'ignition-gazebo-sensors-system',
            'ignition::gazebo::systems::Sensors',
            '<render_engine>ogre2</render_engine>',
        )
        if not loaded:
            return 1
        print('[sensors_loader] Sensors system loaded with Ogre2')
        if not wait_until(
            lambda: topic_available(SCAN_TOPIC),
            NEW_TOPIC_TIMEOUT,
        ):
            print(
                f'[sensors_loader] Sensors loaded, but {SCAN_TOPIC} did not '
                f'appear within {NEW_TOPIC_TIMEOUT:.0f}s',
                file=sys.stderr,
            )
            return 1
        print(f'[sensors_loader] Gazebo topic is available: {SCAN_TOPIC}')

    # Fortress processes non-rendering IMU sensors with a separate world
    # system. The same topic guard prevents duplicate loading on relaunch.
    if wait_until(lambda: topic_available(IMU_TOPIC), EXISTING_TOPIC_TIMEOUT):
        print('[sensors_loader] /imu already exists; Imu system not reloaded')
        return 0

    loaded = load_system(
        'ignition-gazebo-imu-system',
        'gz::sim::systems::Imu',
    )
    if not loaded:
        return 1
    print('[sensors_loader] Imu system loaded')
    if not wait_until(lambda: topic_available(IMU_TOPIC), NEW_TOPIC_TIMEOUT):
        print(
            f'[sensors_loader] Imu loaded, but {IMU_TOPIC} did not appear '
            f'within {NEW_TOPIC_TIMEOUT:.0f}s',
            file=sys.stderr,
        )
        return 1

    print(f'[sensors_loader] Gazebo topic is available: {IMU_TOPIC}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
