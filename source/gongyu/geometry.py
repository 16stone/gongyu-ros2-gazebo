"""Explicit teaching-scale geometry, not a calibrated camera or wireless simulator."""
from heapq import heappop,heappush
from math import atan2,degrees,dist,hypot
from .timing import edge_times


def segment_hits_box(a,b,minimum,maximum):
    lo,hi=0.,1.
    for x,y,mn,mx in zip(a,b,minimum,maximum):
        d=y-x
        if abs(d)<1e-12:
            if x<mn or x>mx:
                return False
            continue
        p,q=(mn-x)/d,(mx-x)/d
        lo=max(lo,min(p,q));hi=min(hi,max(p,q))
        if lo>hi+1e-12:
            return False
    return True


def path_length(points):
    return sum(dist(a,b) for a,b in zip(points,points[1:]))


def default_geometry():
    return {'version':'1.0','device':[8,0,.8],'radio_range_m':9.5,
        'sensors':{'ground':{'range_m':3.,'horizontal_fov_deg':90.,'vertical_fov_deg':60.},
                   'air':{'range_m':9.,'horizontal_fov_deg':90.,'vertical_fov_deg':60.}},
        'heights':{'ground':.3,'blue_air':2.5,'red_air':3.5},
        'infrastructure':{'entrance':[5,0,.6],'red_station':[10,-8,.3]},
        'obstacles':[
            {'id':'device_screen','minimum':[6.9,-1.2,0.],'maximum':[7.1,1.2,1.6],
             'visual_opaque':True,'radio_opaque':True},
            {'id':'optical_screen','minimum':[8.9,2.,0.],'maximum':[9.1,6.,5.],
             'visual_opaque':True,'radio_opaque':False}],
        'edge_polylines':{'D>L':[[1,0,.3],[1,-3.5,.3],[6,-3.5,.3],[6,0,.3]]},
        'communication_policy':'stationary_waypoint_contacts',
        'note':'Uniform range and ray-box occlusion; opacity/ranges are frozen design assumptions. Two-second observation includes sensor aiming; no claim of calibrated optics, propagation or aiming dynamics.'}


class Geometry:
    def __init__(self,config):
        self.config=config

    def clear(self,a,b,channel):
        return not any(o[channel+'_opaque'] and segment_hits_box(a,b,o['minimum'],o['maximum'])
                       for o in self.config['obstacles'])

    def can_observe(self,position,mode,yaw=None,pitch=None):
        target=self.config['device'];sensor=self.config['sensors'][mode]
        if dist(position,target)>sensor['range_m']+1e-9:
            return False
        dx,dy,dz=(b-a for a,b in zip(position,target))
        bearing=degrees(atan2(dy,dx));elevation=degrees(atan2(dz,hypot(dx,dy)))
        yaw=bearing if yaw is None else yaw
        pitch=elevation if pitch is None else pitch
        turn=abs((bearing-yaw+180)%360-180)
        return (turn<=sensor['horizontal_fov_deg']/2 and
                abs(elevation-pitch)<=sensor['vertical_fov_deg']/2 and self.clear(position,target,'visual'))

    def radio(self,a,b):
        return bool(a is not None and b is not None and dist(a,b)<=self.config['radio_range_m']+1e-9
                    and self.clear(a,b,'radio'))

    def ground_route(self,source,destination,nodes,edges,speed,tau_ms,service_ms,visible_nodes=None,edge_durations=None):
        """Choose an actual visible ground waypoint and route; same helper for forecast/execution."""
        adjacency={}
        for a,b,length,mode in edges:
            if mode=='ground':
                adjacency.setdefault(a,[]).append((b,edge_durations[a,b] if edge_durations is not None else round(length/speed*1000)))
                adjacency.setdefault(b,[]).append((a,edge_durations[b,a] if edge_durations is not None else round(length/speed*1000)))
        def shortest(a,b):
            queue=[(0,a,())];seen=set()
            while queue:
                cost,node,path=heappop(queue)
                if node in seen:
                    continue
                seen.add(node)
                if node==b:
                    return cost,path
                for nxt,dt in adjacency.get(node,[]):
                    heappush(queue,(cost+dt,nxt,path+(nxt,)))
            raise ValueError('Disconnected ground observation route')
        candidates=[]
        for node in adjacency:
            visible=node in visible_nodes if visible_nodes is not None else self.can_observe(tuple(nodes[node][:2])+(self.config['heights']['ground'],),'ground')
            if not visible:
                continue
            before,to_obs=shortest(source,node)
            after,from_obs=shortest(node,destination)
            if after<=tau_ms:
                candidates.append({'node':node,'to_observation':list(to_obs),'from_observation':list(from_obs),
                                   'movement_ms':before+after,'return_ms':after,'duration_ms':before+after+service_ms,
                                   'sample_offset_ms':before+service_ms})
        return min(candidates,key=lambda c:(c['movement_ms'],c['return_ms'],c['node'])) if candidates else None


def ground_observation(public,source,destination,remote=False):
    geometry=public.get('geometry')
    g=Geometry(geometry or default_geometry())
    tau=public['tau_ms']-(public['message_delay_ms'] if remote else 0)
    return g.ground_route(source,destination,public.get('nodes',{}),public['edges'],
                          public['ground_speed'],tau,public['service_ms'],None if geometry else {'O'},edge_times(public))
