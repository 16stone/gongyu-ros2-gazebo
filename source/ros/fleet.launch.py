"""Configured isolated localization/navigation stacks; activation remains explicit."""
import importlib.util
import json
import os
from pathlib import Path
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import AppendEnvironmentVariable,ExecuteProcess
from launch_ros.actions import Node


def generate_launch_description():
    source=Path(__file__).resolve().parent;root=Path(os.environ['GONGYU_FLEET_SCENE']).resolve()
    spec=importlib.util.spec_from_file_location('calibration_launch',source/'nav_calibration.launch.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    share=Path(get_package_share_directory('nav2_minimal_tb3_sim'))
    actions=[AppendEnvironmentVariable('GZ_SIM_RESOURCE_PATH',str(share/'models')),
        AppendEnvironmentVariable('GZ_SIM_RESOURCE_PATH',str(share.parent)),
        ExecuteProcess(cmd=['gz','sim','-r','-s','--headless-rendering','-v','2',str(root/'worlds/fleet.sdf')],output='screen'),
        Node(package='ros_gz_bridge',executable='parameter_bridge',name='fleet_bridge',
            parameters=[{'config_file':str(root/'config/fleet_bridge.yaml'),'use_sim_time':True}])]
    if os.environ.get('GONGYU_HEADLESS') != '1':
        actions.insert(3, ExecuteProcess(cmd=['gz','sim','-g','--gui-config',str(root/'config/nav_gui.config' if (root/'config/nav_gui.config').exists() else source/'config/nav_gui.config')],output='screen'))
    selected=os.environ.get('GONGYU_ACTIVE_GROUND')
    for actor in json.loads((root/'config/fleet.json').read_text()):
        if actor['mode']=='ground' and (selected is None or actor['id'] in selected.split(',')):
            actions.extend(module.ground_nodes(root,actor['id']))
    return LaunchDescription(actions)
