"""Report plots and screenshot index from a verified calibration trace."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path


def report(path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    path=Path(path)
    assert json.loads((path/'audit.json').read_text())['status']=='PASS'
    events=[json.loads(x) for x in (path/'events.jsonl').read_text().splitlines()]
    with (path/'trajectory.csv').open() as f:
        rows=[{**r,**{k:float(r[k]) for k in ('t_s','x','y','z','yaw','speed','wz')}} for r in csv.DictReader(f)]
    cancelled=next(e for e in events if e['kind']=='cancel_requested')
    stopped=next(e for e in events if e['kind']=='cancel_settled')
    stats={}
    for actor in ('B1','B3'):
        window=[r for r in rows if r['actor']==actor and cancelled['t_s']<=r['t_s']<=stopped['t_s']]
        last=[r for r in window if r['t_s']>=stopped['t_s']-1.]
        origin=cancelled['payload']['positions'][actor]
        peak=max(math.dist([r['x'],r['y'],r['z']],origin) for r in window)
        speed=max(r['speed'] for r in last)
        assert peak<=(.3 if actor=='B3' else .25) and speed<=.1
        stats[actor]={'maximum_cancel_displacement_m':peak,'last_second_maximum_speed_mps':speed}
    (path/'cancel_window_analysis.json').write_text(json.dumps(stats,indent=2)+'\n')
    index=[]
    for e in events:
        if e['kind']=='native_screenshot_requested':
            files=list((path/'screenshots'/e['payload']['label']).glob('*.png'))
            assert len(files)==1
            index.append({'label':e['payload']['label'],'simulation_paused_at_s':e['t_s'],
                'file':str(files[0].relative_to(path)),
                'sha256':hashlib.sha256(files[0].read_bytes()).hexdigest(),
                'source':'Gazebo GUI /gui/screenshot; unedited renderer output; no full desktop UI'})
    (path/'screenshot_index.json').write_text(json.dumps(index,indent=2)+'\n')
    fig,axes=plt.subplots(2,2,figsize=(11,7),constrained_layout=True)
    for actor,color in (('B1','#397d9d'),('B3','#b16d46')):
        data=[r for r in rows if r['actor']==actor]
        t=[r['t_s'] for r in data]
        axes[0,0].plot([r['x'] for r in data],[r['y'] for r in data],color=color,label=actor)
        axes[1,1].plot(t,[r['speed'] for r in data],color=color,label=actor)
        if actor=='B3':
            axes[0,1].plot(t,[r['z'] for r in data],color=color)
            axes[1,0].plot(t,[r['yaw']*180/math.pi for r in data],color=color)
    axes[0,0].set(title='Actual horizontal trajectories',xlabel='x (m)',ylabel='y (m)')
    axes[0,0].legend();axes[0,0].set_aspect('equal',adjustable='datalim')
    axes[0,1].set(title='Aircraft height',ylabel='z (m)',xlabel='Simulation time (s)')
    axes[0,1].axhline(1.5,color='#777777',ls='--',lw=1)
    axes[1,0].set(title='Aircraft yaw',ylabel='yaw (degrees)',xlabel='Simulation time (s)')
    axes[1,0].axhline(90,color='#777777',ls='--',lw=1)
    axes[1,1].set(title='Speed derived from actual world poses',ylabel='speed (m/s)',xlabel='Simulation time (s)')
    axes[1,1].legend()
    for ax in (axes[0,1],axes[1,0],axes[1,1]):
        ax.axvline(cancelled['t_s'],color='#555555',ls=':',lw=1)
        ax.grid(alpha=.2)
    fig.suptitle('Gazebo one-car / one-aircraft feedback calibration\nSimulator world-pose feedback; not Nav2, localization or mission validation',fontsize=12)
    fig.savefig(path/'feedback_trajectory.png',dpi=180);fig.savefig(path/'feedback_trajectory.svg')
    plt.close(fig)
    print(json.dumps(stats,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run_dir');report(p.parse_args().run_dir)
