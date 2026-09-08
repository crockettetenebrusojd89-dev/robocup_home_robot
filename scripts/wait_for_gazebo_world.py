#!/usr/bin/env python3
"""Wait until the expected Gazebo Fortress world creation service is ready."""

import subprocess
import sys
import time


CREATE_SERVICE = '/world/robocup_home/create'
POLL_PERIOD = 0.2
TIMEOUT = 90.0


def service_is_ready():
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
    return CREATE_SERVICE in {line.strip() for line in result.stdout.splitlines()}


def main():
    """Poll observable readiness instead of relying on a fixed startup delay."""
    print(f'[world_ready] Waiting for {CREATE_SERVICE}', flush=True)
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        if service_is_ready():
            print(f'[world_ready] Gazebo service is ready: {CREATE_SERVICE}', flush=True)
            return 0
        time.sleep(POLL_PERIOD)

    print(
        f'[world_ready] Service unavailable after {TIMEOUT:.0f}s: {CREATE_SERVICE}',
        file=sys.stderr,
        flush=True,
    )
    return 1


if __name__ == '__main__':
    sys.exit(main())
