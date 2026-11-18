#!/usr/bin/env python3
"""Generate Webots R2025a worlds from the frozen Gongyu scenario card.

This Webots build uses Z-UP: getPosition/translation = [x, y(horizontal), z(height)].
Scenario coordinates (sx, sy, h) map to Webots (sx, sy, h).
"""
import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCEN = json.load(open(os.path.join(ROOT, 'config', 'scenario_medium.json'), encoding='utf-8'))
NODES = SCEN['nodes']

# ---- visual palette (dark tech / control-room aesthetic) ----
SKY = [(0.05, 0.08, 0.13), (0.09, 0.13, 0.20), (0.13, 0.18, 0.26)]
FLOOR = (0.10, 0.13, 0.18)
GRID = (0.08, 0.42, 0.52)
CHANNEL = (0.90, 0.66, 0.16)
BLUE = (0.10, 0.52, 0.92)
BLUE_L = (0.35, 0.78, 1.00)
RED = (0.93, 0.30, 0.17)
RED_L = (1.00, 0.56, 0.28)
OBST = (0.62, 0.14, 0.14)
EDGE_G = (0.14, 0.38, 0.48)
EDGE_A = (0.46, 0.32, 0.66)
NEUTRAL = (0.45, 0.55, 0.66)

AIR_NODES = {'F', 'K', 'H', 'F_R', 'K_R', 'H_R'}
RED_NODES = {'N0', 'PN', 'RN', 'S0', 'PS', 'RS'}


def rgb(c):
    return '%.3f %.3f %.3f' % c


def pbr(base, rough=0.55, metal=0.15, emit=None, ei=1.0):
    e = emit if emit else (0.0, 0.0, 0.0)
    return 'PBRAppearance { baseColor %s roughness %.2f metalness %.2f emissiveColor %s emissiveIntensity %.2f }' % (
        rgb(base), rough, metal, rgb(e), ei)


def shape_box(size, app):
    return 'Shape { appearance %s geometry Box { size %s } }' % (app, ' '.join(str(x) for x in size))


def solid(name, pos, children, rot=None, physics=False, bounding=None):
    r = (' rotation %s' % rot) if rot else ''
    phys = ' physics Physics {}' if physics else ''
    bnd = (' boundingObject %s' % bounding) if bounding else ''
    return 'Solid { name "%s" translation %s%s children [ %s ]%s%s }' % (name, pos, r, children, bnd, phys)


def pos(sx, sy, h):
    """scenario -> Webots Z-up translation triple string."""
    return '%.4f %.4f %.4f' % (sx, sy, h)


def emissive_line(name, x1, y1, x2, y2, h, w, color):
    """Flat glowing line on the arena floor between two scenario points (Z-up)."""
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    leng = math.hypot(x2 - x1, y2 - y1)
    ang = math.atan2(y2 - y1, x2 - x1)
    app = pbr(color, rough=0.4, emit=color, ei=0.45)
    # rotation about Z axis
    return 'Solid { name "%s" translation %s rotation 0 0 1 %.5f children [ %s ] }' % (
        name, pos(mx, my, h), ang, shape_box((leng, w, 0.006), app))


def node_marker(nid):
    x, y = NODES[nid][0], NODES[nid][1]
    if nid in AIR_NODES:
        col = BLUE_L if not nid.endswith('_R') else RED_L
    elif nid in RED_NODES:
        col = RED_L
    else:
        col = (0.35, 0.85, 0.95) if nid in ('L', 'J', 'O') else NEUTRAL
    disk = 'Shape { appearance %s geometry Cylinder { height 0.02 radius 0.16 subdivision 24 } }' % (
        pbr(col, rough=0.3, emit=col, ei=0.9))
    post = 'Shape { appearance %s geometry Cylinder { height 0.22 radius 0.02 subdivision 12 } }' % (
        pbr(col, rough=0.3, emit=col, ei=0.6))
    return ('Solid { name "node_%s" translation %s children [ %s ] }' % (nid, pos(x, y, 0.012), disk),
            'Solid { translation %s children [ %s ] }' % (pos(x, y, 0.13), post))


def robot_ugv(name, sx, sy, heading=0.0):
    blue = name.startswith('B')
    body = BLUE if blue else RED
    glow = BLUE_L if blue else RED_L
    top = pbr(body, rough=0.35, metal=0.35, emit=body, ei=0.25)
    accent = pbr(glow, rough=0.3, emit=glow, ei=0.8)
    dark = pbr((0.05, 0.06, 0.08), rough=0.7, metal=0.4)
    shape = shape_box((0.40, 0.34, 0.14), top)  # Z-up: width(x), depth(y), height(z)
    canopy = solid('canopy', '0 0 0.10', shape_box((0.22, 0.20, 0.06), accent))
    beacon = solid('beacon', '0.12 0 0.15', shape_box((0.05, 0.05, 0.05), accent))
    wheel_shapes = []
    for _ in range(4):
        wheel_shapes.append('Shape { appearance %s geometry Cylinder { height 0.05 radius 0.085 subdivision 20 } }' % dark)
    joints = []
    motors = [('left_motor', 'left_sensor', -0.17, -0.16),
              ('right_motor', 'right_sensor', 0.17, -0.16),
              ('rear_left_motor', 'rear_left_sensor', -0.17, 0.16),
              ('rear_right_motor', 'rear_right_sensor', 0.17, 0.16)]
    for (mn, sn, wx, wy), ws in zip(motors, wheel_shapes):
        # Cylinder axis is Y by default -> wheel rolls about Y (Z-up ground)
        joints.append('''HingeJoint {
  jointParameters HingeJointParameters { axis 0 1 0 anchor %.2f %.2f -0.035 }
  device [ RotationalMotor { name "%s" maxVelocity 12 } PositionSensor { name "%s" } ]
  endPoint Solid {
    translation %.2f %.2f -0.035
    children [ %s ]
    boundingObject Cylinder { height 0.05 radius 0.085 subdivision 20 }
    physics Physics { density 800 }
  }
}''' % (wx, wy, mn, sn, wx, wy, ws))
    sensors = '''Lidar { name "lidar_main" translation 0.18 0 0.20 horizontalResolution 180 numberOfLayers 1 fieldOfView 6.283185 minRange 0.02 maxRange 3.0 }
Lidar { name "lidar_low" translation 0.18 0 0.18 horizontalResolution 180 numberOfLayers 1 fieldOfView 6.283185 minRange 0.15 maxRange 1.2 }
InertialUnit { name "imu" }
Compass { name "compass" }
GPS { name "gps" }'''
    children = ' '.join([shape, canopy, beacon] + joints + [sensors])
    return '''DEF %s Robot {
  name "%s" translation %s rotation 0 0 1 %.6f
  controller "gongyu_ugv"
  children [ %s ]
  boundingObject Box { size 0.42 0.40 0.22 }
  physics Physics { density 400 }
}''' % (name, name, pos(sx, sy, 0.12), heading, children)


def robot_uav(name, sx, sy, height):
    blue = name == 'B3'
    body = BLUE if blue else RED
    glow = BLUE_L if blue else RED_L
    top = pbr(body, rough=0.35, metal=0.4, emit=body, ei=0.3)
    arm = pbr((0.12, 0.13, 0.16), rough=0.5, metal=0.5)
    prop = pbr(glow, rough=0.4, emit=glow, ei=0.5)
    arms = []
    motors = []
    mnames = ['front left propeller', 'front right propeller', 'rear left propeller', 'rear right propeller']
    for (mx, my), mn in zip([(-0.13, -0.13), (0.13, -0.13), (-0.13, 0.13), (0.13, 0.13)], mnames):
        arms.append(solid('', pos(mx / 2, my / 2, 0),
                          shape_box((0.30, 0.03, 0.012), arm),
                          rot='0 0 1 %.4f' % math.atan2(my, mx)))
        motors.append('''HingeJoint {
  jointParameters HingeJointParameters { axis 0 0 1 anchor %.2f %.2f 0.03 }
  device [ RotationalMotor { name "%s" maxVelocity 1200 } ]
  endPoint Solid { translation %.2f %.2f 0.03 children [ %s ] physics Physics { density 100 } }
}''' % (mx, my, mn, mx, my, shape_box((0.26, 0.035, 0.008), prop)))
    core = shape_box((0.18, 0.18, 0.07), top)
    cam = solid('', '0.10 0 -0.05', shape_box((0.06, 0.06, 0.06), arm))
    sensors = 'GPS { name "gps" } InertialUnit { name "inertial unit" } Gyro { name "gyro" } Camera { name "camera" width 160 height 120 fieldOfView 1.0 }'
    children = ' '.join([core, cam] + arms + motors + [sensors])
    return '''DEF %s Robot {
  name "%s" translation %s
  controller "gongyu_uav"
  children [ %s ]
  boundingObject Box { size 0.36 0.36 0.10 }
  physics Physics { density 120 }
}''' % (name, name, pos(sx, sy, height), children)


def team_beacon(name, sx, sy, color):
    app = pbr(color, rough=0.3, emit=color, ei=1.0)
    core = shape_box((0.10, 0.10, 1.6), app)
    cap = solid('', '0 0 0.85', shape_box((0.28, 0.28, 0.06), app))
    return 'Solid { name "%s" translation %s children [ %s %s ] }' % (name, pos(sx, sy, 0.8), core, cap)


UGV = [('B1', 'D'), ('B2', 'O'), ('R1', 'E'), ('R2', 'E'), ('R3', 'N0'), ('R4', 'S0')]
UAV = [('B3', 'F'), ('R5', 'F_R')]


def world(name, robots, low_obstacle=False, holdout=False):
    b = []
    b.append('#VRML_SIM R2025a utf8')
    b.append('# generated by webots/tools/generate_world.py; scenario=%s (Z-up)' % SCEN['id'])
    b.append('')
    b.append('WorldInfo { basicTimeStep 16 title "%s" }' % name)
    b.append('Viewpoint { position 9.5 -15 19 orientation 0.61 0 0 1.57 }')
    sky = ' '.join(rgb(c) for c in SKY)
    b.append('Background { skyColor [ %s ] }' % sky)
    b.append('DirectionalLight { direction -0.4 0.3 -1 intensity 2.2 color 0.85 0.92 1.0 castShadows TRUE }')
    b.append('DirectionalLight { direction 0.5 -0.4 -0.7 intensity 0.7 color 0.5 0.7 1.0 }')
    b.append('PointLight { location 4 0 4 intensity 25 attenuation 0 0 0.02 color 0.2 0.6 1.0 }')
    b.append('PointLight { location 12 -4 4 intensity 22 attenuation 0 0 0.02 color 1.0 0.4 0.2 }')
    # floor: center scenario (9.5, -2.5), thickness 0.16 in Z, top at z=0
    b.append(solid('DEF_floor', pos(9.5, -2.5, -0.08),
                   shape_box((27, 28, 0.16), pbr(FLOOR, rough=0.92, metal=0.02)),
                   bounding='Box { size 27 28 0.16 }'))
    # grid lines
    gx = 0
    for xv in range(-3, 23, 2):
        b.append(emissive_line('grid_x_%d' % gx, xv, -16, xv, 11, 0.004, 0.012, GRID)); gx += 1
    gz = 0
    for zv in range(-16, 12, 2):
        b.append(emissive_line('grid_z_%d' % gz, -3, zv, 22, zv, 0.004, 0.012, GRID)); gz += 1
    # arena border
    for (nm, x1, y1, x2, y2) in [('bd_n', -3, 10.5, 22, 10.5), ('bd_s', -3, -15.5, 22, -15.5),
                                  ('bd_w', -3, -15.5, -3, 10.5), ('bd_e', 22, -15.5, 22, 10.5)]:
        b.append(emissive_line(nm, x1, y1, x2, y2, 0.02, 0.05, (0.20, 0.65, 0.85)))
    # topology edges
    for i, e in enumerate(SCEN['edges']):
        a, bb, _, mode = e[0], e[1], e[2], e[3]
        if a in NODES and bb in NODES:
            col = EDGE_A if mode == 'air' else EDGE_G
            b.append(emissive_line('edge_%d' % i, NODES[a][0], NODES[a][1],
                                   NODES[bb][0], NODES[bb][1], 0.010, 0.018, col))
    # central channel highlight (decorative)
    b.append(solid('channel_floor', pos(3.5, 0, 0.004),
                   shape_box((3.2, 1.0, 0.008), pbr(CHANNEL, rough=0.4, emit=CHANNEL, ei=0.55)), physics=False))
    for sy in (0.55, -0.55):
        b.append(solid('channel_rail', pos(3.5, sy, 0.30),
                       shape_box((3.2, 0.08, 0.6), pbr((0.30, 0.32, 0.38), rough=0.6, metal=0.3,
                                                       emit=CHANNEL, ei=0.15)),
                       bounding='Box { size 3.2 0.08 0.6 }'))
    # frozen obstacles (scenario minimum/maximum = [x, y, z-up])
    for ob in SCEN['geometry']['obstacles']:
        lo, hi = ob['minimum'], ob['maximum']
        cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
        cz = (lo[2] + hi[2]) / 2
        size = (hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])
        b.append(solid(ob['id'], pos(cx, cy, cz), shape_box(size, pbr(OBST, rough=0.5, emit=OBST, ei=0.35)),
                       bounding='Box { size %s }' % ' '.join(str(v) for v in size)))
    if low_obstacle:
        cy = 0.15 if not holdout else -4.6
        b.append(solid('low_obstacle', pos(3.5, cy, 0.09),
                       shape_box((0.4, 0.8, 0.18), pbr((0.95, 0.70, 0.12), rough=0.5,
                                                       emit=(0.95, 0.70, 0.12), ei=0.4)),
                       bounding='Box { size 0.4 0.8 0.18 }'))
    for nid in NODES:
        disk, post = node_marker(nid)
        b.append(disk); b.append(post)
    b.append(team_beacon('beacon_blue', 4.0, 7.5, BLUE_L))
    b.append(team_beacon('beacon_red', 12.0, -7.5, RED_L))
    fl = SCEN['fleet']
    berths = SCEN.get('physical_berths', {})
    def spawn(node):
        bps = berths.get(node)
        if bps:
            return [bps[0][0], bps[0][1], 0.3]
        return list(NODES[node]) + [0.3]
    initial = dict((k, v.get('initial_xyz', spawn(v['node']))) for k, v in fl.items())
    # separate multi-berth spawns (E holds R1,R2; D holds B1)
    used = {}
    for nm, v in fl.items():
        node = v['node']
        bps = berths.get(node)
        if bps and 'initial_xyz' not in v:
            i = used.get(node, 0)
            if i < len(bps):
                initial[nm] = [bps[i][0], bps[i][1], 0.3]
                used[node] = i + 1
    if holdout:
        initial = dict(initial)
        initial['R3'] = [8.0, -5.0, 0.3]
        initial['R4'] = [8.0, -11.5, 0.3]
    for nm, node in robots:
        p = initial.get(nm, [NODES[node][0], NODES[node][1], 0.3])
        b.append(robot_uav(nm, p[0], p[1],
                           SCEN['geometry']['heights']['blue_air'] if nm == 'B3' else SCEN['geometry']['heights']['red_air'])
                 if nm in ('B3', 'R5') else robot_ugv(nm, p[0], p[1]))
    b.append('Robot { name "referee" supervisor TRUE controller "gongyu_referee" }')
    out = os.path.join(ROOT, 'worlds', name + '.wbt')
    open(out, 'w', encoding='utf-8').write('\n'.join(b) + '\n')
    print(out)


if __name__ == '__main__':
    # Static scenery must have physics disabled; otherwise the floor itself falls
    # and every robot free-falls through it (root cause found in phys-probe-01).
    suffix = os.environ.get('GONGYU_WORLD_SUFFIX', '')
    def gen(name, *a, **kw):
        return world(name + suffix, *a, **kw)
    gen('web_b1_route', [('B1', 'D')], low_obstacle=True)
    gen('web_b1_lowobs', [('B1', 'D')], low_obstacle=True)
    gen('web_b3_target', [('B3', 'F')])
    gen('web_medium', UGV + UAV)
    gen('web_holdout_v1', UGV + UAV, holdout=True)
    gen('web_d4', [('B1', 'D'), ('B2', 'O'), ('R3', 'N0'), ('B3', 'F')])
    gen('web_smoke', [('B1', 'D')], low_obstacle=True)
    print('WORLDS_GENERATED suffix=' + suffix)
