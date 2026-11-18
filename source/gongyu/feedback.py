"""Small position outer loop; success requires fresh, settled simulator feedback."""
from math import atan2,cos,hypot,pi,sin


def clamp(value,limit):
    return max(-limit,min(limit,value))


def angle(value):
    return (value+pi)%(2*pi)-pi


class PositionController:
    def __init__(self,mode):
        if mode not in ('ground','air'):
            raise ValueError('unknown motion mode')
        self.mode=mode;self.target=None;self.target_yaw=None
        self.state='IDLE';self.settled_since=None

    def set_target(self,xyz,yaw=None):
        self.target=tuple(xyz);self.target_yaw=yaw
        self.state='ACTIVE';self.settled_since=None

    def cancel(self,sample):
        self.target=tuple(sample['xyz']) if self.mode=='air' else None
        self.target_yaw=sample['yaw']
        self.state='CANCELLED';self.settled_since=None

    def command(self,sample,now):
        zero=(0.,0.,0.,0.)
        if sample is None or not 0<=now-sample['t']<=.5:
            self.state='FEEDBACK_LOST';self.settled_since=None
            return zero
        if self.target is None:
            return zero
        dx,dy,dz=(a-b for a,b in zip(self.target,sample['xyz']))
        distance=hypot(dx,dy)
        yaw_error=angle(self.target_yaw-sample['yaw']) if self.target_yaw is not None else 0.
        within=(distance<=(.3 if self.mode=='air' else .25)
            and (self.mode=='ground' or abs(dz)<=.2)
            and sample['speed']<=.1 and abs(sample['wz'])<=.1
            and (self.target_yaw is None or abs(yaw_error)<=.1))
        if within:
            if self.settled_since is None or now<self.settled_since:
                self.settled_since=now
            if now-self.settled_since>=1. and self.state!='CANCELLED':
                self.state='SUCCEEDED'
        else:
            self.settled_since=None
        if self.mode=='ground':
            if distance<=.15:
                return zero
            heading=angle(atan2(dy,dx)-sample['yaw'])
            return (min(.5,.8*distance)*max(0.,cos(heading)),0.,0.,clamp(1.4*heading,.8))
        scale=min(.8,.5/distance) if distance>0 else .8
        vx,vy=scale*dx,scale*dy
        yaw=sample['yaw']
        return (cos(yaw)*vx+sin(yaw)*vy,-sin(yaw)*vx+cos(yaw)*vy,
            clamp(.8*dz,.4),clamp(1.2*yaw_error,.6))
