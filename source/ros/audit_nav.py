"""Audit navigation using actual trajectories, action results and source snapshots."""
import argparse
import csv
import hashlib
import json
import math
import subprocess
from pathlib import Path


def audit(path):
    path=Path(path)
    metrics=json.loads((path/'metrics.json').read_text())
    manifest=json.loads((path/'manifest.json').read_text())
    events=[json.loads(s) for s in (path/'events.jsonl').read_text().splitlines()]
    with (path/'truth_trajectory.csv').open() as f:
        rows=[{k:float(v) for k,v in r.items()} for r in csv.DictReader(f)]
    assert metrics['status']=='PASS',metrics['failure']
    assert not manifest['code_dirty']
    for name,expected in manifest['source_sha256'].items():
        data=subprocess.check_output(['git','show',manifest['code_revision']+':'+name])
        assert hashlib.sha256(data).hexdigest()==expected,name
    assert sum(e['kind']=='initial_pose_seeded' for e in events)==1
    result1=next(e for e in events if e['kind']=='navigation_result' and e['payload']['goal_id']==1)
    assert result1['payload']['ros_status']==4
    arrival=metrics['arrival']
    window=[r for r in rows if arrival['t_s']-1.<=r['t_s']<=arrival['t_s']]
    assert len(window)>=2 and window[-1]['t_s']-window[0]['t_s']>=.9
    errors=[math.hypot(r['x']-4.,r['y']-2.) for r in window]
    assert max(errors)<=.25 and max(r['speed'] for r in window)<=.1
    cancel=next(e for e in events if e['kind']=='navigation_cancel_requested')
    ack=next(e for e in events if e['kind']=='navigation_cancel_acknowledged')
    terminal=next(e for e in events if e['kind']=='navigation_result' and e['payload']['goal_id']==2)
    assert ack['payload']['accepted'] and terminal['payload']['ros_status']==5
    assert ack['t_s']>=cancel['t_s'] and terminal['t_s']>=cancel['t_s']
    assert metrics['cancel_started']['speed']>.12
    stopped=next(e['payload'] for e in events if e['kind']=='cancel_stopped')
    end_window=[r for r in rows if stopped['t_s']-1.<=r['t_s']<=stopped['t_s']]
    assert len(end_window)>=2 and end_window[-1]['t_s']-end_window[0]['t_s']>=.9
    assert max(r['speed'] for r in end_window)<=.1
    gaps=[]
    for a,b in zip(rows,rows[1:]):
        dt=b['t_s']-a['t_s']
        assert dt>=0
        if dt>0:
            gaps.append(dt)
            expected=math.hypot(b['x']-a['x'],b['y']-a['y'])/dt
            assert abs(expected-b['speed'])<1e-6
    assert gaps and max(gaps)<=.2
    assert max(r['y'] for r in rows)>2.5
    clearance=min(math.hypot(max(abs(r['x']-2.)-.4,0.),max(abs(r['y']-2.)-.7,0.)) for r in rows)
    assert clearance>.22,'configured planning radius intersects the static box'
    shots=[e for e in events if e['kind']=='native_screenshot']
    assert len(shots)==3 and all(e['payload']['acknowledged'] for e in shots)
    images=list((path/'screenshots').rglob('*.png'));assert len(images)==3
    scan_path=path/'scan_snapshots.jsonl'
    scans=[json.loads(s) for s in scan_path.read_text().splitlines()] if scan_path.exists() else []
    for scan in scans:
        assert scan['frame_id']=='B1/base_scan' and len(scan['ranges'])==360
        assert sum(v is not None for v in scan['ranges'])>20
    infrastructure=json.loads((path.with_name(path.name+'_infra')/'shutdown.json').read_text())
    assert infrastructure['client_returncode']==0
    result={'status':'PASS','arrival_dwell_samples':len(window),'arrival_max_error_m':max(errors),
        'arrival_max_speed_mps':max(r['speed'] for r in window),'cancel_stop_samples':len(end_window),
        'cancel_last_second_max_speed_mps':max(r['speed'] for r in end_window),
        'maximum_pose_sample_gap_s':max(gaps),'minimum_center_to_box_distance_m':clearance,
        'native_screenshots':3,'laser_snapshots':len(scans),'initial_pose_seed_events':1,
        'limits':['single-robot AMCL/Nav2 acceptance; no multi-robot or mission-chain conclusion',
            'static-box center clearance is a geometric check, not a general contact/collision audit']}
    (path/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
    index=[{'file':str(p.relative_to(path)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
        'source':'unedited Gazebo native renderer output'} for p in sorted(images)]
    (path/'screenshot_index.json').write_text(json.dumps(index,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run_dir');audit(p.parse_args().run_dir)
