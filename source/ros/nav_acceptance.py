"""Actual single-robot localization, obstacle navigation and cancel acceptance."""
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

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav_msgs.msg import Odometry,OccupancyGrid,Path as NavPath
from nav2_msgs.srv import ManageLifecycleNodes
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data,QoSProfile,DurabilityPolicy,ReliabilityPolicy
from sensor_msgs.msg import LaserScan
from tf2_ros import Buffer,TransformListener
from gz.transport13 import Node as GzNode
from gz.msgs10.pose_v_pb2 import Pose_V

from .ground_adapter import Nav2GroundAdapter


def run(out):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    if os.environ.get('ROS_DOMAIN_ID')!='82' or os.environ.get('GZ_PARTITION')!='gongyu_nav_20261029':
        raise RuntimeError('dedicated navigation domain and partition required')
    started=datetime.now(timezone.utc).isoformat()
    rclpy.init();node=Node('nav_acceptance',namespace='B1',
        parameter_overrides=[rclpy.parameter.Parameter('use_sim_time',value=True)],
        cli_args=['--ros-args','-r','/tf:=/B1/tf','-r','/tf_static:=/B1/tf_static'])
    events=[];samples=[];amcl=[];plans=[];scans=[];inbox={};lock=threading.Lock();truth=None
    gz=GzNode()

    def emit(kind,payload):
        with lock:
            observed_time=truth['t_s'] if truth else 0.
        stamp=max(node.get_clock().now().nanoseconds/1e9,observed_time)
        event={'t_s':stamp,'kind':kind,'payload':payload};events.append(event)
        if kind!='navigation_feedback':
            print(json.dumps(event),flush=True)

    def on_truth(message):
        nonlocal truth
        stamp=message.header.stamp.sec+message.header.stamp.nsec/1e9
        for p in message.pose:
            if p.name!='B1':
                continue
            with lock:
                dt=stamp-truth['t_s'] if truth else 0.
                speed=math.hypot(p.position.x-truth['x'],p.position.y-truth['y'])/dt if dt>0 else 0.
                truth={'t_s':stamp,'x':p.position.x,'y':p.position.y,'z':p.position.z,'speed':speed}
                samples.append(dict(truth))

    gz.subscribe(Pose_V,'/world/gongyu_nav/pose/info',on_truth)
    for topic,kind in (('scan',LaserScan),('peer_scan',LaserScan),('odom',Odometry)):
        node.create_subscription(kind,topic,lambda m,key=topic:inbox.update({key:m}),qos_profile_sensor_data)
    node.create_subscription(PoseWithCovarianceStamped,'amcl_pose',lambda m:amcl.append({
        't_s':m.header.stamp.sec+m.header.stamp.nanosec/1e9,'x':m.pose.pose.position.x,'y':m.pose.pose.position.y}),10)
    node.create_subscription(NavPath,'plan',lambda m:plans.append({'t_s':node.get_clock().now().nanoseconds/1e9,
        'points':[[p.pose.position.x,p.pose.position.y] for p in m.poses]}),10)
    map_qos=QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL,reliability=ReliabilityPolicy.RELIABLE)
    node.create_subscription(OccupancyGrid,'map',lambda m:inbox.update({'map':m}),map_qos)
    buffer=Buffer();listener=TransformListener(buffer,node)
    adapter=Nav2GroundAdapter(node,'B1',emit)

    def until(predicate,seconds,label):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            rclpy.spin_once(node,timeout_sec=.05)
            if predicate():
                return
        raise RuntimeError('timeout: '+label)

    def startup(manager):
        client=node.create_client(ManageLifecycleNodes,manager+'/manage_nodes')
        until(lambda:client.service_is_ready(),40,manager+' service')
        request=ManageLifecycleNodes.Request();request.command=request.STARTUP
        future=client.call_async(request);until(future.done,60,manager+' startup')
        if not future.result().success:
            raise RuntimeError('lifecycle startup failed: '+manager)
        emit('lifecycle_started',{'manager':manager})

    def screenshot(label):
        scan=inbox['scan']
        scans.append({'label':label,'stamp_s':scan.header.stamp.sec+scan.header.stamp.nanosec/1e9,
            'frame_id':scan.header.frame_id,'angle_min':scan.angle_min,'angle_increment':scan.angle_increment,
            'range_min':scan.range_min,'range_max':scan.range_max,
            'ranges':[float(r) if math.isfinite(r) else None for r in scan.ranges]})
        directory=out/'screenshots'/label;directory.mkdir(parents=True)
        command=['gz','service','-s','/gui/screenshot','--reqtype','gz.msgs.StringMsg',
            '--reptype','gz.msgs.Boolean','--timeout','5000','--req','data: '+json.dumps(str(directory))]
        result=subprocess.run(command,capture_output=True,text=True,timeout=9)
        ok=result.returncode==0 and 'data: true' in result.stdout
        emit('native_screenshot',{'label':label,'acknowledged':ok})
        if not ok:
            raise RuntimeError('native screenshot not acknowledged')

    failure=None;arrival=None;cancelled=None;checks={}
    try:
        until(lambda:node.get_clock().now().nanoseconds>0 and all(k in inbox for k in ('scan','peer_scan','odom')) and truth is not None and truth['t_s']>0,45,'real clock/laser/odom/timestamped pose')
        checks['scan_samples']=len(inbox['scan'].ranges)
        checks['scan_frame']=inbox['scan'].header.frame_id
        assert checks['scan_samples']>=360 and checks['scan_frame']=='B1/base_scan'
        startup('lifecycle_manager_localization')
        until(lambda:'map' in inbox,20,'occupancy map')
        initial=node.create_publisher(PoseWithCovarianceStamped,'initialpose',10)
        pose=PoseWithCovarianceStamped();pose.header.frame_id='map'
        pose.header.stamp=node.get_clock().now().to_msg();pose.pose.pose.position.y=2.
        pose.pose.pose.orientation.w=1.
        pose.pose.covariance[0]=.05**2;pose.pose.covariance[7]=.05**2;pose.pose.covariance[35]=.05**2
        until(lambda:initial.get_subscription_count()>0,10,'initial-pose subscriber')
        initial.publish(pose);emit('initial_pose_seeded',{'pose':[0.,2.,0.],'count':1})
        until(lambda:bool(amcl) and buffer.can_transform('map','B1/base_footprint',rclpy.time.Time()),30,'AMCL and map-to-base TF')
        checks['initial_amcl_pose']=amcl[-1]
        transform=buffer.lookup_transform('map','B1/base_footprint',rclpy.time.Time())
        checks['map_to_base_tf']={'parent':transform.header.frame_id,'child':transform.child_frame_id,
            'x':transform.transform.translation.x,'y':transform.transform.translation.y}
        startup('lifecycle_manager_navigation')
        until(lambda:adapter.client.server_is_ready(),30,'NavigateToPose action server')
        screenshot('00_localized')
        until(lambda:node.get_clock().now().nanoseconds/1e9>=truth['t_s']-.05,5,'ROS clock after screenshot')
        adapter.submit(4.,2.,0.)
        until(lambda:adapter.state not in ('REQUESTED','ACTIVE'),120,'first navigation result')
        assert adapter.state=='SUCCEEDED_NAV2',adapter.state
        settled_since=None
        def physically_arrived():
            nonlocal settled_since
            with lock:
                s=dict(truth)
            valid=math.hypot(s['x']-4.,s['y']-2.)<=.25 and s['speed']<=.1
            if not valid:
                settled_since=None
            elif settled_since is None:
                settled_since=s['t_s']
            return settled_since is not None and s['t_s']-settled_since>=1.
        until(physically_arrived,15,'independent true-position settled arrival')
        arrival=dict(truth);emit('physical_arrival_confirmed',arrival)
        screenshot('01_arrived_after_detour')
        until(lambda:node.get_clock().now().nanoseconds/1e9>=truth['t_s']-.05,5,'ROS clock after screenshot')
        adapter.submit(0.,2.,0.)
        until(lambda:adapter.state=='ACTIVE' and truth['speed']>.12,30,'return goal actually moving')
        cancelled=dict(truth);assert adapter.cancel()
        until(lambda:adapter.state in ('CANCELED','ABORTED','SUCCEEDED_NAV2'),20,'actual cancel terminal result')
        assert adapter.state=='CANCELED',adapter.state
        start=node.get_clock().now().nanoseconds/1e9
        until(lambda:node.get_clock().now().nanoseconds/1e9-start>=3.,10,'cancel settling window')
        assert truth['speed']<=.1,truth
        emit('cancel_stopped',dict(truth));screenshot('02_cancelled_and_stopped')
        assert plans and max(abs(y-2.) for p in plans for x,y in p['points'])>.5,'no planned obstacle detour'
    except Exception as exc:
        failure=repr(exc);emit('acceptance_failed',{'error':failure,'navigation_state':adapter.state})
        adapter.cancel()
    finally:
        gz.unsubscribe('/world/gongyu_nav/pose/info');adapter.client.destroy()
        metrics={'status':'PASS' if failure is None else 'FAIL','failure':failure,'checks':checks,
            'arrival':arrival,'cancel_started':cancelled,'last_truth':truth,
            'amcl_updates':len(amcl),'global_plans':len(plans),
            'limits':['single Waffle AMCL/Nav2 gate, not six-robot mission validation',
                'known initial pose seeded once; simulator truth used only for this offline acceptance check']}
        (out/'metrics.json').write_text(json.dumps(metrics,indent=2)+'\n')
        for name,data in (('events',events),('amcl',amcl),('plans',plans),('scan_snapshots',scans)):
            (out/(name+'.jsonl')).write_text(''.join(json.dumps(v)+'\n' for v in data))
        if samples:
            with (out/'truth_trajectory.csv').open('w',newline='') as stream:
                writer=csv.DictWriter(stream,list(samples[0]));writer.writeheader();writer.writerows(samples)
        root=Path(__file__).resolve().parents[1]
        files=[root/'ros/nav_acceptance.py',root/'ros/ground_adapter.py',root/'ros/worlds/nav_calibration.sdf',root/'ros/config/nav2_B1.yaml']
        manifest={'started_at':started,'finished_at':datetime.now(timezone.utc).isoformat(),
            'backend':'Gazebo+AMCL+Nav2','code_revision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
            'code_dirty':bool(subprocess.check_output(['git','diff','HEAD','--name-only'],text=True).strip()),
            'source_sha256':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
            'ros_domain_id':82,'gz_partition':os.environ['GZ_PARTITION']}
        manifest['truth_topic']='/world/gongyu_nav/pose/info'
        manifest['seed']=None
        manifest['seed_control']='not explicitly configured in this basic navigation gate'
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        node.destroy_node();rclpy.shutdown()
    del gz
    print(json.dumps({'status':metrics['status'],'output':str(out)}),flush=True)
    if failure:
        raise SystemExit(1)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
