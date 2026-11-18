"""Nav2 action feedback; an action result does not assert mission arrival."""
import math
from pathlib import Path

from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Path as NavPath
from nav2_msgs.action import NavigateToPose,NavigateThroughPoses
from rclpy.action import ActionClient


class Nav2GroundAdapter:
    def __init__(self,node,actor,emit,through_bt=None):
        self.node=node;self.emit=emit
        self.client=ActionClient(node,NavigateToPose,f'/{actor}/navigate_to_pose')
        self.path_client=ActionClient(node,NavigateThroughPoses,f'/{actor}/navigate_through_poses')
        self.through_bt=str(Path(through_bt or Path(__file__).resolve().parent/'config/axial_transit.xml').resolve())
        self.state='IDLE';self.sequence=0;self.handle=None;self._using_path=False
        self.plan_subscription=node.create_subscription(NavPath,f'/{actor}/plan',self._plan,10)

    def _pose(self,x,y,yaw):
        pose=PoseStamped();pose.header.frame_id='map';pose.header.stamp=self.node.get_clock().now().to_msg()
        pose.pose.position.x=float(x);pose.pose.position.y=float(y)
        pose.pose.orientation.z=math.sin(yaw/2);pose.pose.orientation.w=math.cos(yaw/2)
        return pose

    def submit(self,x,y,yaw):
        goal=NavigateToPose.Goal();goal.pose=self._pose(x,y,yaw)
        self._submit(self.client,goal,{'target':[x,y,yaw]})

    def submit_path(self,targets):
        if len(targets)<2 or any(len(p)!=3 or not all(math.isfinite(v) for v in p) for p in targets):
            raise ValueError('continuous navigation requires at least two finite x/y/yaw poses')
        if not Path(self.through_bt).is_file():raise FileNotFoundError(self.through_bt)
        if not self.path_client.server_is_ready():raise RuntimeError('NavigateThroughPoses action unavailable')
        goal=NavigateThroughPoses.Goal();goal.poses=[self._pose(*p) for p in targets];goal.behavior_tree=self.through_bt
        self._submit(self.path_client,goal,{'target':list(targets[-1]),'via':[list(p) for p in targets],
            'action':'NavigateThroughPoses'})

    def _submit(self,client,goal,payload):
        if self.state in ('REQUESTED','ACTIVE','CANCEL_REQUESTED'):
            raise RuntimeError('one unfinished navigation goal per platform')
        self.sequence+=1;token=self.sequence;self.state='REQUESTED';self.handle=None
        self._using_path='via' in payload
        self.emit('navigation_requested',{'goal_id':token,**payload})
        future=client.send_goal_async(goal,feedback_callback=lambda m:self._feedback(token,m))
        future.add_done_callback(lambda f:self._accepted(token,f))

    def _plan(self,message):
        if self.state=='ACTIVE' and self._using_path:
            self.emit('navigation_plan_observed',{'observed_while_goal':self.sequence,
                'frame':message.header.frame_id,'stamp_s':message.header.stamp.sec+message.header.stamp.nanosec/1e9,
                'points':[[p.pose.position.x,p.pose.position.y] for p in message.poses]})

    def _feedback(self,token,message):
        if token==self.sequence:
            feedback=message.feedback
            self.emit('navigation_feedback',{'goal_id':token,'distance_remaining':feedback.distance_remaining,
                'recoveries':feedback.number_of_recoveries,'remaining_poses':getattr(feedback,'number_of_poses_remaining',None)})

    def _accepted(self,token,future):
        if token!=self.sequence:
            return
        try:
            self.handle=future.result()
            self.state='ACTIVE' if self.handle.accepted else 'REJECTED'
            self.emit('navigation_acceptance',{'goal_id':token,'accepted':self.handle.accepted})
            if self.handle.accepted:
                self.handle.get_result_async().add_done_callback(lambda f:self._result(token,f))
        except Exception as exc:
            self.state='REQUEST_ERROR';self.emit('navigation_error',{'goal_id':token,'error':repr(exc)})

    def _result(self,token,future):
        if token!=self.sequence:
            return
        try:
            result=future.result()
            self.state={4:'SUCCEEDED_NAV2',5:'CANCELED',6:'ABORTED'}.get(result.status,'UNKNOWN_RESULT')
            self.emit('navigation_result',{'goal_id':token,'ros_status':result.status,
                'state':self.state,'error_code':result.result.error_code})
        except Exception as exc:
            self.state='RESULT_ERROR';self.emit('navigation_error',{'goal_id':token,'error':repr(exc)})

    def cancel(self):
        if self.state!='ACTIVE' or not self.handle:
            return False
        token=self.sequence;self.state='CANCEL_REQUESTED'
        self.emit('navigation_cancel_requested',{'goal_id':token})
        self.handle.cancel_goal_async().add_done_callback(lambda f:self._cancel_ack(token,f))
        return True

    def _cancel_ack(self,token,future):
        if token!=self.sequence:
            return
        try:
            accepted=bool(future.result().goals_canceling)
            self.emit('navigation_cancel_acknowledged',{'goal_id':token,'accepted':accepted})
            if not accepted and self.state=='CANCEL_REQUESTED':
                self.state='ACTIVE'
        except Exception as exc:
            self.emit('navigation_cancel_error',{'goal_id':token,'error':repr(exc)})
