"""Isolated single-platform AMCL/Nav2 stack; lifecycle activation is explicit."""
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import AppendEnvironmentVariable,ExecuteProcess
from launch_ros.actions import Node


def generate_launch_description():
    root=Path(__file__).resolve().parent
    share=Path(get_package_share_directory('nav2_minimal_tb3_sim'))
    common=[('/tf','tf'),('/tf_static','tf_static')]
    actions=[AppendEnvironmentVariable('GZ_SIM_RESOURCE_PATH',str(share/'models')),
        AppendEnvironmentVariable('GZ_SIM_RESOURCE_PATH',str(share.parent)),
        ExecuteProcess(cmd=['gz','sim','-r','-s','--headless-rendering','-v','2',str(root/'worlds/nav_calibration.sdf')],output='screen'),
        ExecuteProcess(cmd=['gz','sim','-g','-v','2','--gui-config',str(root/'config/nav_gui.config')],output='screen'),
        Node(package='ros_gz_bridge',executable='parameter_bridge',name='bridge',
            parameters=[{'config_file':str(root/'config/nav_bridge.yaml'),'use_sim_time':True}])]
    actions.extend(ground_nodes(root,'B1'))
    return LaunchDescription(actions)


def ground_nodes(root,actor):
    common=[('/tf','tf'),('/tf_static','tf_static')]
    actions=[Node(package='robot_state_publisher',executable='robot_state_publisher',namespace=actor,
            parameters=[{'robot_description':(root/'assets/waffle.urdf').read_text(),
                'frame_prefix':actor+'/','use_sim_time':True}],remappings=common)]
    servers=[('nav2_map_server','map_server'),('nav2_amcl','amcl'),
        ('nav2_controller','controller_server'),('nav2_planner','planner_server'),
        ('nav2_behaviors','behavior_server'),('nav2_velocity_smoother','velocity_smoother'),
        ('nav2_collision_monitor','collision_monitor'),('nav2_bt_navigator','bt_navigator')]
    for package,executable in servers:
        remaps=list(common)
        if executable in ('controller_server','behavior_server','velocity_smoother'):
            remaps.append(('cmd_vel','cmd_vel_nav'))
        actions.append(Node(package=package,executable=executable,name=executable,namespace=actor,
            parameters=[str(root/f'config/nav2_{actor}.yaml'),{'use_sim_time':True}],
            remappings=remaps,output='screen'))
    for name,nodes in (('localization',['map_server','amcl']),
            ('navigation',[n for _,n in servers[2:]])):
        actions.append(Node(package='nav2_lifecycle_manager',executable='lifecycle_manager',
            name='lifecycle_manager_'+name,namespace=actor,parameters=[{'autostart':False,
                'use_sim_time':True,'node_names':nodes,'bond_timeout':30.}],output='screen'))
    return actions
