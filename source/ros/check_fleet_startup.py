"""Read actual four-platform streams and activate localization, without motion."""
import json
import os
import time
from pathlib import Path
import rclpy
from nav2_msgs.srv import ManageLifecycleNodes
from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan
from rclpy.qos import qos_profile_sensor_data


def activate_localization(node,actors,emit,check_interrupt):
    from lifecycle_msgs.srv import GetState
    clients=[];queries={};managers={};pending={};starting={};started=set();active={};last_state={};next_query={};query_sent={};startup_sent={}
    try:
        for actor in actors:
            queries[actor]=node.create_client(GetState,f'/{actor}/amcl/get_state');clients.append(queries[actor])
            managers[actor]=node.create_client(ManageLifecycleNodes,f'/{actor}/lifecycle_manager_localization/manage_nodes');clients.append(managers[actor])
        # Six independent stacks need more discovery time than the earlier four-vehicle gate.
        deadline=time.monotonic()+max(90,30*len(actors))
        while time.monotonic()<deadline:
            check_interrupt();rclpy.spin_once(node,timeout_sec=.05)
            for actor in actors:
                if actor in active:continue
                if actor in starting:
                    if not starting[actor].done():continue
                    response=starting.pop(actor).result()
                    if response is None or not response.success:raise RuntimeError(actor+' localization startup rejected')
                    emit(actor,'localization_startup',dict(success=True,elapsed_s=time.monotonic()-startup_sent[actor]));started.add(actor);pending.pop(actor,None);next_query[actor]=0.
                now=time.monotonic()
                if actor not in pending and now>=next_query.get(actor,0.) and queries[actor].service_is_ready():
                    pending[actor]=queries[actor].call_async(GetState.Request());query_sent[actor]=now;next_query[actor]=now+.5
                    emit(actor,'localization_query_sent',dict(service='amcl/get_state'))
                if actor not in pending or not pending[actor].done():continue
                response=pending.pop(actor).result()
                if response is None:raise RuntimeError(actor+' localization state reply missing')
                state=response.current_state.id
                emit(actor,'localization_query_reply',dict(state_id=state,elapsed_s=time.monotonic()-query_sent[actor]))
                if last_state.get(actor)!=state:
                    emit(actor,'localization_state',dict(state_id=state,transport='existing_node_async_service'));last_state[actor]=state
                if state==3:active[actor]=state
                elif state!=1 or actor in started:raise RuntimeError(actor+' localization did not become active: '+str(state))
                elif managers[actor].service_is_ready() and not starting:
                    request=ManageLifecycleNodes.Request();request.command=request.STARTUP
                    starting[actor]=managers[actor].call_async(request);startup_sent[actor]=time.monotonic()
                    emit(actor,'localization_startup_sent',dict(service='lifecycle_manager_localization/manage_nodes'))
            if len(active)==len(actors):return active
        raise TimeoutError('localization active replies missing: '+','.join(a for a in actors if a not in active))
    finally:
        for client in clients:node.destroy_client(client)


def run(out,scene=None):
    assert os.environ.get('ROS_DOMAIN_ID')=='83'
    rclpy.init();node=rclpy.create_node('fleet_startup_check');seen={};subscriptions=[]
    actors=('B1','B2','R1','R2');clients={};futures={}
    for actor in actors:
        for kind,typ in (('scan',LaserScan),('odom',Odometry)):
            def receive(msg,actor=actor,kind=kind):
                seen[actor+'/'+kind]=dict(frame=msg.header.frame_id,stamp_s=msg.header.stamp.sec+msg.header.stamp.nanosec/1e9,
                    samples=len(msg.ranges) if kind=='scan' else None)
            subscriptions.append(node.create_subscription(typ,f'/{actor}/{kind}',receive,qos_profile_sensor_data))
        clients[actor]=node.create_client(ManageLifecycleNodes,f'/{actor}/lifecycle_manager_localization/manage_nodes')
    deadline=time.monotonic()+50
    while time.monotonic()<deadline:
        rclpy.spin_once(node,timeout_sec=.1)
        for actor,client in clients.items():
            if actor not in futures and client.service_is_ready():
                request=ManageLifecycleNodes.Request();request.command=request.STARTUP;futures[actor]=client.call_async(request)
        if len(seen)==8 and len(futures)==4 and all(f.done() for f in futures.values()):break
    receipt=dict(streams=seen,localization={a:bool(f.result() and f.result().success) if f.done() else None for a,f in futures.items()},
        limits='No initial-pose seed, AMCL convergence, navigation activation or motion acceptance yet')
    Path(out).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))
    assert len(seen)==8 and all(seen[a+'/scan']['frame']==a+'/base_scan' for a in actors)
    assert len(futures)==4 and all(receipt['localization'].values())
    if scene:
        receipt['localized_navigation']=check_localized_navigation(node,actors,Path(scene),seen)
        receipt['limits']='Navigation ready only; no goals executed, physical task acceptance pending'
        Path(out).write_text(json.dumps(receipt,indent=2)+'\n')
    node.destroy_node();rclpy.shutdown()


def check_localized_navigation(node,actors,scene,seen,check_interrupt=None):
    from geometry_msgs.msg import PoseWithCovarianceStamped
    from tf2_msgs.msg import TFMessage
    from tf2_ros import Buffer
    from rclpy.qos import QoSProfile,DurabilityPolicy,ReliabilityPolicy
    from rclpy.action import ActionClient
    from nav2_msgs.action import NavigateToPose
    from lifecycle_msgs.srv import GetState
    buffers={a:Buffer() for a in actors};poses={};subs=[];publishers={};seeded=set();futures={}
    initial={a['id']:a['initial_xyz'] for a in json.loads((scene/'config/fleet.json').read_text())}
    durable=QoSProfile(depth=10,durability=DurabilityPolicy.TRANSIENT_LOCAL,reliability=ReliabilityPolicy.RELIABLE)
    for actor in actors:
        def tf(msg,actor=actor,static=False):
            for transform in msg.transforms:
                if static:buffers[actor].set_transform_static(transform,'actual_ros_'+actor)
                else:buffers[actor].set_transform(transform,'actual_ros_'+actor)
        subs.append(node.create_subscription(TFMessage,f'/{actor}/tf',tf,100))
        subs.append(node.create_subscription(TFMessage,f'/{actor}/tf_static',lambda m,a=actor:tf(m,a,True),durable))
        def amcl(msg,actor=actor):
            p=msg.pose.pose.position;poses[actor]=dict(x=p.x,y=p.y,frame=msg.header.frame_id,
                covariance_x=msg.pose.covariance[0],covariance_y=msg.pose.covariance[7])
        subs.append(node.create_subscription(PoseWithCovarianceStamped,f'/{actor}/amcl_pose',amcl,durable))
        publishers[actor]=node.create_publisher(PoseWithCovarianceStamped,f'/{actor}/initialpose',10)
    clients={a:node.create_client(ManageLifecycleNodes,f'/{a}/lifecycle_manager_navigation/manage_nodes') for a in actors}
    actions={a:ActionClient(node,NavigateToPose,f'/{a}/navigate_to_pose') for a in actors}
    states={};state_clients=[];confirmed=set();confirming=set()
    names=('controller_server','planner_server','behavior_server','velocity_smoother','collision_monitor','bt_navigator')
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        if check_interrupt:check_interrupt()
        rclpy.spin_once(node,timeout_sec=.05)
        for actor in actors:
            if actor not in seeded and publishers[actor].get_subscription_count():
                msg=PoseWithCovarianceStamped();msg.header.frame_id='map'
                stamp=seen[actor+'/scan']['stamp_s'];msg.header.stamp.sec=int(stamp);msg.header.stamp.nanosec=int((stamp-int(stamp))*1e9)
                msg.pose.pose.position.x=float(initial[actor][0]);msg.pose.pose.position.y=float(initial[actor][1]);msg.pose.pose.orientation.w=1.
                msg.pose.covariance[0]=msg.pose.covariance[7]=msg.pose.covariance[35]=.05**2
                publishers[actor].publish(msg);seeded.add(actor)
            ready=actor in poses and buffers[actor].can_transform('map',actor+'/base_footprint',rclpy.time.Time())
            if ready and actor not in confirmed and clients[actor].service_is_ready():
                if actor in futures:
                    if not futures[actor].done():continue
                    if not futures[actor].result().success:raise RuntimeError('navigation manager rejected startup: '+actor)
                    if actor not in confirming:
                        states[actor]=[(client,None) for client,_ in states[actor]];confirming.add(actor)
                if actor not in states:
                    group=[]
                    for name in names:
                        client=node.create_client(GetState,f'/{actor}/{name}/get_state');state_clients.append(client)
                        group.append((client,None))
                    states[actor]=group
                group=states[actor]
                for i,(client,future) in enumerate(group):
                    if future is None and client.service_is_ready():group[i]=(client,client.call_async(GetState.Request()))
                if not all(f is not None and f.done() for _,f in group):continue
                ids=[f.result().current_state.id for _,f in group]
                if all(i==3 for i in ids):
                    confirmed.add(actor)
                elif all(i==1 for i in ids):
                    if actor in futures:raise RuntimeError('navigation components not active after startup: '+actor)
                    # Concurrent bringup failed in phase29; serialize to limit request pressure.
                    if not any(not f.done() for f in futures.values()):
                        request=ManageLifecycleNodes.Request();request.command=request.STARTUP;futures[actor]=clients[actor].call_async(request)
                else:raise RuntimeError('mixed navigation lifecycle states '+actor+': '+str(ids))
        if len(confirmed)==len(actors) and all(a.server_is_ready() for a in actions.values()):break
    result={a:dict(initial_seed_count=int(a in seeded),amcl=poses.get(a),
        map_to_base=buffers[a].can_transform('map',a+'/base_footprint',rclpy.time.Time()),
        navigation_started=a in confirmed,
        action_ready=actions[a].server_is_ready()) for a in actors}
    (scene.parent/'localized_navigation_diagnostic.json').write_text(json.dumps(result,indent=2)+'\n')
    assert all(r['amcl'] and r['map_to_base'] and r['navigation_started'] and r['action_ready'] for r in result.values()),result
    return result


if __name__=='__main__':
    import sys
    run(sys.argv[1],sys.argv[2] if len(sys.argv)>2 else None)
