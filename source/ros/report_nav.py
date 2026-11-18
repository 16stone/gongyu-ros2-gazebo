"""Recover immutable input files and plot measured localization/navigation traces."""
import argparse
import csv
import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path


def report(path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    path=Path(path);manifest=json.loads((path/'manifest.json').read_text())
    assert json.loads((path/'audit.json').read_text())['status']=='PASS'
    snapshot=path/'inputs';snapshot.mkdir(exist_ok=True)
    receipts={}
    for name in ('ros/nav_sources.json','ros/worlds/nav_calibration.sdf','ros/config/nav2_B1.yaml',
                 'ros/maps/nav_calibration.pgm','ros/maps/nav_calibration.yaml','ros/config/nav_bridge.yaml','ros/assets/waffle.urdf'):
        data=subprocess.check_output(['git','show',manifest['code_revision']+':'+name])
        target=snapshot/Path(name).name;target.write_bytes(data)
        receipts[name]=hashlib.sha256(data).hexdigest()
        if name in manifest['source_sha256']:
            assert receipts[name]==manifest['source_sha256'][name]
    (snapshot/'source_receipt.json').write_text(json.dumps({'retrieved_from_commit':manifest['code_revision'],
        'post_run_recovery':True,'sha256':receipts},indent=2)+'\n')
    with (path/'truth_trajectory.csv').open() as f:
        rows=[{k:float(v) for k,v in r.items()} for r in csv.DictReader(f)]
    amcl=[json.loads(s) for s in (path/'amcl.jsonl').read_text().splitlines()]
    events=[json.loads(s) for s in (path/'events.jsonl').read_text().splitlines()]
    sources=json.loads((snapshot/'nav_sources.json').read_text())
    arrival=next(e for e in events if e['kind']=='physical_arrival_confirmed')
    cancel=next(e for e in events if e['kind']=='navigation_cancel_requested')
    fig,axes=plt.subplots(1,3,figsize=(14,4.5),constrained_layout=True)
    ax,bx,cx=axes
    for name,x,y,sx,sy,_ in sources['boxes']:
        ax.add_patch(Rectangle((x-sx/2,y-sy/2),sx,sy,facecolor='#db9859' if name=='detour_box' else '#abb5b8',alpha=.85))
    ax.plot([r['x'] for r in rows],[r['y'] for r in rows],color='#267b9e',lw=2,label='Gazebo actual pose')
    ax.plot([p['x'] for p in amcl],[p['y'] for p in amcl],color='#93563a',ls=':',lw=1,label='AMCL estimate')
    ax.scatter([0,4],[2,2],marker='*',s=80,color='#253c32',zorder=4)
    ax.set(xlabel='x (m)',ylabel='y (m)',title='Measured path around the box',xlim=(-.7,4.7),ylim=(.5,4.1))
    ax.set_aspect('equal',adjustable='box');ax.legend(fontsize=8,loc='lower center')
    bx.plot([r['t_s'] for r in rows],[r['speed'] for r in rows],color='#267b9e')
    bx.axvline(arrival['t_s'],color='#49734b',ls='--',label='actual settled arrival')
    bx.axvline(cancel['t_s'],color='#a35d44',ls=':',label='cancel requested')
    bx.set(xlabel='Simulation time (s)',ylabel='speed (m/s)',title='Actual motion and stopping')
    bx.grid(alpha=.2);bx.legend(fontsize=8)
    scans=path/'scan_snapshots.jsonl'
    if scans.exists():
        scan=json.loads(scans.read_text().splitlines()[0])
        xy=[(value*math.cos(scan['angle_min']+i*scan['angle_increment']),
             value*math.sin(scan['angle_min']+i*scan['angle_increment']))
            for i,value in enumerate(scan['ranges']) if value is not None]
        cx.scatter([p[0] for p in xy],[p[1] for p in xy],s=4,color='#687b78')
        cx.scatter(0,0,s=40,color='#a35d44')
        cx.set(title='Actual 360-beam laser snapshot',xlabel='sensor x (m)',ylabel='sensor y (m)')
        cx.set_aspect('equal',adjustable='box');cx.grid(alpha=.2)
    else:
        cx.text(.1,.5,'Raw scan not retained in this version',transform=cx.transAxes);cx.axis('off')
    fig.suptitle(path.name+' | one Waffle, AMCL + Nav2\nKnown initial pose seeded once; simulator truth is an independent acceptance signal.',fontsize=11)
    fig.savefig(path/'nav_evidence.png',dpi=180);fig.savefig(path/'nav_evidence.svg')
    plt.close(fig)
    selected=next((path/'screenshots/01_arrived_after_detour').glob('*.png'))
    shutil.copy2(selected,path/'arrived_native.png')
    assert hashlib.sha256(selected.read_bytes()).digest()==hashlib.sha256((path/'arrived_native.png').read_bytes()).digest()
    artifacts={str(p.relative_to(path)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(path.rglob('*')) if p.is_file() and p.name!='artifact_sha256.json'}
    (path/'artifact_sha256.json').write_text(json.dumps(artifacts,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run_dir');report(p.parse_args().run_dir)
