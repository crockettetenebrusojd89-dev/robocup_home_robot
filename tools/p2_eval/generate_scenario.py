#!/usr/bin/env python3
"""Generate one reproducible P2 world and its isolated evaluation evidence."""

import argparse
from pathlib import Path
import sys

from p2_eval_core import EvaluationConfigError, generate_trial


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-world", required=True, type=Path)
    parser.add_argument("--table-config", required=True, type=Path)
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--class-manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        paths = generate_trial(
            args.base_world,
            args.table_config,
            args.scenario,
            args.class_manifest,
            args.output_dir,
        )
    except EvaluationConfigError as error:
        print(f"scenario generation failed: {error}", file=sys.stderr)
        return 1
    for name, path in paths.items():
        print(f"{name}: {path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
