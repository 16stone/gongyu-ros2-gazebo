import tempfile
import unittest
import xml.etree.ElementTree as E
from pathlib import Path

import yaml

from ros.prepare_nav_world import prepare,reference_root


class NavScene(unittest.TestCase):
    def test_generated_map_and_world_share_obstacles_and_b1_interfaces(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            prepare(root,reference_root())
            world=E.parse(root/'worlds/nav_calibration.sdf').find('world')
            robot=world.find('model[@name="B1"]')
            self.assertIsNotNone(robot.find('.//sensor[@name="hls_lfcd_lds"]'))
            self.assertEqual(robot.find('.//sensor[@name="hls_lfcd_lds"]/topic').text,'/B1/scan')
            self.assertEqual(robot.find('plugin[@name="gz::sim::systems::DiffDrive"]/topic').text,'/B1/cmd_vel')
            self.assertIsNotNone(world.find('model[@name="detour_box"]'))
            params=yaml.safe_load((root/'config/nav2_B1.yaml').read_text())['B1']
            self.assertEqual(params['amcl']['ros__parameters']['base_frame_id'],'B1/base_footprint')
            self.assertEqual(params['collision_monitor']['ros__parameters']['cmd_vel_out_topic'],'cmd_vel')
            grid=(root/'maps/nav_calibration.pgm').read_bytes()
            self.assertTrue(grid.startswith(b'P5\n'))
            self.assertIn(0,grid.split(b'\n',3)[3])
            self.assertIn(254,grid.split(b'\n',3)[3])


if __name__=='__main__':
    unittest.main()
