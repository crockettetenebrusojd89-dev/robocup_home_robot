#!/usr/bin/env python3
"""Convert Xacro to SDF with matching passive references and initial poses."""

import argparse
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


STOWED_JOINTS = {
    'fr3_joint1': -0.68,
    'fr3_joint2': 0.29,
    'fr3_joint3': -0.26,
    'fr3_joint4': -2.91,
    'fr3_joint5': 0.75,
    'fr3_joint6': 1.03,
    'fr3_joint7': 2.00,
}


def _run(command):
    return subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout


def _passive_references(urdf_root):
    references = {}
    for gazebo in urdf_root.findall('gazebo'):
        joint_name = gazebo.get('reference', '')
        spring_reference = gazebo.find('springReference')
        if joint_name.startswith('fr3_') and spring_reference is not None:
            references[joint_name] = spring_reference.text.strip()
    return references


def _seed_child_pose(joint, child_link, reference):
    """Make the pre-physics link pose agree with a joint initial position."""
    joint_type = joint.get('type')
    pose = child_link.find('pose')
    axis = joint.find('axis/xyz')
    if pose is None or pose.get('relative_to') != joint.get('name'):
        raise RuntimeError(
            f'SDF child link {child_link.get("name")} has an unexpected pose frame'
        )
    if axis is None:
        raise RuntimeError(f'SDF joint {joint.get("name")} has no axis vector')

    pose_values = [float(value) for value in pose.text.split()]
    axis_values = [float(value) for value in axis.text.split()]
    if len(pose_values) != 6 or len(axis_values) != 3:
        raise RuntimeError(f'Unexpected SDF pose or axis for {joint.get("name")}')

    position = float(reference)
    if joint_type == 'revolute':
        if pose_values != [0.0] * 6 or axis_values != [0.0, 0.0, 1.0]:
            raise RuntimeError(
                f'Unsupported non-canonical revolute joint {joint.get("name")}'
            )
        pose.text = f'0 0 0 0 0 {position}'
    elif joint_type == 'prismatic':
        if position != 0.0:
            raise RuntimeError(
                f'Unsupported nonzero prismatic joint {joint.get("name")}'
            )
    else:
        raise RuntimeError(
            f'Unsupported initial-position joint type {joint_type!r}'
        )

    dynamics = joint.find('axis/dynamics')
    spring_reference = None if dynamics is None else dynamics.find(
        'spring_reference'
    )
    if spring_reference is None:
        raise RuntimeError(f'SDF joint {joint.get("name")} has no passive spring')
    spring_reference.text = '0'

    if joint_type == 'revolute':
        lower = joint.find('axis/limit/lower')
        upper = joint.find('axis/limit/upper')
        if lower is None or upper is None:
            raise RuntimeError(f'SDF joint {joint.get("name")} has no limits')
        lower.text = str(float(lower.text) - position)
        upper.text = str(float(upper.text) - position)


def _set_control_initial_positions(urdf_root):
    updated = set()
    for joint in urdf_root.findall('./ros2_control/joint'):
        name = joint.get('name', '')
        if name not in STOWED_JOINTS:
            continue
        initial = joint.find(
            "state_interface[@name='position']/param[@name='initial_value']"
        )
        if initial is None:
            raise RuntimeError(
                f'ros2_control joint {name} has no position initial_value'
            )
        initial.text = str(STOWED_JOINTS[name])
        updated.add(name)
    missing = sorted(set(STOWED_JOINTS) - updated)
    if missing:
        raise RuntimeError('Missing controlled FR3 joints: ' + ', '.join(missing))


def generate_spawn_sdf(xacro_path, arm_control=False, controller_config=''):
    """Return SDF whose initial link poses match the passive references."""
    command = ['xacro', xacro_path]
    if arm_control:
        command.extend([
            'arm_control:=true',
            f'controller_config:={controller_config}',
        ])
    urdf_text = _run(command)
    urdf_root = ET.fromstring(urdf_text)
    if arm_control:
        _set_control_initial_positions(urdf_root)
    references = _passive_references(urdf_root)
    if not references and not arm_control:
        raise RuntimeError('No FR3 passive joint references were found in the Xacro')

    with tempfile.NamedTemporaryFile(suffix='.urdf') as urdf_file:
        urdf_file.write(urdf_text.encode('utf-8'))
        urdf_file.flush()
        sdf_text = _run(['ign', 'sdf', '-p', urdf_file.name])

    sdf_root = ET.fromstring(sdf_text)
    sdf_joints = {
        joint.get('name'): joint
        for joint in sdf_root.findall('./model/joint')
    }
    sdf_links = {
        link.get('name'): link
        for link in sdf_root.findall('./model/link')
    }
    missing = sorted(set(references) - set(sdf_joints))
    if missing:
        raise RuntimeError(
            'Converted SDF is missing referenced joints: ' + ', '.join(missing)
        )

    for joint_name, reference in references.items():
        axis = sdf_joints[joint_name].find('axis')
        if axis is None:
            raise RuntimeError(f'SDF joint {joint_name} has no axis element')
        child_name = sdf_joints[joint_name].findtext('child')
        child_link = sdf_links.get(child_name)
        if child_link is None:
            raise RuntimeError(
                f'SDF joint {joint_name} has no child link {child_name!r}'
            )
        _seed_child_pose(sdf_joints[joint_name], child_link, reference)

    return ET.tostring(sdf_root, encoding='unicode')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('xacro_file')
    parser.add_argument('--arm-control', action='store_true')
    parser.add_argument('--controller-config', default='')
    args = parser.parse_args()
    try:
        if args.arm_control and not args.controller_config:
            raise RuntimeError('--controller-config is required with --arm-control')
        sys.stdout.write(generate_spawn_sdf(
            args.xacro_file,
            arm_control=args.arm_control,
            controller_config=args.controller_config,
        ))
    except (OSError, ET.ParseError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(f'Failed to generate spawn SDF: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
