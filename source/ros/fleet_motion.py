"""Four short Nav2 goals; Gazebo truth is an independent acceptance observer."""
import csv,json,math,os,subprocess,threading,time
from pathlib import Path
import rclpy
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from gz.transport13 import Node as GzNode
from gz.msgs10.pose_v_pb2 import Pose_V
from .check_fleet_startup import check_localized_navigation
from .ground_adapter import Nav2GroundAdapter


def run(out,scene):
    assert os.environ.get('ROS_DOMAIN_ID')=='83' and os.environ.get('GZ_PARTITION')=='gongyu_fleet_nav_20261030'
    out=Path(out);out.mkdir(parents=True,exist_ok=False);actors=('B1','B2','R1','R2')
    rclpy.init();node=rclpy.create_node('fleet_motion_acceptance',parameter_overrides=[rclpy.parameter.Parameter('use_sim_time',value=True)]);seen={};subs=[];events=[];samples=[];truth={};lock=threading.Lock()
    def emit(actor,kind,payload):events.append(dict(wall=time.monotonic(),actor=actor,kind=kind,payload=payload))
    for actor in actors:
        def scan(msg,actor=actor):seen[actor+'/scan']=dict(stamp_s=0.,frame=msg.header.frame_id,samples=len(msg.ranges))
        subs.append(node.create_subscription(LaserScan,f'/{actor}/scan',scan,qos_profile_sensor_data))
    gz=GzNode()
    def poses(message):
        stamp=message.header.stamp.sec+message.header.stamp.nsec/1e9
        with lock:
            for p in message.pose:
                if p.name not in actors:continue
                previous=truth.get(p.name);xyz=(p.position.x,p.position.y,p.position.z)
                dt=stamp-previous['t_s'] if previous else 0.
                row=dict(actor=p.name,t_s=stamp,x=xyz[0],y=xyz[1],z=xyz[2],speed=math.dist(xyz,previous['xyz'])/dt if dt>0 else 0.,xyz=xyz)
                truth[p.name]=row;samples.append(row)
    gz.subscribe(Pose_V,'/world/gongyu_fleet/pose/info',poses)
    def until(test,seconds,label):
        end=time.monotonic()+seconds
        while not test():
            if time.monotonic()>end:raise TimeoutError(label)
            rclpy.spin_once(node,timeout_sec=.05)
    def screenshot(label):
        directory=(out/'screenshots'/label).resolve();directory.mkdir(parents=True)
        r=subprocess.run(['gz','service','-s','/gui/screenshot','--reqtype','gz.msgs.StringMsg','--reptype','gz.msgs.Boolean','--timeout','5000','--req','data: '+json.dumps(str(directory))],capture_output=True,text=True,timeout=8)
        emit('referee','native_screenshot',dict(label=label,stdout=r.stdout));assert 'data: true' in r.stdout
    adapters={a:Nav2GroundAdapter(node,a,lambda k,p,a=a:emit(a,k,p)) for a in actors}
    targets={'B1':(0.,1.,0.),'B2':(0.,-1.,0.),'R1':(4.,1.,math.pi),'R2':(4.,-1.,math.pi)}
    failure=None;localized=None;initial=None;final=None
    try:
        until(lambda:len(seen)==4 and len(truth)==4,45,'actual four scans and truth')
        for actor in actors:
            for attempt in range(3):
                state=subprocess.run(['ros2','service','call',f'/{actor}/amcl/get_state','lifecycle_msgs/srv/GetState','{}'],capture_output=True,text=True,timeout=25)
                emit(actor,'localization_actual_state',dict(stdout=state.stdout,attempt=attempt))
                if "id=3, label='active'" in state.stdout:break
                assert "id=1, label='unconfigured'" in state.stdout,state.stdout
                try:
                    r=subprocess.run(['ros2','service','call',f'/{actor}/lifecycle_manager_localization/manage_nodes','nav2_msgs/srv/ManageLifecycleNodes','{command: 0}'],capture_output=True,text=True,timeout=25)
                    emit(actor,'localization_startup',dict(stdout=r.stdout,stderr=r.stderr));assert 'success=True' in r.stdout
                    break
                except subprocess.TimeoutExpired as exc:emit(actor,'localization_request_timeout',dict(attempt=attempt,stdout=str(exc.stdout)))
            else:raise TimeoutError(actor+' localization did not activate')
        localized=check_localized_navigation(node,actors,Path(scene),seen)
        screenshot('00_four_localized')
        with lock:initial={a:dict(truth[a]) for a in actors}
        for a in actors:adapters[a].submit(*targets[a])
        until(lambda:all(a.state in ('SUCCEEDED_NAV2','ABORTED','REJECTED','RESULT_ERROR') for a in adapters.values()),100,'four navigation results')
        assert all(a.state=='SUCCEEDED_NAV2' for a in adapters.values()),{a:c.state for a,c in adapters.items()}
        settled={a:None for a in actors}
        def arrived():
            with lock:current={a:dict(truth[a]) for a in actors}
            for a,s in current.items():
                if math.hypot(s['x']-targets[a][0],s['y']-targets[a][1])>.25 or s['speed']>.1:settled[a]=None
                elif settled[a] is None:settled[a]=s['t_s']
            return all(settled[a] is not None and current[a]['t_s']-settled[a]>=1. for a in actors)
        until(arrived,20,'true-position one-second settled arrivals')
        with lock:final={a:dict(truth[a]) for a in actors}
        assert all(math.hypot(final[a]['x']-initial[a]['x'],final[a]['y']-initial[a]['y'])>.6 for a in actors)
        screenshot('01_four_arrived')
    except Exception as exc:
        failure=repr(exc)
        for a in adapters.values():a.cancel()
    finally:
        gz.unsubscribe('/world/gongyu_fleet/pose/info')
        (out/'metrics.json').write_text(json.dumps(dict(status='FAIL' if failure else 'PASS',failure=failure,localized=localized,initial=initial,final=final,targets=targets,states={a:c.state for a,c in adapters.items()},limits='Four short navigation goals only; no flight or shared mission acceptance'),indent=2))
        (out/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
        (out/'truth.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in samples))
        node.destroy_node();rclpy.shutdown()
    if failure:raise RuntimeError(failure)


if __name__=='__main__':
    import sys
    run(sys.argv[1],sys.argv[2])
