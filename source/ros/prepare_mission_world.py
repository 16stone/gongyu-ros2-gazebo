"""Card-aligned scene geometry; initial berths only, not a completed mission driver."""
import hashlib,json,math,shutil
import xml.etree.ElementTree as E
from pathlib import Path
import yaml
from .prepare_fleet_world import prepare as prepare_fleet
from gongyu.berths import Berths,physical_card


def degrade(world,card):
    """Opt-in perception stress; absent keys leave the nominal world byte-identical.

    `sensor_noise_stddev_m` widens the gaussian sigma that the vendor model already
    carries (0.01 m), so the stress cell is a measured multiple of the nominal sensor
    rather than an invented one.  `sensor_occluders` adds solid obstacles that are
    deliberately *not* registered in the static map: the only way a unit can learn
    about them is its own lidar, which is what the occlusion cell is meant to test.
    """
    sigma=card.get('sensor_noise_stddev_m')
    if sigma is not None:
        sigma=float(sigma)
        if not 0.<sigma<=.5:raise ValueError('sensor_noise_stddev_m out of range: '+str(sigma))
        touched=0
        for sensor in world.iter('sensor'):
            if sensor.get('type')!='gpu_lidar':continue
            noise=sensor.find('ray/noise')
            if noise is None:continue
            noise.find('type').text='gaussian';noise.find('mean').text='0.0'
            noise.find('stddev').text=repr(sigma);touched+=1
        if touched<2*sum(1 for s in card['fleet'].values() if s['mode']=='ground'):
            raise ValueError('expected one noise block per ground lidar, got '+str(touched))
    for i,spec in enumerate(card.get('sensor_occluders') or []):
        x,y,sx,sy,height=spec
        model=E.SubElement(world,'model',name='unmapped_occluder_'+str(i))
        E.SubElement(model,'static').text='true'
        E.SubElement(model,'pose').text=' '.join(map(str,(x,y,height/2,0,0,0)))
        link=E.SubElement(model,'link',name='body')
        for kind in ('collision','visual'):
            part=E.SubElement(link,kind,name=kind);g=E.SubElement(part,'geometry')
            E.SubElement(E.SubElement(g,'box'),'size').text=' '.join(map(str,(sx,sy,height)))
            if kind=='visual':
                material=E.SubElement(part,'material')
                for tag,value in (('ambient','0.42 0.30 0.10 1'),('diffuse','0.55 0.40 0.14 1'),
                                  ('emissive','0.05 0.03 0.01 1')):E.SubElement(material,tag).text=value


def prepare(out,card):
    out=Path(out);source=Path(__file__).resolve().parent
    original=card;card=physical_card(card) if 'physical_berths' not in card else card
    berths=Berths(card);fleet=[]
    for actor,spec in card['fleet'].items():
        x,y,_=berths.position(actor,spec['node']);mode=spec['mode']
        fleet.append((actor,mode,(float(x),float(y),.01 if mode=='ground' else .06)))
    prepare_fleet(out,source,fleet)
    shutil.copy2(source/'config/axial_transit.xml',out/'config/axial_transit.xml')
    for actor,mode,_ in fleet:
        if mode=='ground':
            path=out/f'config/nav2_{actor}.yaml';params=yaml.safe_load(path.read_text())
            params[actor]['controller_server']['ros__parameters']['goal_checker']['xy_goal_tolerance']=.08
            params[actor]['controller_server']['ros__parameters']['goal_checker']['stateful']=False
            # A nearby free endpoint cannot stand in for an independently checked .1 m berth.
            params[actor]['planner_server']['ros__parameters']['GridBased']['tolerance']=0.
            for costmap,layer in [('local_costmap','voxel_layer'),('global_costmap','obstacle_layer')]:
                layers=params[actor][costmap][costmap]['ros__parameters']
                # A clear no-return ray must also erase an old moving-peer obstacle.
                layers[layer]['scan']['inf_is_valid']=True
                layers['peer_layer']['peer_scan']['inf_is_valid']=True
            path.write_text(yaml.safe_dump(params,sort_keys=False))
    tree=E.parse(out/'worlds/fleet.sdf');world=tree.getroot().find('world');world.set('name','gongyu_mission')
    for model in list(world.findall('model')):
        if model.get('name') not in {a for a,_,_ in fleet}|{'ground_plane'}:world.remove(model)
    scene=E.Element('scene');world.insert(0,scene)
    E.SubElement(scene,'ambient').text='0.45 0.5 0.6 1'
    E.SubElement(scene,'background').text='0.06 0.09 0.14 1'
    E.SubElement(scene,'shadows').text='true'
    ground=world.find('model[@name="ground_plane"]')
    if ground is not None:
        for visual in ground.findall('.//visual'):
            material=visual.find('material')
            if material is None:material=E.SubElement(visual,'material')
            for tag,value in (('ambient','0.12 0.14 0.17 1'),('diffuse','0.16 0.19 0.23 1'),('specular','0.05 0.05 0.05 1')):
                node=material.find(tag)
                if node is None:node=E.SubElement(material,tag)
                node.text=value
    points=list(card['nodes'].values())+list(card['geometry']['infrastructure'].values())+[card['geometry']['device']]
    points.extend(p for positions in card['physical_berths'].values() for p in positions)
    if card.get('physical_delivery_waypoint') is not None:points.append(card['physical_delivery_waypoint'])
    for path in card['geometry']['edge_polylines'].values():points.extend(path)
    xmin=math.floor(min(p[0] for p in points)-2);xmax=math.ceil(max(p[0] for p in points)+2)
    ymin=math.floor(min(p[1] for p in points)-2);ymax=math.ceil(max(p[1] for p in points)+2)
    boxes=[]
    def box(name,minimum,maximum,color,collision=True,emissive=None):
        model=E.SubElement(world,'model',name=name);E.SubElement(model,'static').text='true'
        center=[(a+b)/2 for a,b in zip(minimum,maximum)];size=[b-a for a,b in zip(minimum,maximum)]
        E.SubElement(model,'pose').text=' '.join(map(str,(*center,0,0,0)));link=E.SubElement(model,'link',name='body')
        for kind in (('collision','visual') if collision else ('visual',)):
            part=E.SubElement(link,kind,name=kind);g=E.SubElement(part,'geometry');E.SubElement(E.SubElement(g,'box'),'size').text=' '.join(map(str,size))
            if kind=='visual':
                material=E.SubElement(part,'material');E.SubElement(material,'ambient').text=color;E.SubElement(material,'diffuse').text=color
                if emissive is not None:E.SubElement(material,'emissive').text=emissive
        if collision:boxes.append((minimum,maximum))
    for o in card['geometry']['obstacles']:box(o['id'],o['minimum'],o['maximum'],'0.20 0.26 0.34 1',emissive='0.02 0.05 0.08 1')
    for name,mn,mx in (
        ('west_boundary',[xmin-.15,ymin-.15,0],[xmin,ymax+.15,1]),
        ('east_boundary',[xmax,ymin-.15,0],[xmax+.15,ymax+.15,1]),
        ('south_boundary',[xmin,ymin-.15,0],[xmax,ymin,1]),
        ('north_boundary',[xmin,ymax,0],[xmax,ymax+.15,1])):box(name,mn,mx,'0.10 0.13 0.18 1')
    # Stop walls short of E/W node centers so paired initial berths remain outside the tunnel.
    e,w=card['nodes']['E'],card['nodes']['W']
    if e[1]!=w[1]:raise ValueError('initial mission generator requires a horizontal E-W channel')
    for side in (-1,1):
        y=e[1]+(card.get('physical_channel_clear_width_m',1.0)/2+.075)*side
        box('channel_wall_'+str(side),[min(e[0],w[0])+.35,y-.075,0],[max(e[0],w[0])-.35,y+.075,1.2],'0.30 0.42 0.56 1',emissive='0.03 0.10 0.16 1')
    for name,p in card['nodes'].items():box('waypoint_'+name,[p[0]-.12,p[1]-.12,.005],[p[0]+.12,p[1]+.12,.015],'0.15 0.55 0.7 1',False,emissive='0.1 0.85 1 1')
    for name,positions in card['physical_berths'].items():
        for i,(x,y) in enumerate(positions):box(f'berth_{name}_{i}',[x-.06,y-.06,.016],[x+.06,y+.06,.025],'0.2 0.8 0.3 1',False,emissive='0.1 0.7 0.3 1')
    p=card['geometry']['device'];box('observed_device',[p[0]-.1,p[1]-.1,p[2]-.1],[p[0]+.1,p[1]+.1,p[2]+.1],'0.8 0.15 0.15 1',False,emissive='1 0.15 0.15 1')
    # The delivered recording camera was patched in out of band, so video could not be re-recorded from source.
    # Pose, image size and rate are copied verbatim from that camera to keep new footage comparable with the release.
    camera=E.SubElement(world,'model',name='evidence_camera')
    E.SubElement(camera,'static').text='true'
    E.SubElement(camera,'pose').text='9.5 -2.5 32 0 1.57079632679 0'
    sensor=E.SubElement(E.SubElement(camera,'link',name='link'),'sensor',name='camera')
    sensor.set('type','camera')
    image=E.SubElement(E.SubElement(sensor,'camera'),'image')
    E.SubElement(image,'width').text='960'
    E.SubElement(image,'height').text='600'
    E.SubElement(image,'format').text='R8G8B8'
    E.SubElement(sensor,'always_on').text='1'
    E.SubElement(sensor,'update_rate').text='5'
    E.SubElement(sensor,'topic').text='gongyu_record_camera'
    degrade(world,card)
    E.indent(tree);tree.write(out/'worlds/fleet.sdf',encoding='utf-8',xml_declaration=True)
    resolution=.05;origin=(xmin-.2,ymin-.2);width=math.ceil((xmax-xmin+.4)/resolution);height=math.ceil((ymax-ymin+.4)/resolution)
    grid=bytearray()
    for row in range(height):
        y=origin[1]+(height-row-.5)*resolution
        for col in range(width):
            x=origin[0]+(col+.5)*resolution
            grid.append(0 if any(a[0]<=x<=b[0] and a[1]<=y<=b[1] for a,b in boxes) else 254)
    (out/'maps/nav_calibration.pgm').write_bytes(f'P5\n{width} {height}\n255\n'.encode()+grid)
    (out/'maps/nav_calibration.yaml').write_text(yaml.safe_dump(dict(image='nav_calibration.pgm',resolution=resolution,origin=[*origin,0.],negate=0,occupied_thresh=.65,free_thresh=.25)))
    gui=(source/'config/nav_gui.config').read_text().replace('<camera_pose>2 2 6 0 1.57079632679 0</camera_pose>','<camera_pose>8 0 24 0 1.57079632679 0</camera_pose>')
    (out/'config/nav_gui.config').write_text(gui)
    (out/'scenario.json').write_text(json.dumps(card,indent=2))
    (out/'source_scenario.json').write_text(json.dumps(original,indent=2))
    (out/'mission_scene.json').write_text(json.dumps(dict(bounds=[xmin,ymin,xmax,ymax],obstacles=card['geometry']['obstacles'],
        scenario_sha256=hashlib.sha256(json.dumps(card,sort_keys=True).encode()).hexdigest(),physical_boxes=boxes,
        limits=['explicit physical berths require the PhysicalWorld destination allocator; no motion validation yet',
                'aircraft start on ground and must take off before mission clock starts',
                'physical narrow walls added; motion times require shared recalibration',
                'visual/RF opacity still evaluated by abstract mission geometry']),indent=2))


if __name__=='__main__':
    import argparse
    from gongyu.world import load_card
    p=argparse.ArgumentParser();p.add_argument('case');p.add_argument('out');a=p.parse_args();prepare(Path(a.out),load_card(a.case))
