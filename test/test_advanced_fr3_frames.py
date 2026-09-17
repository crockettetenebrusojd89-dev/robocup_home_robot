#!/usr/bin/env python3

import math
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET


REPOSITORY = Path(__file__).resolve().parents[1]


class AdvancedFr3FramesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.robot = ET.parse(
            REPOSITORY / 'urdf' / 'mobile_manipulator.xacro'
        ).getroot()

    def test_base_link_to_fr3_link0_fixed_transform(self):
        child_to_joint = {}
        for joint in self.robot.findall('.//joint'):
            if joint.attrib.get('type') != 'fixed':
                continue
            child = joint.find('child').attrib['link']
            parent = joint.find('parent').attrib['link']
            origin = joint.find('origin')
            xyz = tuple(float(value) for value in origin.attrib['xyz'].split())
            rpy = tuple(float(value) for value in origin.attrib['rpy'].split())
            child_to_joint[child] = (parent, xyz, rpy)

        translation = [0.0, 0.0, 0.0]
        current = 'fr3_link0'
        while current != 'base_link':
            parent, xyz, rpy = child_to_joint[current]
            self.assertTrue(all(math.isclose(value, 0.0) for value in rpy))
            translation = [a + b for a, b in zip(translation, xyz)]
            current = parent

        expected = (-0.09, 0.055, 0.425)
        for actual, wanted in zip(translation, expected):
            self.assertAlmostEqual(actual, wanted, places=9)

    def test_moveit_chain_and_tcp_match_integrated_robot(self):
        semantic = ET.parse(REPOSITORY / 'config' / 'mobile_fr3.srdf').getroot()
        group = semantic.find("group[@name='fr3_arm']")
        self.assertIsNotNone(group)
        chain = group.find('chain')
        self.assertEqual(chain.attrib['base_link'], 'fr3_link0')
        self.assertEqual(chain.attrib['tip_link'], 'fr3_hand_tcp')
        end_effector = semantic.find("end_effector[@name='fr3_hand']")
        self.assertEqual(end_effector.attrib['parent_link'], 'fr3_hand_tcp')


if __name__ == '__main__':
    unittest.main()
