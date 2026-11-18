"""One isolated fleet run with bounded monitoring and append-only evidence."""
import hashlib,json,os,signal,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path

LOCAL_DDS = """<CycloneDDS xmlns="https://cdds.io/config"><Domain id="any">
<General><MaxMessageSize>1400B</MaxMessageSize><FragmentSize>1100B</FragmentSize><Interfaces><NetworkInterface name="lo"/></Interfaces><AllowMulticast>false</AllowMulticast></General>
<Discovery><Peers><Peer Address="127.0.0.1"/></Peers><ParticipantIndex>auto</ParticipantIndex>
<MaxAutoParticipantIndex>110</MaxAutoParticipantIndex></Discovery>
</Domain></CycloneDDS>"""


def environment_for(scene,out):
    scene=Path(scene).resolve();out=Path(out).resolve()
    if out.exists():raise FileExistsError('use a new output directory: '+str(out))
    env=dict(os.environ,ROS_DOMAIN_ID='83',GZ_PARTITION='gongyu_fleet_episode_20261030',
        GZ_IP='127.0.0.1',GONGYU_FLEET_SCENE=str(scene),GONGYU_EPISODE_OUT=str(out),
        RMW_IMPLEMENTATION='rmw_cyclonedds_cpp',ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST',CYCLONEDDS_URI=LOCAL_DDS,
        MESA_LOADER_DRIVER_OVERRIDE='d3d12',GALLIUM_DRIVER='d3d12',MESA_D3D12_DEFAULT_ADAPTER_NAME='NVIDIA')
    for key in ('ROS_STATIC_PEERS','GONGYU_ACTIVE_GROUND'):env.pop(key,None)
    env.setdefault('GONGYU_MECH','joint')
    # "No GUI" is not "no GPU": GONGYU_HEADLESS already suppresses the GUI in
    # fleet.launch.py and the screenshot service in capture.py.  Dropping the Mesa
    # d3d12 adapter as well forces llvmpipe, which on WSL2 costs roughly 3x wall
    # time (1593-1830 s vs 548-563 s on amax-pi05 for the same card).  Callers that
    # want a headless round rendered on the local GPU set GONGYU_RENDER_GPU=1;
    # without it this branch is identical to phase123.
    if env.get('GONGYU_HEADLESS') == '1' and env.get('GONGYU_RENDER_GPU') != '1':
        for key in ('MESA_LOADER_DRIVER_OVERRIDE', 'GALLIUM_DRIVER', 'MESA_D3D12_DEFAULT_ADAPTER_NAME'):
            env.pop(key, None)
    return env


def update_progress(out,previous,last_wall,wall):
    path=Path(out)/'runtime_heartbeat.json'
    if not path.exists():path=Path(out)/'checkpoint.json'
    if not path.exists():return previous,last_wall
    current=json.loads(path.read_text())['mission_ms']
    if current!=previous:return current,wall
    if wall-last_wall>90:raise TimeoutError('mission clock/checkpoint stopped for 90 wall seconds at '+str(current))
    return previous,last_wall


def save_runtime_heartbeat(out,mission_ms):
    path=Path(out)/'runtime_heartbeat.tmp'
    path.write_text(json.dumps({'mission_ms':int(mission_ms),'wall_monotonic':time.monotonic()}))
    path.replace(Path(out)/'runtime_heartbeat.json')


def source_fingerprint(root):
    root=Path(root);revision='unknown'
    metadata=root/'SOURCE_REVISION.json'
    if metadata.exists():revision=json.loads(metadata.read_text())['revision']
    if (root/'.git').exists():
        try:revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True,stderr=subprocess.DEVNULL).strip()
        except (OSError,subprocess.CalledProcessError):pass
    hashes={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in ('gongyu','ros') for p in sorted((root/folder).rglob('*.py'))}
    return {'revision':revision,'sha256':hashes}


def is_fleet_process(argv,env):
    if any(x in ('ros.fleet_episode','ros.fleet_runner') or Path(x).name in ('_ros2_daemon','fleet.launch.py') for x in argv):return True
    if env.get('ROS_DOMAIN_ID')=='83' and any(x.startswith('/opt/ros/') for x in argv):return True
    return env.get('GZ_PARTITION')=='gongyu_fleet_episode_20261030' and 'sim' in argv


def capture_updates(out,offsets):
    for name in ('events.jsonl','driver_events.jsonl'):
        path=Path(out)/name
        if not path.exists():continue
        with path.open() as stream:
            stream.seek(offsets.get(name,0))
            while line:=stream.readline():
                if not line.endswith('\n'):break
                event=json.loads(line);offsets[name]=stream.tell()
                yield name,event


def live_owned_members(pgid):
    members=[]
    for entry in Path('/proc').glob('[0-9]*/stat'):
        try:fields=entry.read_text().rsplit(') ',1)[1].split()
        except (OSError,IndexError):continue
        if fields[0] not in ('Z','X') and int(fields[2])==pgid and int(fields[3])==pgid:
            members.append(int(entry.parent.name))
    return sorted(members)


def stop_owned(process):
    receipt={'pgid':process.pid,'signals':[]}
    if process.poll() is None and os.getpgid(process.pid)!=process.pid:raise RuntimeError('refusing a foreign process group')
    for sig,seconds in ((signal.SIGINT,20),(signal.SIGTERM,5),(signal.SIGKILL,2)):
        process.poll()
        if not live_owned_members(process.pid):break
        try:os.killpg(process.pid,sig)
        except ProcessLookupError:break
        receipt['signals'].append(int(sig));end=time.monotonic()+seconds
        while live_owned_members(process.pid) and time.monotonic()<end:
            process.poll();time.sleep(.05)
    receipt['final_members']=live_owned_members(process.pid)
    if receipt['final_members']:raise RuntimeError('owned processes survived cleanup: '+str(receipt))
    process.wait(timeout=2);receipt['returncode']=process.returncode
    return receipt


def capture_milestones(out):
    from .capture import capture_native
    out=Path(out);seen=set();offsets={};deadline=time.monotonic()+4200
    while time.monotonic()<deadline:
        for stream_name,event in capture_updates(out,offsets):
            kind=event['kind'];task=event.get('task_id');label=None
            if kind=='physical_arrival_granted':label='channel_approach_'+event['actor']
            elif kind=='red_route_decision' and event['actor']=='R1':label='R1_route_decision'
            elif kind=='delivery' and task in ('blue1','blue2','red1'):label=task+'_delivered'
            if label is None or label in seen:continue
            seen.add(label)
            def emit(actor,kind,payload):
                with (out/'capture_milestones.jsonl').open('a') as f:
                    f.write(json.dumps({'trigger_stream':stream_name,'trigger_event':event,
                        'capture_wall_utc':datetime.now(timezone.utc).isoformat(),
                        'kind':kind,'payload':payload,'scope':'Native scene captured after the saved event; not an exact-event-time frame'})+'\n')
            capture_native(out/'screenshots'/label,label,emit)
        if (out/'metrics.json').exists():break
        time.sleep(1)


def main(scene,out,policy,feedback_mode=None):
    from gongyu.world import load_card
    scene=Path(scene).resolve();out=Path(out).resolve();root=Path(__file__).resolve().parents[1]
    load_card(scene/'scenario.json')
    for rel in ('worlds/fleet.sdf','config/fleet.json','config/fleet_bridge.yaml'):
        if not (scene/rel).is_file():raise FileNotFoundError(scene/rel)
    # Do not join a stale or another user's fleet session; never kill it to make room.
    for path in Path('/proc').glob('[0-9]*/cmdline'):
        if int(path.parent.name)==os.getpid():continue
        try:
            argv=path.read_bytes().decode(errors='replace').split(chr(0))
            fields=(path.parent/'environ').read_bytes().decode(errors='replace').split(chr(0))
            process_env=dict(field.split('=',1) for field in fields if '=' in field)
        except OSError:continue
        if is_fleet_process(argv,process_env):
            raise RuntimeError('a conflicting fleet process is live; inspect PID '+path.parent.name)
    env=environment_for(scene,out);setup=out.parent/(out.name+'_launch');setup.mkdir(exist_ok=False,parents=True)
    children=[];failure=None;started=time.monotonic();previous=None;last_progress=started
    receipt={'started_utc':datetime.now(timezone.utc).isoformat(),'scene':str(scene),'out':str(out),'policy':policy,'feedback_mode':feedback_mode or 'truth',
        'source':source_fingerprint(root),
        'transport':{k:env[k] for k in ('ROS_DOMAIN_ID','ROS_AUTOMATIC_DISCOVERY_RANGE','CYCLONEDDS_URI','GZ_PARTITION')},'cleanup':[]}
    logs=[];stopping=False;cleaning_up=False
    def request_stop(signum,frame):
        nonlocal stopping
        if not stopping and not cleaning_up:
            stopping=True;raise KeyboardInterrupt('received signal '+str(signum))
    previous_handlers={sig:signal.signal(sig,request_stop) for sig in (signal.SIGINT,signal.SIGTERM)}
    try:
        for name,command in [('stack',['ros2','launch',str(root/'ros/fleet.launch.py')]),
            ('client',[sys.executable,'-m','ros.fleet_episode',str(out),str(scene),'--policy',policy]+(['--feedback-mode',feedback_mode] if feedback_mode else [])),
            ('capture',[sys.executable,'-m','ros.fleet_runner','--capture-only',str(out)])]:
            log=(setup/(name+'.log')).open('w');logs.append(log)
            process=subprocess.Popen(command,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            children.append((name,process));receipt[name+'_pid']=process.pid
            (setup/'live_run.json').write_text(json.dumps(receipt,indent=2))
        stack,client,capture=[p for _,p in children]
        while client.poll() is None:
            if stack.poll() is not None:raise RuntimeError('fleet launch exited before its client')
            if time.monotonic()-started>4200:raise TimeoutError('fleet run wall limit')
            previous,last_progress=update_progress(out,previous,last_progress,time.monotonic())
            time.sleep(1)
        if client.returncode:raise RuntimeError('fleet client exited '+str(client.returncode))
        metrics=json.loads((out/'metrics.json').read_text())
        if metrics['ended']!='full_window' or metrics['failure']:raise RuntimeError('incomplete physical window')
        try:receipt['capture_returncode']=capture.wait(timeout=45)
        except subprocess.TimeoutExpired:receipt['capture_wait_timed_out']=True
    except (Exception,KeyboardInterrupt) as exc:
        failure=repr(exc)
    finally:
        cleaning_up=True
        for name,process in reversed(children):
            try:receipt['cleanup'].append({'name':name,**stop_owned(process)})
            except Exception as exc:receipt['cleanup'].append({'name':name,'error':repr(exc)});failure=failure or repr(exc)
        for log in logs:log.close()
        receipt.update(ended_utc=datetime.now(timezone.utc).isoformat(),failure=failure,last_checkpoint_ms=previous,
            wall_seconds=time.monotonic()-started,status='FAIL' if failure else 'COMPLETE')
        (setup/'shutdown.json').write_text(json.dumps(receipt,indent=2))
        for sig,handler in previous_handlers.items():signal.signal(sig,handler)
    print(json.dumps(receipt),flush=True)
    if failure:raise SystemExit(1)


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--scene');p.add_argument('--out');p.add_argument('--policy',default='P3');p.add_argument('--feedback-mode',choices=['truth','sensed']);p.add_argument('--capture-only')
    a=p.parse_args()
    if a.capture_only:capture_milestones(a.capture_only)
    else:
        if not a.scene or not a.out:p.error('--scene and --out are required')
        main(a.scene,a.out,a.policy,a.feedback_mode)
