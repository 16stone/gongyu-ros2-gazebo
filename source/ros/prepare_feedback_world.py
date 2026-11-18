"""Build a local one-car/one-aircraft world from the installed official examples."""
import copy
import hashlib
import json
import xml.etree.ElementTree as E
from pathlib import Path

root=Path(__file__).resolve().parents[1]
examples=Path('/opt/ros/jazzy/opt/gz_sim_vendor/share/gz/gz-sim8/worlds')
asset=root/'ros/models/X3_UAV_v4'
tree=E.parse(examples/'multicopter_velocity_control.sdf');world=tree.getroot().find('world')
world.set('name','gongyu_feedback')
world.find('physics/max_step_size').text='0.002'
for plugin in list(world.findall('plugin')):
    if plugin.get('name').endswith('Sensors'):
        world.remove(plugin)
includes=world.findall('include');plugins=includes[0].findall('plugin')
for include in includes:
    world.remove(include)
air=E.parse(asset/'model.sdf').getroot().find('model');air.set('name','B3')
air.find('pose').text='0 -2 0.06 0 0 0'
for uri in air.findall('.//mesh/uri'):
    if uri.text.startswith('model://x3/'):
        uri.text=str(asset/uri.text.removeprefix('model://x3/'))
for material in air.findall('.//material'):
    for script in material.findall('script'):
        material.remove(script)
        E.SubElement(material,'ambient').text='0.2 0.2 0.2 1'
for plugin in plugins:
    plugin=copy.deepcopy(plugin)
    ns=plugin.find('robotNamespace')
    if ns is not None:
        ns.text='B3'
    if plugin.get('name').endswith('OdometryPublisher'):
        E.SubElement(plugin,'odom_topic').text='/B3/odometry'
    air.append(plugin)
world.append(air)
ground=E.parse(examples/'diff_drive.sdf').find('.//model[@name="vehicle_blue"]')
ground.set('name','B1')
ground.find('plugin/odom_publish_frequency').text='50'
E.SubElement(ground.find('plugin'),'topic').text='/B1/cmd_vel'
world.append(ground)
assert len([m for m in world.findall('model') if m.find('static') is None])==2
assert len(air.findall('plugin[@name="gz::sim::systems::MulticopterMotorModel"]'))==4
assert len(air.findall('plugin[@name="gz::sim::systems::MulticopterVelocityControl"]'))==1
assert all(Path(u.text).is_file() for u in air.findall('.//mesh/uri'))
out=root/'ros/worlds/feedback.sdf';out.parent.mkdir(parents=True,exist_ok=True)
E.indent(tree);tree.write(out,encoding='utf-8',xml_declaration=True)
files=[examples/'multicopter_velocity_control.sdf',examples/'diff_drive.sdf',asset/'model.sdf',asset/'model.config',out]
receipt={'gazebo_version':'8.15.0','source_model_url':'https://fuel.gazebosim.org/1.0/OpenRobotics/models/X3%20UAV/4/X3%20UAV.zip',
    'source_zip_sha256':'c995a307936ce7df5a544e6c89b0396d054befa6ff5fbdbf262949b59cc12247',
    'changes':['one X3 aircraft and one blue differential-drive vehicle; removed X4',
        'B1/B3 topics; 2ms physics step; local mesh paths; legacy material scripts replaced by simple color'],
    'sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
(root/'evidence/phase04_setup/world_sources.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(out)
