"""Clone the calibrated platforms into an isolated six-entity startup scene."""
import argparse
import copy
import json
import re
import shutil
import xml.etree.ElementTree as E
from pathlib import Path
import yaml

FLEET=[('B1','ground',(-1,1,.01)),('B2','ground',(-1,-1,.01)),
       ('R1','ground',(5,1,.01)),('R2','ground',(5,-1,.01)),
       ('B3','air',(1,-2,.06)),('R5','air',(3,-2,.06))]


def resolve_mesh(uri,source):
    """Find a file-path mesh reference on this machine.

    Historical worlds hard-code the original workstation's absolute path; a fresh
    checkout only carries the repository copy under ros/models, so fall back to it.
    """
    if uri.is_file():return uri
    root=source/'models'
    if not root.is_dir():return None
    for candidate in (root/uri.name,*root.rglob(uri.name)):
        if candidate.is_file():return candidate
    return None


def mesh_textures(mesh):
    """Collada resolves image sources against the .dae directory, so they must travel with it."""
    if mesh.suffix.lower()!='.dae':return []
    found=[]
    for name in re.findall(r'<init_from>\s*([^<\s]+)\s*</init_from>',mesh.read_text(errors='ignore')):
        if '://' in name:continue
        candidate=(mesh.parent/name).resolve()
        if candidate.is_file() and candidate not in found:found.append(candidate)
    return found


def paint(model,mode):
    """Team colour and a visual-only footprint plate. No collision or inertial element is touched."""
    team='0.10 0.45 0.95' if model.get('name').startswith('B') else '0.95 0.25 0.20'
    halo=[round(float(c)*.55,3) for c in team.split()]
    body=next((link for link in model.findall('link') if link.find('visual') is not None),None)
    if body is None:return
    for visual in body.findall('visual'):
        material=visual.find('material')
        if material is None:material=E.SubElement(visual,'material')
        for tag in ('ambient','diffuse'):
            node=material.find(tag)
            if node is None:node=E.SubElement(material,tag)
            node.text='0.13 0.15 0.19 1'
        node=material.find('specular')
        if node is None:node=E.SubElement(material,'specular')
        node.text='0.55 0.6 0.7 1'
    plate=E.SubElement(body,'visual',name='team_halo')
    offset='-0.064 0 0.004 0 0 0' if mode=='ground' else '0 0 -0.07 0 0 0'
    E.SubElement(plate,'pose').text=offset
    geometry=E.SubElement(E.SubElement(plate,'geometry'),'box')
    E.SubElement(geometry,'size').text='0.62 0.62 0.012'
    material=E.SubElement(plate,'material')
    E.SubElement(material,'ambient').text=team+' 1'
    E.SubElement(material,'diffuse').text=team+' 1'
    E.SubElement(material,'emissive').text=' '.join(map(str,halo))+' 1'


def prepare(out,source,fleet=None):
    out=Path(out);source=Path(source)
    for folder in ('worlds','config','maps','assets'):(out/folder).mkdir(parents=True,exist_ok=True)
    tree=E.parse(source/'worlds/nav_calibration.sdf');world=tree.getroot().find('world');world.set('name','gongyu_fleet')
    ground=world.find('model[@name="B1"]');world.remove(ground)
    air=E.parse(source/'worlds/feedback.sdf').getroot().find('world/model[@name="B3"]')
    bridge=yaml.safe_load((source/'config/nav_bridge.yaml').read_text());all_bridge=[bridge[0]]
    fleet=FLEET if fleet is None else fleet
    missing=[]
    for actor,mode,xyz in fleet:
        template=ground if mode=='ground' else air;old='B1' if mode=='ground' else 'B3'
        model=E.fromstring(E.tostring(template,encoding='unicode').replace(old,actor))
        model.set('name',actor);model.find('pose').text=' '.join(map(str,(*xyz,0,0,0)));paint(model,mode);world.append(model)
        for uri in model.findall('.//visual/geometry/mesh/uri'):
            if '://' in uri.text:continue
            resolved=resolve_mesh(Path(uri.text),source)
            if resolved is None:
                missing.append(dict(actor=actor,uri=uri.text));continue
            target=out/'assets'/'models'/resolved.name
            target.parent.mkdir(parents=True,exist_ok=True)
            if not target.exists():shutil.copy2(resolved,target)
            for texture in mesh_textures(resolved):
                side=target.parent/texture.name
                if not side.exists():shutil.copy2(texture,side)
            uri.text=str(target.resolve())
        if mode=='ground':
            params=yaml.safe_load((source/'config/nav2_B1.yaml').read_text().replace('B1',actor))
            params[actor]['map_server']['ros__parameters']['yaml_filename']=str(out.resolve()/'maps/nav_calibration.yaml')
            (out/f'config/nav2_{actor}.yaml').write_text(yaml.safe_dump(params,sort_keys=False))
            all_bridge.extend(json.loads(json.dumps(r).replace('B1',actor)) for r in bridge[1:])
        else:
            all_bridge.append(dict(ros_topic_name=f'/{actor}/cmd_vel',gz_topic_name=f'/{actor}/gazebo/command/twist',
                ros_type_name='geometry_msgs/msg/Twist',gz_type_name='gz.msgs.Twist',direction='ROS_TO_GZ'))
    (out/'assets'/'unresolved_meshes.json').write_text(json.dumps(missing,indent=2),encoding='utf-8')
    for name in ('nav_calibration.pgm','nav_calibration.yaml'):(out/'maps'/name).write_bytes((source/'maps'/name).read_bytes())
    (out/'assets/waffle.urdf').write_bytes((source/'assets/waffle.urdf').read_bytes())
    (out/'config/fleet_bridge.yaml').write_text(yaml.safe_dump(all_bridge,sort_keys=False))
    (out/'config/fleet.json').write_text(json.dumps([dict(id=a,mode=m,initial_xyz=p) for a,m,p in fleet],indent=2))
    E.indent(tree);tree.write(out/'worlds/fleet.sdf',encoding='utf-8',xml_declaration=True)
    print(out/'worlds/fleet.sdf')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out');a=p.parse_args();prepare(Path(a.out),Path(__file__).resolve().parent)
