"""Reuse the reference robot platform, while generating a new navigation scene."""
import hashlib
import json
import xml.etree.ElementTree as E
from pathlib import Path

import yaml


def reference_root():
    return Path('/mnt/c/Users/ZhuanZ/Documents/ChatGPT/无人系统导论/02_参考文档/优化拓展_20261027/source')


def prepare(out,reference):
    out=Path(out);reference=Path(reference)
    for folder in ('assets','worlds','config','maps'):
        (out/folder).mkdir(parents=True,exist_ok=True)
    source_model=reference/'assets/robots/waffle_robot1.sdf'
    text=source_model.read_text().replace('robot1','B1')
    robot=E.fromstring(text).find('model');robot.set('name','B1')
    robot.find('pose').text='0 2 0.01 0 0 0'
    for parent in robot.iter():
        for sensor in list(parent.findall('sensor')):
            if sensor.get('type')!='gpu_lidar':
                parent.remove(sensor)
    base=Path('/opt/ros/jazzy/opt/gz_sim_vendor/share/gz/gz-sim8/worlds/diff_drive.sdf')
    tree=E.parse(base);world=tree.getroot().find('world');world.set('name','gongyu_nav')
    world.find('physics/max_step_size').text='0.002'
    for model in list(world.findall('model')):
        if model.get('name')!='ground_plane':
            world.remove(model)
    plugin=E.SubElement(world,'plugin',filename='gz-sim-sensors-system',name='gz::sim::systems::Sensors')
    E.SubElement(plugin,'render_engine').text='ogre2'
    world.append(robot)
    boxes=[('west_wall',-3.,.5,.2,9.,1.5),('east_wall',7.,.5,.2,9.,1.5),
        ('south_wall',2.,-4.,10.,.2,1.5),('north_wall',2.,5.,10.,.2,1.5),
        ('detour_box',2.,2.,.8,1.4,1.)]
    rectangles=[]
    for name,x,y,sx,sy,height in boxes:
        model=E.SubElement(world,'model',name=name);E.SubElement(model,'static').text='true'
        E.SubElement(model,'pose').text=f'{x} {y} {height/2} 0 0 0'
        link=E.SubElement(model,'link',name='body')
        for kind in ('collision','visual'):
            element=E.SubElement(link,kind,name=kind)
            geometry=E.SubElement(element,'geometry')
            E.SubElement(E.SubElement(geometry,'box'),'size').text=f'{sx} {sy} {height}'
            if kind=='visual':
                material=E.SubElement(element,'material')
                color='0.85 0.35 0.12 1' if name=='detour_box' else '0.55 0.60 0.65 1'
                E.SubElement(material,'ambient').text=color
                E.SubElement(material,'diffuse').text=color
        rectangles.append([x-sx/2,y-sy/2,x+sx/2,y+sy/2])
    E.indent(tree);tree.write(out/'worlds/nav_calibration.sdf',encoding='utf-8',xml_declaration=True)
    resolution=.05;origin=(-3.2,-4.2);width,height=208,188
    grid=bytearray()
    for row in range(height):
        y=origin[1]+(height-row-.5)*resolution
        for col in range(width):
            x=origin[0]+(col+.5)*resolution
            grid.append(0 if any(a<=x<=c and b<=y<=d for a,b,c,d in rectangles) else 254)
    (out/'maps/nav_calibration.pgm').write_bytes(f'P5\n{width} {height}\n255\n'.encode()+grid)
    (out/'maps/nav_calibration.yaml').write_text(yaml.safe_dump({'image':'nav_calibration.pgm',
        'resolution':resolution,'origin':[*origin,0.],'negate':0,'occupied_thresh':.65,'free_thresh':.25}))
    params=yaml.safe_load((reference/'configs/nav2_robot1.yaml').read_text().replace('robot1','B1'))
    params['map_server']['ros__parameters']['yaml_filename']=str((out/'maps/nav_calibration.yaml').resolve())
    params['collision_monitor']['ros__parameters']['cmd_vel_out_topic']='cmd_vel'
    params['controller_server']['ros__parameters']['controller_frequency']=10.
    params['controller_server']['ros__parameters']['costmap_update_timeout']=1.
    params['controller_server']['ros__parameters']['FollowPath']['debug_trajectory_details']=False
    params['controller_server']['ros__parameters']['FollowPath']['vy_samples']=1
    params['controller_server']['ros__parameters']['FollowPath']['vx_samples']=10
    params['controller_server']['ros__parameters']['FollowPath']['vtheta_samples']=15
    for name in ('route_server','waypoint_follower','docking_server','smoother_server'):
        params.pop(name,None)
    for value in params.values():
        if isinstance(value,dict) and 'ros__parameters' in value:
            value['ros__parameters']['use_sim_time']=True
    (out/'config/nav2_B1.yaml').write_text(yaml.safe_dump({'B1':params},sort_keys=False))
    urdf=reference/'assets/robots/waffle_peer.urdf'
    (out/'assets/waffle.urdf').write_bytes(urdf.read_bytes())
    bridge=[]
    for ros_topic,gz_topic,ros_type,gz_type,direction in (
        ('/clock','/clock','rosgraph_msgs/msg/Clock','gz.msgs.Clock','GZ_TO_ROS'),
        ('/B1/odom','/B1/odom','nav_msgs/msg/Odometry','gz.msgs.Odometry','GZ_TO_ROS'),
        ('/B1/tf','/B1/tf','tf2_msgs/msg/TFMessage','gz.msgs.Pose_V','GZ_TO_ROS'),
        ('/B1/scan','/B1/scan','sensor_msgs/msg/LaserScan','gz.msgs.LaserScan','GZ_TO_ROS'),
        ('/B1/peer_scan','/B1/peer_scan','sensor_msgs/msg/LaserScan','gz.msgs.LaserScan','GZ_TO_ROS'),
        ('/B1/cmd_vel','/B1/cmd_vel','geometry_msgs/msg/Twist','gz.msgs.Twist','ROS_TO_GZ')):
        bridge.append(dict(ros_topic_name=ros_topic,gz_topic_name=gz_topic,ros_type_name=ros_type,
            gz_type_name=gz_type,direction=direction))
    (out/'config/nav_bridge.yaml').write_text(yaml.safe_dump(bridge,sort_keys=False))
    gui=base.parent.parent/'gui/gui.config'
    gui_text=gui.read_text().replace('<width>1000</width>','<width>1600</width>').replace(
        '<height>845</height>','<height>900</height>').replace(
        '<camera_pose>-6 0 6 0 0.5 0</camera_pose>','<camera_pose>2 2 6 0 1.57079632679 0</camera_pose>')
    (out/'config/nav_gui.config').write_text(gui_text)
    sources=[source_model,urdf,reference/'configs/nav2_robot1.yaml',base]
    receipt={'reference_root':str(reference),'reused':'robot platform/URDF and Nav2 parameter template only; no mission controller',
        'boxes':boxes,'map_origin':origin,'map_resolution':resolution,
        'source_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}}
    (out/'nav_sources.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt


if __name__=='__main__':
    prepare(Path(__file__).resolve().parent,reference_root())
