"""One-car/one-aircraft calibration using actual Gazebo pose feedback.

This deliberately bypasses Nav2/localization; it verifies the low-level plant,
body-frame air outer loop and settled/cancel feedback before those integrations.
"""
import argparse
import csv
import hashlib
import json
import math
import os
import subprocess
import threading
import time
from datetime import datetime,timezone
from pathlib import Path
from google.protobuf import text_format

from gz.transport13 import Node
from gz.msgs10.boolean_pb2 import Boolean
from gz.msgs10.pose_v_pb2 import Pose_V
from gz.msgs10.stringmsg_pb2 import StringMsg
from gz.msgs10.twist_pb2 import Twist
from gz.msgs10.world_control_pb2 import WorldControl

from gongyu.feedback import PositionController,angle


def run(out):
    if os.environ.get('GZ_PARTITION')!='gongyu_feedback_20261029' or os.environ.get('GZ_IP')!='127.0.0.1':
        raise RuntimeError('the dedicated calibration partition is required')
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    node=Node();lock=threading.Lock();latest={};rows=[];raw=[];events=[]
    controls={'B1':PositionController('ground'),'B3':PositionController('air')}
    pubs={a:node.advertise('/B1/cmd_vel' if a=='B1' else '/B3/gazebo/command/twist',Twist) for a in controls}
    started=datetime.now(timezone.utc).isoformat()

    def on_pose(message):
        stamp=message.header.stamp.sec+message.header.stamp.nsec/1e9
        for pose in message.pose:
            if pose.name not in controls:
                continue
            p,q=pose.position,pose.orientation
            xyz=(p.x,p.y,p.z)
            yaw=math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
            with lock:
                previous=latest.get(pose.name);dt=stamp-previous['t'] if previous else 0.
                speed=math.dist(xyz,previous['xyz'])/dt if dt>0 else 0.
                wz=angle(yaw-previous['yaw'])/dt if dt>0 else 0.
                sample={'t':stamp,'xyz':xyz,'yaw':yaw,'speed':speed,'wz':wz,'received_wall':time.monotonic()}
                latest[pose.name]=sample
                rows.append({'t_s':stamp,'actor':pose.name,'x':p.x,'y':p.y,'z':p.z,
                    'yaw':yaw,'speed':speed,'wz':wz})
                raw.append({'t_s':stamp,'name':pose.name,'position':list(xyz),
                    'quaternion':[q.x,q.y,q.z,q.w]})

    node.subscribe(Pose_V,'/world/gongyu_feedback/pose/info',on_pose)

    def request_service(service,message):
        # A separate client keeps blocking requests independent of the Python pose subscriber.
        reply=subprocess.run(['gz','service','-s',service,'--reqtype',message.DESCRIPTOR.full_name,
            '--reptype','gz.msgs.Boolean','--timeout','5000','--req',text_format.MessageToString(message)],
            capture_output=True,text=True,timeout=9,check=True)
        response=Boolean()
        text_format.Parse(reply.stdout,response)
        return response.data

    def world_pause(value):
        if not request_service('/world/gongyu_feedback/control',WorldControl(pause=value)):
            raise RuntimeError('world control was not acknowledged')

    def emit(kind,payload):
        with lock:
            stamp=max((s['t'] for s in latest.values()),default=0.)
        events.append({'t_s':stamp,'kind':kind,'payload':payload})
        print(json.dumps(events[-1]),flush=True)
        return stamp

    def screenshot(label,resume=True):
        world_pause(True)
        directory=out/'screenshots'/label;directory.mkdir(parents=True)
        acknowledged=request_service('/gui/screenshot',StringMsg(data=str(directory)))
        emit('native_screenshot_requested',{'label':label,'acknowledged':acknowledged})
        if not acknowledged:
            raise RuntimeError('native screenshot was not acknowledged')
        if resume:
            world_pause(False)

    def publish(actor,values):
        message=Twist();message.linear.x,message.linear.y,message.linear.z=values[:3]
        message.angular.z=values[3];pubs[actor].publish(message)

    phase='takeoff';phase_started=0.;failure=None;cancel_positions={};outcomes=[]
    try:
        wait_start=time.monotonic()
        while len(latest)<2:
            if time.monotonic()-wait_start>10:
                raise RuntimeError('both real model poses are required before control')
            time.sleep(.02)
        with lock:
            initial={a:dict(s) for a,s in latest.items()}
        if max(s['t'] for s in initial.values())>.1:
            raise RuntimeError('calibration requires a freshly started paused world')
        ground_z=initial['B1']['xyz'][2]
        controls['B1'].set_target((0.,2.,ground_z))
        controls['B3'].set_target((0.,-2.,1.5))
        for actor in controls:
            publish(actor,(0.,0.,0.,0.))
        emit('phase_started',{'phase':phase,'targets':{a:c.target for a,c in controls.items()}})
        screenshot('00_initial_paused',resume=False)
        world_pause(False);wall_start=time.monotonic()
        while True:
            with lock:
                samples={a:dict(s) for a,s in latest.items()}
            stamp=max(s['t'] for s in samples.values())
            if time.monotonic()-wall_start>150 or stamp-phase_started>35:
                raise RuntimeError('motion/feedback timeout in '+phase)
            for actor,c in controls.items():
                if time.monotonic()-samples[actor]['received_wall']>.5:
                    raise RuntimeError('feedback stopped for '+actor)
                publish(actor,c.command(samples[actor],stamp))
            if phase in ('takeoff','turn','translate') and all(c.state=='SUCCEEDED' for c in controls.values()):
                outcome={'phase':phase,'finished_s':stamp,'samples':samples,
                    'targets':{a:c.target for a,c in controls.items()}}
                outcomes.append(outcome);emit('phase_succeeded',outcome)
                screenshot('01_'+phase)
                if phase=='takeoff':
                    phase='turn';controls['B3'].set_target((0.,-2.,1.5),yaw=math.pi/2)
                elif phase=='turn':
                    phase='translate'
                    controls['B1'].set_target((3.,2.,ground_z))
                    controls['B3'].set_target((2.,-2.,1.5),yaw=math.pi/2)
                else:
                    phase='cancel_in_motion'
                    controls['B1'].set_target((5.,2.,ground_z))
                    controls['B3'].set_target((4.,-2.,1.5),yaw=math.pi/2)
                phase_started=emit('phase_started',{'phase':phase,'targets':{a:c.target for a,c in controls.items()}})
            elif phase=='cancel_in_motion' and stamp-phase_started>=1.:
                cancel_positions={a:s['xyz'] for a,s in samples.items()}
                for actor,c in controls.items():
                    c.cancel(samples[actor])
                phase_started=emit('cancel_requested',{'positions':cancel_positions,
                    'speeds':{a:s['speed'] for a,s in samples.items()}})
                phase='cancel_hold'
            elif phase=='cancel_hold' and stamp-phase_started>=5.:
                for actor,c in controls.items():
                    assert c.state=='CANCELLED','cancel was relabelled as successful arrival'
                    assert samples[actor]['speed']<=.1,(actor,'not stopped',samples[actor])
                    limit=.3 if actor=='B3' else .25
                    assert math.dist(samples[actor]['xyz'],cancel_positions[actor])<=limit,(actor,'excess cancellation displacement')
                emit('cancel_settled',{'samples':samples,'cancel_positions':cancel_positions})
                screenshot('04_cancel_settled',resume=False)
                break
            time.sleep(.02)
    except Exception as exc:
        failure=repr(exc);emit('calibration_failed',{'reason':failure,'phase':phase})
    finally:
        for actor in controls:
            publish(actor,(0.,0.,0.,0.))
        try:
            world_pause(True)
        except Exception as exc:
            failure=failure or repr(exc)
        node.unsubscribe('/world/gongyu_feedback/pose/info')
        pubs.clear()
        with lock:
            final={a:dict(s) for a,s in latest.items()};saved_rows=list(rows);saved_raw=list(raw)
        (out/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
        (out/'pose_samples.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in saved_raw))
        if saved_rows:
            with (out/'trajectory.csv').open('w',newline='') as f:
                writer=csv.DictWriter(f,list(saved_rows[0]));writer.writeheader();writer.writerows(saved_rows)
        metrics={'status':'PASS' if failure is None else 'FAIL','failure':failure,'last_phase':phase,
            'outcomes':outcomes,'final':final,'cancel_positions':cancel_positions,
            'pose_sample_count':len(saved_rows),
            'limits':['low-level Gazebo plant calibration only; no Nav2 or localization',
                'controllers consume simulator world poses; no sensor state estimation claim',
                'no mission, communication, six/eight robots or general collision validation']}
        (out/'metrics.json').write_text(json.dumps(metrics,indent=2)+'\n')
        source=Path(__file__).resolve().parents[1]
        files=[Path(__file__),source/'gongyu/feedback.py',source/'ros/worlds/feedback.sdf']
        manifest={'started_at':started,'finished_at':datetime.now(timezone.utc).isoformat(),
            'backend':'gazebo_sim_8.15.0','partition':os.environ['GZ_PARTITION'],
            'code_revision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
            'code_dirty':bool(subprocess.check_output(['git','diff','HEAD','--name-only'],text=True).strip()),
            'source_sha256':{str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
            'pose_topic':'/world/gongyu_feedback/pose/info','feedback':'simulator world pose; speed derived from consecutive poses'}
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    del node
    print(json.dumps({'status':metrics['status'],'failure':failure,'output':str(out)}),flush=True)
    if failure:
        raise SystemExit(1)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
