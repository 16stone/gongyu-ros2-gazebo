"""Two independent X3 position loops in the six-entity world, with raw feedback."""
import json,math,os,subprocess,threading,time
from pathlib import Path
from gz.transport13 import Node
from gz.msgs10.pose_v_pb2 import Pose_V
from gz.msgs10.twist_pb2 import Twist
from gongyu.feedback import PositionController,angle


def run(out):
    assert os.environ.get('GZ_PARTITION')=='gongyu_fleet_air_20261030'
    out=Path(out);out.mkdir(parents=True,exist_ok=False);node=Node();lock=threading.Lock()
    controls={a:PositionController('air') for a in ('B3','R5')};latest={};raw=[];events=[];outcomes=[]
    pubs={a:node.advertise(f'/{a}/gazebo/command/twist',Twist) for a in controls}
    def pose(message):
        stamp=message.header.stamp.sec+message.header.stamp.nsec/1e9
        with lock:
            for p in message.pose:
                if p.name not in controls:continue
                xyz=(p.position.x,p.position.y,p.position.z);q=p.orientation
                yaw=math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z));old=latest.get(p.name);dt=stamp-old['t'] if old else 0.
                s=dict(t=stamp,xyz=xyz,yaw=yaw,speed=math.dist(xyz,old['xyz'])/dt if dt>0 else 0.,wz=angle(yaw-old['yaw'])/dt if dt>0 else 0.,received_wall=time.monotonic())
                latest[p.name]=s;raw.append(dict(actor=p.name,**s))
    node.subscribe(Pose_V,'/world/gongyu_fleet/pose/info',pose)
    def request(service,typ,text):
        r=subprocess.run(['gz','service','-s',service,'--reqtype',typ,'--reptype','gz.msgs.Boolean','--timeout','5000','--req',text],capture_output=True,text=True,timeout=8)
        assert 'data: true' in r.stdout,(service,r.stdout,r.stderr)
    def pause(value):request('/world/gongyu_fleet/control','gz.msgs.WorldControl','pause: '+str(value).lower())
    def screenshot(label):
        pause(True);directory=(out/'screenshots'/label).resolve();directory.mkdir(parents=True)
        request('/gui/screenshot','gz.msgs.StringMsg','data: '+json.dumps(str(directory)))
        pause(False)
    failure=None;phase='takeoff';started=time.monotonic();phase_at=0.;cancel_positions=None;phase_pending=True
    try:
        while len(latest)<2:
            if time.monotonic()-started>15:raise TimeoutError('two real X3 poses')
            time.sleep(.02)
        for a,c in controls.items():c.set_target((1. if a=='B3' else 3.,-2.,1.5))
        assert max(s['t'] for s in latest.values())<=.1,'fresh paused world required'
        screenshot('00_initial');pause(False)
        while True:
            with lock:samples={a:dict(s) for a,s in latest.items()}
            stamp=max(s['t'] for s in samples.values())
            if time.monotonic()-started>150 or stamp-phase_at>40:raise TimeoutError(phase)
            for a,c in controls.items():
                assert time.monotonic()-samples[a]['received_wall']<1.,'stale wall feedback'
                values=c.command(samples[a],stamp);m=Twist();m.linear.x,m.linear.y,m.linear.z=values[:3];m.angular.z=values[3];pubs[a].publish(m)
            if phase_pending:
                phase_at=stamp;phase_pending=False
                events.append(dict(kind='goal_started',phase=phase,t_s=stamp,targets={a:c.target for a,c in controls.items()}))
            if phase in ('takeoff','translate') and all(c.state=='SUCCEEDED' for c in controls.values()):
                outcomes.append(dict(phase=phase,t_s=stamp,samples=samples,targets={a:c.target for a,c in controls.items()}));screenshot('01_'+phase)
                if phase=='takeoff':
                    for a,c in controls.items():c.set_target((1. if a=='B3' else 3.,0.,1.5))
                    phase='translate'
                else:
                    for a,c in controls.items():c.set_target((1. if a=='B3' else 3.,-2.,1.5))
                    phase='cancel_in_motion'
                phase_pending=True
            elif phase=='cancel_in_motion' and stamp-phase_at>=1.:
                cancel_positions={a:s['xyz'] for a,s in samples.items()}
                for a,c in controls.items():c.cancel(samples[a])
                events.append(dict(kind='cancel_requested',t_s=stamp,goal_started_s=phase_at,elapsed_s=stamp-phase_at,positions=cancel_positions))
                phase='cancel_hold';phase_at=stamp
            elif phase=='cancel_hold' and stamp-phase_at>=5.:
                assert all(c.state=='CANCELLED' and samples[a]['speed']<=.1 and math.dist(samples[a]['xyz'],cancel_positions[a])<=.3 for a,c in controls.items())
                outcomes.append(dict(phase=phase,t_s=stamp,samples=samples,cancel_positions=cancel_positions));screenshot('03_cancel_hold');break
            time.sleep(.02)
    except Exception as exc:failure=repr(exc)
    finally:
        try:pause(True)
        except Exception as exc:failure=failure or repr(exc)
        node.unsubscribe('/world/gongyu_fleet/pose/info')
        (out/'pose_samples.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in raw))
        (out/'events.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in events))
        (out/'metrics.json').write_text(json.dumps(dict(status='FAIL' if failure else 'PASS',failure=failure,outcomes=outcomes,scope='Two X3 low-level position loops; simulator pose feedback; no onboard localization or mission integration'),indent=2))
    if failure:raise RuntimeError(failure)


if __name__=='__main__':
    import sys
    run(sys.argv[1])
