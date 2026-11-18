"""Per-entity waypoint execution; mission completion remains in PhysicalWorld."""
import math
from collections import deque
from .feedback import PositionController


class MoveDispatcher:
    def __init__(self,fleet,ground,publish_air,ground_tolerance=.1,emit=None):
        self.fleet=fleet;self.ground=ground;self.publish_air=publish_air
        self.ground_tolerance=ground_tolerance;self.emit=emit or (lambda *args:None)
        self.air={a:PositionController('air') for a,s in fleet.items() if s['mode']=='air'}
        self.pending={};self.samples={}
        self.arrival_owners={};self.arrival_waiters={}

    def begin(self,actor,token,points,arrival_region=None,arrival_gate_before=None,continuous_ground=False):
        if actor not in self.fleet:raise ValueError('unknown actuator')
        if len(points)<2 or any(len(p)!=3 or not all(math.isfinite(v) for v in p) for p in points):raise ValueError('finite 3D waypoints required')
        if type(continuous_ground) is not bool or continuous_ground and (self.fleet[actor]['mode']!='ground' or not callable(getattr(self.ground.get(actor),'submit_path',None))):
            raise ValueError('continuous navigation requires a ground path actuator')
        previous=self.pending.get(actor)
        if previous and (not self.done(actor,previous['token']) or token<=previous['token']):raise RuntimeError('unfinished or obsolete actuator goal')
        if arrival_region is not None and (self.fleet[actor]['mode']!='ground' or not isinstance(arrival_region,str) or not arrival_region
            or type(arrival_gate_before) is not int or not 1<=arrival_gate_before<len(points)):raise ValueError('ground arrival region and valid gate waypoint required')
        owned=next((r for r,owner in self.arrival_owners.items() if owner[0]==actor),None)
        if owned is not None:
            if owned!=arrival_region:raise RuntimeError('arrival claim cannot be abandoned before actual region completion')
            self.arrival_owners[owned]=(actor,token)
            self.emit(actor,'physical_arrival_transfer',dict(region=owned,goal_id=token))
        self.pending[actor]=dict(token=token,queue=deque(points[1:]),target=tuple(points[0]),corrections=0,
            arrival_region=arrival_region,arrival_gate_before=arrival_gate_before,next_waypoint=1,waiting_arrival=False,completed=False,continuous_ground=continuous_ground)
        self._next(actor)

    def _next(self,actor):
        p=self.pending[actor];region=p['arrival_region'];key=(actor,p['token'])
        if region and p['next_waypoint']>=p['arrival_gate_before'] and self.arrival_owners.get(region)!=key:
            queue=self.arrival_waiters.setdefault(region,deque())
            if key not in queue:
                queue.append(key);self.emit(actor,'physical_arrival_wait',dict(region=region,goal_id=p['token'],owner=self.arrival_owners.get(region)))
            if region in self.arrival_owners or queue[0]!=key:
                p['waiting_arrival']=True;return
            queue.popleft();self.arrival_owners[region]=key
            self.emit(actor,'physical_arrival_granted',dict(region=region,goal_id=p['token']))
        p['waiting_arrival']=False
        origin=self.samples.get(actor,{}).get('xyz',p['target'])
        if p['continuous_ground'] and len(p['queue'])>1 and (not region or p['next_waypoint']>=p['arrival_gate_before']):
            points=list(p['queue']);targets=[];previous=origin
            for i,target in enumerate(points):
                a,b=(target,points[i+1]) if i+1<len(points) else (previous,target)
                targets.append((target[0],target[1],math.atan2(b[1]-a[1],b[0]-a[0])))
                previous=target
            p['queue'].clear();p['target']=points[-1];p['next_waypoint']+=len(points);p['yaw']=targets[-1][2]
            p['corrections']=0
            self.ground[actor].submit_path(targets)
            return
        target=p['queue'].popleft();p['target']=target;p['next_waypoint']+=1
        if actor in self.air:self.air[actor].set_target(target)
        else:
            heading=(target[0]-origin[0],target[1]-origin[1])
            if p['queue'] and math.hypot(p['queue'][0][0]-target[0],p['queue'][0][1]-target[1])>1e-6:
                heading=(p['queue'][0][0]-target[0],p['queue'][0][1]-target[1])
            p['yaw']=math.atan2(heading[1],heading[0]);p['corrections']=0
            self.ground[actor].submit(target[0],target[1],p['yaw'])

    def release_arrival(self,actor,token):
        # PhysicalWorld calls this only after actual success and continuous destination dwell.
        p=self.pending.get(actor)
        if not p or p['token']!=token or not self.done(actor,token):return False
        region=p['arrival_region']
        if region and self.arrival_owners.get(region)==(actor,token):
            del self.arrival_owners[region];self.emit(actor,'physical_arrival_released',dict(region=region,goal_id=token));return True
        return False

    def _fail(self,message):
        for air in self.air:self.publish_air(air,(0.,0.,0.,0.))
        raise RuntimeError(message)

    def tick(self,samples,now):
        self.samples.update(samples)
        for actor,p in self.pending.items():
            if p['waiting_arrival']:
                self._next(actor);continue
            if actor in self.air:
                controller=self.air[actor];command=controller.command(samples.get(actor),now)
                self.publish_air(actor,command);succeeded=controller.state=='SUCCEEDED'
            else:
                state=self.ground[actor].state
                if state in ('ABORTED','REJECTED','REQUEST_ERROR','RESULT_ERROR','UNKNOWN_RESULT'):
                    self._fail(actor+' navigation '+state)
                succeeded=state=='SUCCEEDED_NAV2'
                s=samples.get(actor)
                if succeeded and not p['queue'] and s is not None and 0<=now-s['t']<=.2:
                    error=math.hypot(s['xyz'][0]-p['target'][0],s['xyz'][1]-p['target'][1])
                    if error>self.ground_tolerance:
                        if p['corrections']>=3:self._fail(actor+' parking correction limit exceeded')
                        p['corrections']+=1
                        self.emit(actor,'parking_correction_requested',dict(goal_id=p['token'],attempt=p['corrections'],error_m=error,target=p['target']))
                        self.ground[actor].submit(p['target'][0],p['target'][1],p['yaw']);succeeded=False
            if succeeded and p['queue']:self._next(actor)
            elif succeeded and actor in self.air:
                # A completed token stays terminal even when hover feedback temporarily disappears.
                p['completed']=True

    def done(self,actor,token):
        p=self.pending.get(actor)
        if not p or p['token']!=token or p['queue']:return False
        return p['completed'] if actor in self.air else self.ground[actor].state=='SUCCEEDED_NAV2'
