#!/usr/bin/env python3
"""Wait until the expected Gazebo Fortress world creation service is ready."""

import argparse
import re
import subprocess
import sys
import time


POLL_PERIOD = 0.2
TIMEOUT = 90.0
WORLD_NAME_PATTERN = re.compile(r'^[A-Za-z0-9_.-]+$')


def parse_arguments(arguments=None):
    """Parse and validate the world service namespace."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--world-name', default='robocup_home')
    parsed = parser.parse_args(arguments)
    if WORLD_NAME_PATTERN.fullmatch(parsed.world_name) is None:
        parser.error(
            'world name may contain only letters, digits, underscore, dot, '
            'or hyphen'
        )
    return parsed


def service_is_ready(create_service):
    """Return whether the exact Gazebo Transport service is discoverable."""
    try:
        result = subprocess.run(
            ['ign', 'service', '-l'],
            check=False,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

    if result.returncode != 0:
        return False
    return create_service in {line.strip() for line in result.stdout.splitlines()}


def main(arguments=None):
    """Poll observable readiness instead of relying on a fixed startup delay."""
    parsed = parse_arguments(arguments)
    create_service = f'/world/{parsed.world_name}/create'
    print(f'[world_ready] Waiting for {create_service}', flush=True)
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        if service_is_ready(create_service):
            print(
                f'[world_ready] Gazebo service is ready: {create_service}',
                flush=True,
            )
            return 0
        time.sleep(POLL_PERIOD)

    print(
        f'[world_ready] Service unavailable after {TIMEOUT:.0f}s: '
        f'{create_service}',
        file=sys.stderr,
        flush=True,
    )
    return 1


if __name__ == '__main__':
    sys.exit(main())
