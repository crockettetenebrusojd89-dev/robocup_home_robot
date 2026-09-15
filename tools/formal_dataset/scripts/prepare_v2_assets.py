#!/usr/bin/env python3
"""Create an immutable V2 model root while preserving all V1 assets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

from v2_common import SCHEMA_VERSION, build_asset_manifest, sha256_file


DEFAULT_SOURCE = Path.home() / "robocup_assets" / "official_models"
DEFAULT_BEER_ZIP = Path.home() / "Downloads" / "beer.zip"
DEFAULT_OUTPUT = Path.home() / "robocup_assets" / "official_models_v2"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--beer-zip", type=Path, default=DEFAULT_BEER_ZIP)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).resolve().parents[1] / "classes.json")
    return parser.parse_args()


def _class_names(path: Path) -> list[str]:
    document = json.loads(path.read_text(encoding="utf-8"))
    return [item["name"] for item in document["classes"]]


def _safe_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    if not members:
        raise ValueError("beer archive is empty")
    for member in members:
        path = Path(member.filename)
        if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "beer":
            raise ValueError(f"unsafe or unexpected beer archive member: {member.filename}")
    return members


def prepare(source: Path, beer_zip: Path, output: Path, class_names: list[str]) -> dict:
    source = source.expanduser().resolve()
    beer_zip = beer_zip.expanduser().resolve()
    output = output.expanduser().resolve()
    if not source.is_dir():
        raise FileNotFoundError(source)
    if not beer_zip.is_file():
        raise FileNotFoundError(beer_zip)
    if output.exists():
        raise FileExistsError(f"refusing to reuse V2 asset path: {output}")
    for name in class_names:
        if not (source / name).is_dir():
            raise FileNotFoundError(source / name)

    with tempfile.TemporaryDirectory(prefix="formal_v2_assets_", dir=output.parent) as temporary:
        staging = Path(temporary) / "official_models_v2"
        shutil.copytree(source, staging)
        with zipfile.ZipFile(beer_zip) as archive:
            members = _safe_members(archive)
            extracted = Path(temporary) / "teacher_release"
            archive.extractall(extracted, members)
        new_beer = extracted / "beer"
        sdf_path = new_beer / "model.sdf"
        texture_path = new_beer / "materials" / "textures" / "beer.png"
        sdf = sdf_path.read_text(encoding="utf-8")
        for token in ("<sdf version=\"1.6\">", "<pbr>", "<albedo_map>", "beer.png"):
            if token not in sdf:
                raise ValueError(f"teacher beer model.sdf is missing {token}")
        if not texture_path.is_file():
            raise FileNotFoundError(texture_path)

        shutil.rmtree(staging / "beer")
        shutil.copytree(new_beer, staging / "beer")
        asset_manifest = build_asset_manifest(staging, class_names)
        provenance = {
            "schema_version": SCHEMA_VERSION,
            "source_v1_root": str(source),
            "teacher_beer_archive": str(beer_zip),
            "teacher_beer_archive_sha256": sha256_file(beer_zip),
            "beer_model_sdf_sha256": sha256_file(staging / "beer" / "model.sdf"),
            "beer_texture_sha256": sha256_file(staging / "beer" / "materials" / "textures" / "beer.png"),
            "classes": {
                name: {"tree_sha256": value["tree_sha256"]}
                for name, value in asset_manifest["classes"].items()
            },
        }
        (staging / "asset_provenance.json").write_text(
            json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
        )
        staging.rename(output)
    return provenance


def main() -> int:
    args = parse_args()
    provenance = prepare(
        args.source, args.beer_zip, args.output, _class_names(args.manifest.expanduser().resolve())
    )
    print(f"ASSETS_READY {args.output.expanduser().resolve()}")
    print(f"BEER_MODEL_SHA256 {provenance['beer_model_sdf_sha256']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
