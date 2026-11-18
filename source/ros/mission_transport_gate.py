"""Actual R1 Nav2 -> shared PhysicalWorld transport and unload integration gate."""
import json,math,os,subprocess,time,threading
from pathlib import Path
import rclpy
from rclpy.qos import QoSProfile,DurabilityPolicy,ReliabilityPolicy,qos_profile_sensor_data
from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan
from tf2_msgs.msg import TFMessage
from tf2_ros import Buffer
from gz.transport13 import Node as GzNode
from gz.msgs10.pose_v_pb2 import Pose_V
from gongyu.physical_world import PhysicalWorld
from gongyu.policies import Controller
from gongyu.world import load_card
from gongyu.feedback_time import sample_time
from gongyu.actuation import MoveDispatcher
from .ground_adapter import Nav2GroundAdapter
from .check_fleet_startup import check_localized_navigation


def run(out,scene):
    assert os.environ.get('ROS_DOMAIN_ID')=='83' and os.environ.get('GZ_PARTITION')=='gongyu_mission_gate_20261030'
    out=Path(out);scene=Path(scene);out.mkdir(parents=True,exist_ok=False)
    card=load_card(scene/'scenario.json');rclpy.init()
    node=rclpy.create_node('mission_transport_gate',parameter_overrides=[rclpy.parameter.Parameter('use_sim_time',value=True)])
    buffer=Buffer();odom={};scans={};log=[];raw=[];truth=[];lock=threading.Lock();subs=[]
    def emit(k,p):log.append(dict(kind=k,payload=p,wall=time.monotonic()))
    adapter=Nav2GroundAdapter(node,'R1',emit);token=None;world=None;failure=None;localized=None;origin_ms=None
    dispatcher=MoveDispatcher({'R1':card['fleet']['R1']},{'R1':adapter},lambda *args:None,card['physical_berth_tolerance_m'],lambda a,k,p:emit(k,dict(actor=a,**p)))
    def tf(msg,static=False):
        for t in msg.transforms:
            if static:buffer.set_transform_static(t,'actual_ros_R1')
            else:buffer.set_transform(t,'actual_ros_R1')
    durable=QoSProfile(depth=10,durability=DurabilityPolicy.TRANSIENT_LOCAL,reliability=ReliabilityPolicy.RELIABLE)
    subs.append(node.create_subscription(TFMessage,'/R1/tf',tf,100))
    subs.append(node.create_subscription(TFMessage,'/R1/tf_static',lambda m:tf(m,True),durable))
    subs.append(node.create_subscription(Odometry,'/R1/odom',lambda m:odom.update(msg=m,wall=time.monotonic()),qos_profile_sensor_data))
    subs.append(node.create_subscription(LaserScan,'/R1/scan',lambda m:scans.update({'R1/scan':dict(stamp_s=0.,frame=m.header.frame_id)}),qos_profile_sensor_data))
    gz=GzNode()
    def actual(msg):
        stamp=msg.header.stamp.sec+msg.header.stamp.nsec/1e9
        with lock:
            for p in msg.pose:
                if p.name=='R1':truth.append(dict(t_s=stamp,xyz=[p.position.x,p.position.y,p.position.z]))
    gz.subscribe(Pose_V,'/world/gongyu_mission/pose/info',actual)
    def until(test,seconds,label):
        end=time.monotonic()+seconds
        while not test():
            if time.monotonic()>end:raise TimeoutError(label)
            rclpy.spin_once(node,timeout_sec=.05)
    def screenshot(label):
        directory=(out/'screenshots'/label).resolve();directory.mkdir(parents=True)
        r=subprocess.run(['gz','service','-s','/gui/screenshot','--reqtype','gz.msgs.StringMsg','--reptype','gz.msgs.Boolean','--timeout','5000','--req','data: '+json.dumps(str(directory))],capture_output=True,text=True,timeout=8)
        emit('native_screenshot',dict(label=label,stdout=r.stdout));assert 'data: true' in r.stdout
    def submit(actor,goal_id,points):
        nonlocal token
        assert actor=='R1'
        token=goal_id;dispatcher.begin(actor,goal_id,points)
    try:
        until(lambda:bool(odom) and bool(scans),45,'R1 scan and odometry')
        for attempt in range(3):
            r=subprocess.run(['ros2','service','call','/R1/amcl/get_state','lifecycle_msgs/srv/GetState','{}'],capture_output=True,text=True,timeout=25)
            emit('localization_state',dict(stdout=r.stdout))
            if "id=3, label='active'" in r.stdout:break
            assert "id=1, label='unconfigured'" in r.stdout,r.stdout
            try:
                r=subprocess.run(['ros2','service','call','/R1/lifecycle_manager_localization/manage_nodes','nav2_msgs/srv/ManageLifecycleNodes','{command: 0}'],capture_output=True,text=True,timeout=25)
                emit('localization_startup',dict(stdout=r.stdout));assert 'success=True' in r.stdout;break
            except subprocess.TimeoutExpired:emit('startup_timeout',dict(attempt=attempt))
        else:raise TimeoutError('R1 localization startup')
        localized=check_localized_navigation(node,('R1',),scene,scans)
        until(lambda:buffer.can_transform('map','R1/base_footprint',rclpy.time.Time()),10,'actual map-base transform')
        screenshot('00_localized_before_mission')
        until(lambda:time.monotonic()-odom['wall']<.1,5,'fresh odometry after screenshot callback pause')
        origin_ms=None;last_sample=-1;started=time.monotonic();controller=Controller('R1',[('move','W'),('move','D'),('unload','red1')])
        world=PhysicalWorld(card,out.name,submit)
        while 'red1' not in world.completed:
            rclpy.spin_once(node,timeout_sec=.02)
            if time.monotonic()-started>210:raise TimeoutError('transport gate')
            if time.monotonic()-odom['wall']>.5:raise RuntimeError('odometry lost')
            msg=odom['msg'];absolute=msg.header.stamp.sec*1000+msg.header.stamp.nanosec//1000000
            if origin_ms is None:origin_ms=absolute
            stamp=absolute-origin_ms
            if stamp<=last_sample:continue
            last_sample=stamp;world.advance(stamp)
            transform=buffer.lookup_transform('map','R1/base_footprint',rclpy.time.Time())
            tf_absolute=transform.header.stamp.sec*1000+transform.header.stamp.nanosec//1000000
            sampled=sample_time(absolute,tf_absolute)
            if sampled is None:continue
            t=transform.transform.translation;xyz=(t.x,t.y,card['geometry']['heights']['ground'])
            speed=math.hypot(msg.twist.twist.linear.x,msg.twist.twist.linear.y);wz=msg.twist.twist.angular.z
            raw.append(dict(t_ms=stamp,odom_absolute_ms=absolute,tf_absolute_ms=tf_absolute,sampled_ms=sampled-origin_ms,xyz=xyz,speed=speed,wz=wz,goal_id=token,nav_state=adapter.state))
            dispatcher.tick({'R1':dict(xyz=xyz,t=sampled/1000,speed=speed,wz=wz,yaw=0.)},absolute/1000)
            current=token if 'R1' in world.moves else None
            world.receive_pose('R1',xyz,speed,wz,sampled-origin_ms,current,dispatcher.done('R1',token))
            controller.step(world)
        screenshot('01_actual_unload_complete')
        assert not world.violations
    except (Exception,KeyboardInterrupt) as exc:
        failure=repr(exc);adapter.cancel()
    finally:
        gz.unsubscribe('/world/gongyu_mission/pose/info')
        (out/'metrics.json').write_text(json.dumps(dict(status='FAIL' if failure else 'PASS',failure=failure,origin_ms=origin_ms,localized=localized,mission=world.metrics() if world else None,scope='R1 transport integration only; other entities parked; no policy comparison'),indent=2))
        (out/'adapter_events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in log))
        (out/'feedback.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in raw))
        with lock:(out/'independent_truth.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in truth))
        if world:
            from dataclasses import asdict
            (out/'events.jsonl').write_text(''.join(json.dumps(asdict(e))+'\n' for e in world.events))
        node.destroy_node();rclpy.shutdown()
    if failure:raise RuntimeError(failure)


if __name__=='__main__':
    import sys
    run(sys.argv[1],sys.argv[2])
