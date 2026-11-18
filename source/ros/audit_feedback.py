"""Check actual pose traces independently of the driver's own success flags."""
import argparse
import csv
import json
import math
from pathlib import Path


def audit(path):
    path=Path(path)
    events=[json.loads(x) for x in (path/'events.jsonl').read_text().splitlines()]
    metrics=json.loads((path/'metrics.json').read_text())
    with (path/'trajectory.csv').open() as stream:
        rows=[{**r,**{k:float(r[k]) for k in ('t_s','x','y','z','yaw','speed','wz')}} for r in csv.DictReader(stream)]
    assert metrics['status']=='PASS',metrics['failure']
    successes=[e for e in events if e['kind']=='phase_succeeded']
    assert [e['payload']['phase'] for e in successes]==['takeoff','turn','translate']
    checked=0
    for event in successes:
        end=event['payload']['finished_s']
        for actor in ('B1','B3'):
            window=[r for r in rows if r['actor']==actor and end-1.<=r['t_s']<=end]
            assert len(window)>=2 and window[-1]['t_s']-window[0]['t_s']>=.9,(actor,'dwell evidence missing')
            target=event['payload']['targets'][actor]
            for r in window:
                assert math.hypot(r['x']-target[0],r['y']-target[1])<=(.3 if actor=='B3' else .25)
                assert actor=='B1' or abs(r['z']-target[2])<=.2
                assert r['speed']<=.1 and abs(r['wz'])<=.1
                if actor=='B3' and event['payload']['phase'] in ('turn','translate'):
                    assert abs((r['yaw']-math.pi/2+math.pi)%(2*math.pi)-math.pi)<=.1
                checked+=1
    started=next(e['t_s'] for e in events if e['kind']=='phase_started' and e['payload']['phase']=='cancel_in_motion')
    cancelled=next(e for e in events if e['kind']=='cancel_requested')
    assert cancelled['t_s']-started>=1.,'cancel timer started before the new goal was issued'
    assert all(v>.1 for v in cancelled['payload']['speeds'].values()),'cancel test did not cancel moving robots'
    stopped=next(e for e in events if e['kind']=='cancel_settled')
    assert stopped['t_s']-cancelled['t_s']>=5.
    for actor,sample in stopped['payload']['samples'].items():
        assert sample['speed']<=.1
        assert math.dist(sample['xyz'],cancelled['payload']['positions'][actor])<=(.3 if actor=='B3' else .25)
    shots=[e for e in events if e['kind']=='native_screenshot_requested']
    assert len(shots)==5 and all(e['payload']['acknowledged'] for e in shots)
    assert len(list((path/'screenshots').rglob('*.png')))==5
    result={'status':'PASS','phases_checked':3,'settled_pose_checks':checked,
        'moving_cancel_after_s':cancelled['t_s']-started,'native_screenshots_checked':5,
        'limits':['low-level plant calibration only; no Nav2, sensing or mission-chain validation']}
    (path/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run_dir');audit(p.parse_args().run_dir)
