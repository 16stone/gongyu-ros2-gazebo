"""Development fleet episode using actual feedback and local policies."""
import json,math,os,signal,subprocess,threading,time,traceback
from dataclasses import asdict
from pathlib import Path
from collections import deque
import rclpy
from rclpy.qos import QoSProfile,DurabilityPolicy,ReliabilityPolicy,qos_profile_sensor_data
from rclpy.signals import SignalHandlerOptions
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan
from tf2_msgs.msg import TFMessage
from tf2_ros import Buffer
from gz.transport13 import Node as GzNode
from gz.msgs10.pose_v_pb2 import Pose_V
from gz.msgs10.world_stats_pb2 import WorldStatistics
from gongyu.actuation import MoveDispatcher
from gongyu.feedback import angle
from gongyu.feedback_time import sample_time,aligned_sample
from gongyu.physical_world import PhysicalWorld
from gongyu.onboard_sensing import OnboardFeedback
from gongyu.policies import controllers
from .entity_topology import EntityTopology
from gongyu.world import load_card
from .capture import capture_native
from .ground_adapter import Nav2GroundAdapter
from .fleet_runner import save_runtime_heartbeat
from .check_fleet_startup import check_localized_navigation,activate_localization


def check_interrupt(requested):
    if requested.is_set():raise KeyboardInterrupt


def fleet_actors(card):
    ground=[a for a,s in card['fleet'].items() if s['mode']=='ground'];air=[a for a,s in card['fleet'].items() if s['mode']=='air']
    expected_ground=({'B1','B2','R1','R2'},{'B1','B2','R1','R2','R3','R4'})
    if set(ground) not in expected_ground or set(air)!={'B3','R5'} or len(ground)+len(air)!=len(card['fleet']):
        raise ValueError('expected B1/B2/R1/R2 plus optional R3/R4 ground actors and B3/R5 air actors')
    return ground,air


def save_last_scans(out,scans):
    rows={topic:dict(frame_id=m.header.frame_id,stamp_s=m.header.stamp.sec+m.header.stamp.nanosec/1e9,
        angle_min=m.angle_min,angle_increment=m.angle_increment,range_min=m.range_min,range_max=m.range_max,
        ranges=[float(x) if math.isfinite(x) else None for x in m.ranges]) for topic,m in scans.items()}
    (out/'last_scans.json').write_text(json.dumps(rows,allow_nan=False))


def capture_failure_scene(screenshot,emit):
    try:screenshot('99_failure_after_stop')
    except Exception as exc:emit('referee','failure_screenshot_unavailable',dict(error=repr(exc)))


def stop_for_shutdown(adapters,air,publish,emit):
    errors=[]
    for actor in list(adapters)+list(air):
        try:
            if actor in adapters:adapters[actor].cancel()
            else:publish(actor,(0.,0.,0.,0.))
        except Exception as exc:
            errors.append(actor+': '+repr(exc));emit(actor,'shutdown_command_failed',dict(error=repr(exc)))
    return errors


def save_checkpoint(out,world,streams,offsets):
    for name,rows in streams.items():
        end=len(rows)
        with (out/(name+'.jsonl')).open('a') as f:
            f.write(''.join(json.dumps(e,default=asdict)+'\n' for e in rows[offsets.get(name,0):end]))
        offsets[name]=end
    temporary=out/'checkpoint.tmp'
    temporary.write_text(json.dumps(dict(status='PARTIAL_NOT_FINAL',mission_ms=world.now,mission=world.metrics())))
    temporary.replace(out/'checkpoint.json')


def run(out,scene,policy,feedback_mode=None):
    assert os.environ.get('ROS_DOMAIN_ID')=='83' and os.environ.get('GZ_PARTITION')=='gongyu_fleet_episode_20261030'
    out=Path(out);scene=Path(scene);out.mkdir(parents=True,exist_ok=False);card=load_card(scene/'scenario.json')
    # phase110 opt-in: registered cards carry no onboard_sensing key, so the
    # aircraft still receive the exact simulator pose by default.  When enabled
    # the referee sees an estimated state from a degraded onboard observation.
    sensing_cfg=card.get('onboard_sensing')
    mode=feedback_mode or ('sensed' if sensing_cfg else 'truth')
    if mode not in ('truth','sensed'):raise ValueError('unknown feedback mode: '+str(mode))
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO);node=rclpy.create_node('physical_fleet_episode',parameter_overrides=[rclpy.parameter.Parameter('use_sim_time',value=True)])
    stop_requested=threading.Event();previous_sigint=signal.signal(signal.SIGINT,lambda *_:stop_requested.set())
    checkpoint_offsets={};last_checkpoint=-10000
    ground,air=fleet_actors(card)
    onboard=OnboardFeedback(air,dict(sensing_cfg or {})) if mode=='sensed' else None
    sensed_cache={}
    buffers={a:Buffer() for a in ground};odom={};scans={};last_scans={};subs=[];log=[];raw=[];truth=[];airs={};history={a:deque(maxlen=40) for a in air};world_stats={};lock=threading.Lock()
    def emit(a,k,p):log.append(dict(actor=a,kind=k,payload=p,wall=time.monotonic()))
    durable=QoSProfile(depth=10,durability=DurabilityPolicy.TRANSIENT_LOCAL,reliability=ReliabilityPolicy.RELIABLE)
    for a in ground:
        def tf(msg,a=a,static=False):
            for t in msg.transforms:
                if static:buffers[a].set_transform_static(t,'actual_ros_'+a)
                else:buffers[a].set_transform(t,'actual_ros_'+a)
        subs.append(node.create_subscription(TFMessage,f'/{a}/tf',tf,100))
        subs.append(node.create_subscription(TFMessage,f'/{a}/tf_static',lambda m,a=a:tf(m,a,True),durable))
        subs.append(node.create_subscription(Odometry,f'/{a}/odom',lambda m,a=a:odom.update({a:(m,time.monotonic())}),qos_profile_sensor_data))
        def scan(m,a=a):
            scans[a+'/scan']=dict(stamp_s=0.,frame=m.header.frame_id);last_scans[a+'/scan']=m
        subs.append(node.create_subscription(LaserScan,f'/{a}/scan',scan,qos_profile_sensor_data))
        subs.append(node.create_subscription(LaserScan,f'/{a}/peer_scan',lambda m,a=a:last_scans.update({a+'/peer_scan':m}),qos_profile_sensor_data))
    adapters={a:Nav2GroundAdapter(node,a,lambda k,p,a=a:emit(a,k,p),through_bt=Path(scene)/'config/axial_transit.xml') for a in ground}
    pubs={a:node.create_publisher(Twist,f'/{a}/cmd_vel',10) for a in air}
    def publish(a,v):
        m=Twist();m.linear.x,m.linear.y,m.linear.z=v[:3];m.angular.z=v[3];pubs[a].publish(m)
    dispatcher=MoveDispatcher(card['fleet'],adapters,publish,card['physical_berth_tolerance_m'],emit);gz=GzNode()
    def pose(msg):
        t=msg.header.stamp.sec+msg.header.stamp.nsec/1e9
        with lock:
            for p in msg.pose:
                if p.name not in card['fleet']:continue
                xyz=(p.position.x,p.position.y,p.position.z);q=p.orientation;yaw=math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
                truth.append(dict(actor=p.name,t_s=t,xyz=xyz))
                if p.name in air:
                    old=airs.get(p.name);dt=t-old['t'] if old else 0.
                    airs[p.name]=dict(t=t,xyz=xyz,yaw=yaw,speed=math.dist(xyz,old['xyz'])/dt if dt>0 else 0.,wz=angle(yaw-old['yaw'])/dt if dt>0 else 0.,received_wall=time.monotonic())
                    history[p.name].append(airs[p.name])
    gz.subscribe(Pose_V,'/world/gongyu_mission/pose/info',pose)
    def stats(m):
        with lock:world_stats.update(paused=m.paused,sim_s=m.sim_time.sec+m.sim_time.nsec/1e9,iterations=m.iterations,received_wall=time.monotonic())
    gz.subscribe(WorldStatistics,'/world/gongyu_mission/stats',stats)
    def snapshot():
        check_interrupt(stop_requested)
        result={}
        now=node.get_clock().now().nanoseconds/1e9
        with lock:
            for a,rows in history.items():
                s=aligned_sample(rows,now)
                if s is not None and time.monotonic()-s['received_wall']<=.5:
                    if onboard is None:result[a]=dict(s);continue
                    key=(a,round(float(s['t']),6))
                    if key not in sensed_cache:sensed_cache[key]=onboard.feed(a,dict(s))
                    estimated=sensed_cache[key]
                    if estimated is None:continue   # a real observation dropout removes the fresh sample
                    result[a]=dict(estimated)
        for a,(m,wall) in odom.items():
            at=rclpy.time.Time(nanoseconds=max(0,node.get_clock().now().nanoseconds-100000000))
            if time.monotonic()-wall>.5 or not buffers[a].can_transform('map',a+'/base_footprint',at):continue
            tf=buffers[a].lookup_transform('map',a+'/base_footprint',at);absolute=m.header.stamp.sec*1000+m.header.stamp.nanosec//1000000
            tf_ms=tf.header.stamp.sec*1000+tf.header.stamp.nanosec//1000000;sampled=sample_time(absolute,tf_ms)
            if sampled is None:continue
            p,q=tf.transform.translation,tf.transform.rotation
            result[a]=dict(t=sampled/1000,xyz=(p.x,p.y,card['geometry']['heights']['ground']),yaw=math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z)),speed=math.hypot(m.twist.twist.linear.x,m.twist.twist.linear.y),wz=m.twist.twist.angular.z,odom_absolute_ms=absolute,tf_absolute_ms=tf_ms)
        return result
    def until(test,seconds,label):
        end=time.monotonic()+seconds;next_diagnostic=0.
        while True:
            check_interrupt(stop_requested)
            if time.monotonic()>=next_diagnostic:
                with lock:state=dict(world_stats)
                stamps={a:m.header.stamp.sec+m.header.stamp.nanosec/1e9 for a,(m,wall) in odom.items()}
                emit('referee','startup_stream_status',dict(gate=label,
                    missing_odom=[a for a in ground if a not in odom],
                    missing_scan=[a for a in ground if a+'/scan' not in scans],
                    missing_air=[a for a in air if a not in airs],
                    ros_clock_s=node.get_clock().now().nanoseconds/1e9,odom_stamp_s=stamps,
                    air_stamp_s={a:s['t'] for a,s in airs.items()},world_stats=state))
                next_diagnostic=time.monotonic()+1.
            if test():break
            if time.monotonic()>end:raise TimeoutError(label)
            rclpy.spin_once(node,timeout_sec=.03)
    def screenshot(label):
        return capture_native(out/'screenshots'/label,label,emit)
    world=None;failure=None;origin=None;localized=None;phase='startup';ended='not_started'
    entities=None;topology='shared';topology_receipt=None
    try:
        until(lambda:len(odom)==len(ground) and len(scans)==len(ground) and len(airs)==len(air) and node.get_clock().now().nanoseconds>0,60,'all actual sensor streams')
        activate_localization(node,ground,emit,lambda:check_interrupt(stop_requested))
        localized=check_localized_navigation(node,ground,scene,scans,lambda:check_interrupt(stop_requested))
        until(lambda:len(snapshot())==len(card['fleet']),15,'all configured fresh local feedback streams')
        phase='takeoff';started=time.monotonic();takeoff_sim_start=node.get_clock().now().nanoseconds/1e9
        for a in air:
            source=snapshot()[a]['xyz'];spec=card['fleet'][a];x,y=card['nodes'][spec['node']]
            z=card['geometry']['heights']['blue_air' if a.startswith('B') else 'red_air']
            dispatcher.begin(a,0,[source,(x,y,z)])
        while True:
            check_interrupt(stop_requested)
            rclpy.spin_once(node,timeout_sec=.02);now=node.get_clock().now().nanoseconds/1e9;ss=snapshot();dispatcher.tick(ss,now)
            if all(dispatcher.done(a,0) for a in air):break
            # Startup precedes the mission clock; rendering load must not consume the flight allowance.
            if time.monotonic()-started>240 or now-takeoff_sim_start>40:raise TimeoutError('both mission-height takeoffs')
        screenshot('00_six_ready_airborne' if len(card['fleet'])==6 else '00_eight_ready_airborne')
        until(lambda:len(snapshot())==len(card['fleet']),10,'feedback after screenshot')
        initial=snapshot();origin=node.get_clock().now().nanoseconds//1000000
        world=PhysicalWorld(card,out.name,dispatcher.begin,release_arrival=dispatcher.release_arrival);cs=controllers(card,policy)
        for a,s in initial.items():world.receive_pose(a,s['xyz'],s['speed'],s['wz'],round(s['t']*1000)-origin)
        assert all(world.fresh(a) and world.within(a,world.reference_position(a,card['fleet'][a]['node'])) for a in card['fleet']),'all configured initial physical regions must be ready'
        world.emit('referee','physical_all_ready',{'actors':list(initial),'origin_ms':origin})
        world.initialize_bookings()
        # GONGYU_TOPOLOGY=entities puts every decision maker in its own process.
        # The default (`shared`) executes the identical loop below, so a round that
        # does not set the switch is byte-identical to phase123.
        topology=os.environ.get('GONGYU_TOPOLOGY','shared').strip().lower()
        if topology not in ('shared','entities'):raise ValueError('unknown GONGYU_TOPOLOGY '+topology)
        if topology=='entities':
            entities=EntityTopology(card,policy,world).spawn()
            world.emit('referee','topology_declared',dict(topology='one process per entity',entities=len(entities.connections),wire='multiprocessing.Pipe',driver='ros.fleet_episode'))
            topology_receipt=entities.receipt()
        started=time.monotonic();last=-1;last_policy=-100;phase='mission';wall_limit=max(500,10*card['end_ms']/1000);last_heartbeat=0.  # 2026-11-10 harness-only: 10x wall budget; physics/rules unchanged
        while True:
            check_interrupt(stop_requested)
            rclpy.spin_once(node,timeout_sec=.02);absolute=node.get_clock().now().nanoseconds//1000000
            if time.monotonic()-last_heartbeat>=1.:
                save_runtime_heartbeat(out,absolute-origin);last_heartbeat=time.monotonic()
            if time.monotonic()-started>wall_limit:ended='wall_limit';break
            if absolute==last:continue
            last=absolute;ss=snapshot();dispatcher.tick(ss,absolute/1000);relative=absolute-origin;world.advance(relative)
            for a,s in ss.items():
                goal=world.moves[a]['token'] if a in world.moves else None
                world.receive_pose(a,s['xyz'],s['speed'],s['wz'],round(s['t']*1000)-origin,goal,dispatcher.done(a,goal))
                raw.append(dict(actor=a,mission_ms=relative,**s))
            if relative-last_policy>=card['step_ms']:
                if entities is None:
                    for a in sorted(cs):cs[a].step(world)
                else:
                    entities.tick(relative,relative//card['step_ms'])
                    topology_receipt=entities.receipt()
                last_policy=relative
            if relative-last_checkpoint>=10000:
                save_checkpoint(out,world,dict(driver_events=log,feedback=raw,independent_truth=truth,events=world.events,
                    decisions=world.decisions,diagnostics=world.diagnostics),checkpoint_offsets)
                last_checkpoint=relative
            if relative>=card['end_ms']:ended='full_window';break
            if time.monotonic()-started>wall_limit:ended='wall_limit';break
        screenshot('01_episode_end')
    except (Exception,KeyboardInterrupt) as exc:
        failure=repr(exc);ended='interrupted' if stop_requested.is_set() or isinstance(exc,KeyboardInterrupt) else 'error'
        emit('referee','episode_exception',dict(error=failure,stop_requested=stop_requested.is_set(),traceback=traceback.format_exc()))
    finally:
        if entities is not None:
            try:
                topology_receipt=entities.receipt()
                world.emit('referee','topology_requests',dict(topology_receipt))
                entities.close()
            except Exception as exc:emit('referee','topology_close_failed',dict(error=repr(exc)));failure=failure or repr(exc)
        if world:
            try:save_checkpoint(out,world,dict(driver_events=log,feedback=raw,independent_truth=truth,events=world.events,
                decisions=world.decisions,diagnostics=world.diagnostics),checkpoint_offsets)
            except Exception as exc:
                emit('referee','checkpoint_failed',dict(error=repr(exc)));failure=failure or repr(exc)
        stop_errors=stop_for_shutdown(adapters,air,publish,emit)
        if stop_errors:failure=failure or '; '.join(stop_errors)
        try:
            r=subprocess.run(['gz','service','-s','/world/gongyu_mission/control','--reqtype','gz.msgs.WorldControl','--reptype','gz.msgs.Boolean','--timeout','5000','--req','pause: true'],capture_output=True,text=True,timeout=8)
            emit('referee','shutdown_pause',dict(stdout=r.stdout))
            if 'data: true' not in r.stdout:failure=failure or 'shutdown pause not acknowledged'
        except Exception as exc:failure=failure or repr(exc)
        if failure:capture_failure_scene(screenshot,emit)
        try:save_last_scans(out,last_scans)
        except Exception as exc:emit('referee','scan_evidence_unavailable',dict(error=repr(exc)))
        try:
            gz.unsubscribe('/world/gongyu_mission/pose/info')
            gz.unsubscribe('/world/gongyu_mission/stats')
        except Exception as exc:
            emit('referee','shutdown_unsubscribe_failed',dict(error=repr(exc)));failure=failure or repr(exc)
        (out/'metrics.json').write_text(json.dumps(dict(status='FAIL' if failure else 'WINDOW_RECORDED',failure=failure,phase=phase,ended=ended,stop_signal_received=stop_requested.is_set(),origin_ms=origin,policy=policy,feedback_mode=mode,topology=dict(mode=topology,**(topology_receipt or {})),onboard_sensing=onboard.report() if onboard else None,localized=localized,mission=world.metrics() if world else None,limits=('Physical scenario timing and deadlines fixed before launch; symbolic payload/geometry sensing; aircraft use onboard observed+estimated state (simulator-derived, no hardware sensor)' if mode=='sensed' else 'Physical scenario timing and deadlines fixed before launch; symbolic payload/geometry sensing; aircraft use own simulator pose'),indent=2)))
        for name,values in (('driver_events',log),('feedback',raw),('independent_truth',truth)):(out/(name+'.jsonl')).write_text(''.join(json.dumps(e)+'\n' for e in values))
        if world:
            (out/'events.jsonl').write_text(''.join(json.dumps(asdict(e))+'\n' for e in world.events))
            (out/'decisions.json').write_text(json.dumps(world.decisions,indent=2))
            (out/'diagnostics.json').write_text(json.dumps(world.diagnostics,indent=2))
        node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
        signal.signal(signal.SIGINT,previous_sigint)
    if failure:raise RuntimeError(failure)


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('out');p.add_argument('scene');p.add_argument('--policy',default='P3');p.add_argument('--feedback-mode',choices=['truth','sensed']);a=p.parse_args();run(a.out,a.scene,a.policy,a.feedback_mode)
