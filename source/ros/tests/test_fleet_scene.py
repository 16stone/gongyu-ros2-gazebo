import importlib.util
import tempfile
import unittest
import xml.etree.ElementTree as E
import yaml
from pathlib import Path


class FleetScene(unittest.TestCase):
    def test_four_namespaced_navigation_platforms_and_two_real_rotorcraft(self):
        root=Path(__file__).resolve().parents[1]
        spec=importlib.util.spec_from_file_location('fleet_scene',root/'prepare_fleet_world.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            module.prepare(Path(directory),root)
            world=E.parse(Path(directory)/'worlds/fleet.sdf').getroot().find('world')
            for actor in ('B1','B2','R1','R2','B3','R5'):
                model=world.find(f'model[@name="{actor}"]');self.assertIsNotNone(model)
                if actor in ('B3','R5'):
                    self.assertEqual(len(model.findall('plugin[@name="gz::sim::systems::MulticopterMotorModel"]')),4)
                    self.assertEqual(model.find('plugin[@name="gz::sim::systems::MulticopterVelocityControl"]/robotNamespace').text,actor)
                else:
                    self.assertTrue((Path(directory)/f'config/nav2_{actor}.yaml').is_file())
                    self.assertIn('/'+actor+'/',E.tostring(model).decode())
                    config=yaml.safe_load((Path(directory)/f'config/nav2_{actor}.yaml').read_text())
                    self.assertEqual(config[actor]['map_server']['ros__parameters']['yaml_filename'],
                                     str(Path(directory).resolve()/'maps/nav_calibration.yaml'))


if __name__=='__main__':unittest.main()
