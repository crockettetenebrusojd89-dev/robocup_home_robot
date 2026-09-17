#!/usr/bin/env python3
"""Create a disposable four-object dining scene for Advanced Stage 1."""

import argparse
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


DINING_OBJECTS = (
    {
        'class_name': 'apple',
        'instance_name': 'stage1_dining_apple',
        'x': 1.45,
        'y': 1.55,
        'z': 0.78,
        'yaw': 0.35,
    },
    {
        'class_name': 'coke_can',
        'instance_name': 'stage1_dining_coke_can',
        'x': 1.85,
        'y': 1.93,
        'z': 0.78,
        'yaw': -0.45,
    },
    {
        'class_name': 'mustard_bottle',
        'instance_name': 'stage1_dining_mustard_bottle',
        'x': 2.50,
        'y': 1.55,
        'z': 0.78,
        'yaw': 0.20,
    },
    {
        'class_name': 'master_chef_can',
        'instance_name': 'stage1_dining_master_chef_can',
        'x': 2.95,
        'y': 1.93,
        'z': 0.78,
        'yaw': -0.70,
    },
)


def create_dining_world(source_world, output_world):
    """Copy a household world while replacing only formal object includes."""
    source_world = Path(source_world)
    output_world = Path(output_world)
    tree = ET.parse(source_world)
    world = tree.getroot().find('world')
    if world is None:
        raise ValueError('source world has no top-level world element')

    class_names = {item['class_name'] for item in DINING_OBJECTS}
    formal_classes = {
        'apple', 'banana', 'beer', 'bleach_cleanser', 'bowl', 'chips_can',
        'coke_can', 'cracker_box', 'gelatin_box', 'master_chef_can',
        'mustard_bottle', 'pitcher_base', 'potted_meat_can', 'pudding_box',
        'sugar_box', 'tomato_soup_can', 'tuna_fish_can', 'windex_bottle',
    }
    for include in list(world.findall('include')):
        uri = (include.findtext('uri') or '').strip()
        if uri.rsplit('/', 1)[-1] in formal_classes:
            world.remove(include)

    for item in DINING_OBJECTS:
        include = ET.SubElement(world, 'include')
        ET.SubElement(include, 'uri').text = f"model://{item['class_name']}"
        ET.SubElement(include, 'name').text = item['instance_name']
        ET.SubElement(include, 'static').text = 'true'
        ET.SubElement(include, 'pose').text = (
            f"{item['x']:.3f} {item['y']:.3f} {item['z']:.3f} "
            f"0 0 {item['yaw']:.3f}"
        )

    output_world.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_world, encoding='utf-8', xml_declaration=True)
    return {
        'source_world': str(source_world.resolve()),
        'output_world': str(output_world.resolve()),
        'objects': [dict(item) for item in DINING_OBJECTS],
        'note': (
            'The four poses are on the 0.78 m dining-table surface: one '
            'object per normal-height dining table quadrant.'
        ),
    }


def parse_arguments(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-world', type=Path, required=True)
    parser.add_argument('--output-world', type=Path, required=True)
    return parser.parse_args(arguments)


def main(arguments=None):
    args = parse_arguments(arguments)
    if args.source_world.suffix != '.world' or not args.source_world.is_file():
        print('source world must be an existing .world file', file=sys.stderr)
        return 2
    if args.output_world.suffix != '.world':
        print('output world must end in .world', file=sys.stderr)
        return 2
    try:
        metadata = create_dining_world(args.source_world, args.output_world)
    except (OSError, ET.ParseError, ValueError) as error:
        print(f'could not generate dining validation world: {error}', file=sys.stderr)
        return 1
    print(json.dumps(metadata, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
