"""Shared mission rules with completion driven exclusively by external pose feedback."""
import math
from .world import World
from .berths import Berths


class PhysicalWorld(World):
    def grant_may_expire(self,r,now):
        """Do not expire a lawful grant that cannot be used yet.

        AMAX 2026-11-10, amax-new-med-ind-01 (medium_independent, joint):
        B1 was granted 289634-337634 ms while B2 held the channel until
        297768 ms.  The graph grace rule expired B1's grant five times at
        ~2 s intervals, B1 entered only at 299860 ms and delivered at
        382306 ms against a 350000 ms deadline (13/14).  A promise about
        future channel access is not broken by the channel being busy.

        Narrow by construction: only a holder physically at E/W and only
        while the channel is occupied or its mandatory gap has not elapsed.
        Deadlines, quotas, dwell and arrival standards are untouched.
        """
        holder=r.get('actor')
        if self.poses.get(holder) not in ('E','W'):return True
        if self.channel.occupant is not None or now<self.channel.clear_at+self.channel.gap:
            return False
        return True

    def __init__(self,card,run_id,submit_move,release_arrival=None):
        self.samples={};self.moves={};self.services={};self.sequence={};self.submit_move=submit_move
        nodes=card.get('physical_arrival_mutex_nodes',[])
        if nodes not in ([],['D']) or nodes and not callable(release_arrival):raise ValueError('D arrival profile requires its actual-completion release callback')
        self.release_arrival=release_arrival
        if type(card.get('physical_continuous_channel',False)) is not bool:raise ValueError('continuous channel flag must be boolean')
        for name in ('physical_delivery_waypoint','physical_channel_west_alignment',
                 'physical_channel_east_alignment'):
            via=card.get(name)
            if via is not None and (not isinstance(via,(list,tuple)) or len(via)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in via)):
                raise ValueError(name+' must be a finite3D point')
        super().__init__(card,run_id)
        self.berths=Berths(card) if 'physical_berths' in card else None

    def reference_position(self,actor,node):
        return self.berths.position(actor,node) if self.berths else super().node_position(actor,node)

    def feedback_position(self,actor):
        return self.samples[actor]['xyz'] if actor in self.samples else None

    def node_position(self,actor,node):
        if actor in self.samples and self.poses.get(actor)==node:
            return self.samples[actor]['xyz']
        return super().node_position(actor,node)

    def fresh(self,actor):
        return actor in self.samples and 0<=self.now-self.samples[actor]['at']<=200

    def radio_positions(self):
        positions=super().radio_positions()
        return {a:(p if a not in self.card['fleet'] or self.fresh(a) else None) for a,p in positions.items()}

    def within(self,actor,target):
        s=self.samples[actor];air=self.card['fleet'][actor]['mode']=='air'
        tolerance=self.card.get('physical_berth_tolerance_m',.3 if air else .25)
        return (math.hypot(s['xyz'][0]-target[0],s['xyz'][1]-target[1])<=tolerance
            and (not air or abs(s['xyz'][2]-target[2])<=.2) and s['speed']<=.1 and abs(s['wz'])<=.1)

    def later(self,at,actor,kind,payload):
        if kind=='arrived':
            self.moves[actor]=dict(payload=payload,since=None,queued=False,started_ms=self.now)
        elif kind.endswith('_completed'):
            self.services[actor]=dict(kind=kind,payload=payload,since=None,queued=False,started_ms=self.now)
        else:super().later(at,actor,kind,payload)

    def departure_ready(self,actor,source,target):
        clearance=self.card.get('physical_departure_clearance_m',0)
        if not self.berths or not clearance or self.card['fleet'][actor]['mode']!='ground':return True
        for peer,pending in self.moves.items():
            if peer!=actor and pending['payload']['from']==source and pending['payload']['node']==target:
                if not self.fresh(peer) or math.dist(self.samples[peer]['xyz'],self.reference_position(actor,source))<clearance:
                    self.emit(actor,'physical_departure_held',dict(source=source,target=target,peer=peer,
                        reason='predecessor has not cleared the local exit',clearance_m=clearance))
                    return False
        return True

    def arrival_region_ready(self,actor,source,target):
        """Refuse a channel entry whose arrival region is already claimed by a teammate.

        The E<->W traverse carries arrival_region='D' and waits at its first waypoint for
        the D arrival mutex.  That wait happens *inside* the channel: a holder that enters
        while a teammate is still on its way to D keeps the single-capacity channel for the
        whole wait.  phase115 observed 122.020 s of channel occupancy against a 48 s
        nominal window, which pushed the second blue delivery past its deadline.

        The condition is local and observable: the teammate's pending move already names D
        as its target.  Waiting at the berth instead of entering costs nothing, because the
        channel would otherwise be held idle by the same vehicle anyway.
        """
        if {source,target}!={'E','W'}:return True
        if 'D' not in self.card.get('physical_arrival_mutex_nodes',[]):return True
        for peer,pending in self.moves.items():
            if peer==actor or pending['payload'].get('node')!='D':continue
            if not self.fresh(peer):continue
            self.emit(actor,'physical_arrival_held',dict(source=source,target=target,peer=peer,
                reason='teammate holds the D arrival region',region='D'))
            return False
        return True

    ENTRY_APRON_M=.65

    def apron_clear(self,actor,point):
        """Is the entry staging point free of every peer's in-flight move?

        phase122 placed `physical_channel_east_alignment` on the channel axis 0.4 m
        outside the east mouth so that a guarded entry stops being a
        translation+turn.  The same cell is on B1's L -> E berth transfer: on
        amax-fs-c1-new-adv-02 (medium_adversarial) that transfer passed 0.497 m from
        it while R1 was dispatching, Nav2 answered "Goal Coordinates of(5.400000,
        0.000000) was in lethal cost", the action aborted and the episode ended at
        150.98 s.  The staging point is a conditional gain, so the referee only uses
        it when no peer is currently driving through the apron.

        Threshold: 0.65 m.  The recorded pool separates cleanly -- 0.497 m when a peer
        owns the apron, >= 0.906 m otherwise -- and 0.65 m is the only value needed to
        keep both clusters on the correct side.  The corridor is approximated by the
        straight segment between the peer's source and target reference positions,
        which is the same two-point geometry the referee itself dispatches.
        """
        for peer,pending in self.moves.items():
            if peer==actor or not self.fresh(peer):continue
            payload=pending['payload']
            if 'from' not in payload or 'node' not in payload:continue
            a=self.reference_position(peer,payload['from'])
            b=self.reference_position(peer,payload['node'])
            if a is None or b is None:continue
            dx,dy=b[0]-a[0],b[1]-a[1]
            denominator=dx*dx+dy*dy
            fraction=0. if denominator<1e-9 else max(0.,min(1.,((point[0]-a[0])*dx+(point[1]-a[1])*dy)/denominator))
            if math.hypot(point[0]-(a[0]+dx*fraction),point[1]-(a[1]+dy*fraction))<self.ENTRY_APRON_M:
                return False
        return True

    def start_move(self,actor,target,now=None):
        if now is not None:self.advance(now)
        source=self.poses[actor]
        if not self.fresh(actor) or source is None or not self.within(actor,self.reference_position(actor,source)):
            return False
        if (source,target) not in self.edges or self.edges[source,target][1]!=self.card['fleet'][actor]['mode']:
            raise ValueError('illegal physical edge')
        if not self.departure_ready(actor,source,target):return False
        if not self.arrival_region_ready(actor,source,target):return False
        if self.berths and self.berths.reserve(actor,target) is None:return False
        if not super().start_move(actor,target):
            if self.berths:self.berths.release(actor,target)
            return False
        self.sequence[actor]=self.sequence.get(actor,0)+1
        token=self.sequence[actor];self.moves[actor]['token']=token
        points=self.edge_points(actor,source,target)
        if self.berths:
            middle=list(points[1:-1])
            if {source,target}=={'E','W'}:
                # Interior goals force the channel route; their next heading stays axial.
                begin,end=points[0],points[-1]
                middle=[tuple(begin)]+[tuple(a+(b-a)*fraction for a,b in zip(begin,end)) for fraction in (1/3,2/3)]+[tuple(end)]
                west=self.card.get('physical_channel_west_alignment')
                if west is not None:
                    # Stage outside the wall corner before a guard-protected turn.
                    middle=([tuple(west)]+middle) if source=='W' else (middle+[tuple(west)])
                east=self.card.get('physical_channel_east_alignment')
                if east is not None and self.apron_clear(actor,east):
                    # Mirror of the west point: align on the axis before the east mouth,
                    # so the guarded entry is a translation and not a translation+turn.
                    middle=([tuple(east)]+middle) if source=='E' else (middle+[tuple(east)])
                elif east is not None:
                    # A peer is driving through the apron; fall back to the two-point
                    # entry rather than asking the planner for an occupied goal cell.
                    self.emit(actor,'physical_entry_alignment_skipped',dict(point=list(east),
                        source=source,target=target,apron_m=self.ENTRY_APRON_M,
                        reason='a peer in-flight move crosses the entry apron'))
            if (source,target)==('W','D') and self.card.get('physical_delivery_waypoint') is not None:
                middle=[self.card['physical_delivery_waypoint']]
            points=[self.reference_position(actor,source)]+middle+[self.reference_position(actor,target)]
        self.emit(actor,'physical_move_requested',dict(goal_id=token,waypoints=points))
        arrival={}
        if 'D' in self.card.get('physical_arrival_mutex_nodes',[]) and (target=='D' or (source,target)==('E','W')):
            gate=(2 if self.berths else max(1,len(points)-2)) if target=='W' else len(points)-1
            if self.berths and target=='W' and self.card.get('physical_continuous_channel'):
                gate=1  # Wait in the berth, then traverse the entrance and channel in one continuous action.
            arrival=dict(arrival_region='D',arrival_gate_before=gate)
        if self.berths and {source,target}=={'E','W'} and self.card.get('physical_continuous_channel'):
            arrival['continuous_ground']=True
        try:self.submit_move(actor,token,points,**arrival)
        except Exception as exc:
            self.emit(actor,'physical_dispatch_failed',dict(goal_id=token,error=repr(exc)))
            # Keep the occupied resource and unresolved action until actual recovery feedback.
            raise
        return True

    def service(self,actor,kind,task_id=None):
        node=self.poses[actor]
        if not self.fresh(actor) or node is None or not self.within(actor,self.reference_position(actor,node)):
            return False
        return super().service(actor,kind,task_id)

    def receive_pose(self,actor,xyz,speed,wz,sampled_ms,goal_id=None,navigation_succeeded=False):
        if actor not in self.card['fleet']:raise ValueError('unknown physical actor')
        if len(xyz)!=3 or not all(math.isfinite(x) for x in (*xyz,speed,wz)) or speed<0:
            raise ValueError('invalid physical feedback')
        if not 0<=self.now-sampled_ms<=200:return False
        if actor in self.samples and sampled_ms<=self.samples[actor]['at']:return False
        move=self.moves.get(actor)
        if move and goal_id!=move['token']:return False
        previous=self.samples.get(actor)
        self.samples[actor]=dict(xyz=tuple(xyz),speed=speed,wz=wz,at=sampled_ms)
        if move and self.berths:
            source=move['payload']['from'];origin=self.berths.position(actor,source)
            if origin and sampled_ms>=move['started_ms'] and math.dist(xyz,origin)>.55:
                self.berths.release(actor,source)
                self.emit(actor,'physical_berth_cleared',dict(node=source,goal_id=goal_id,sampled_ms=sampled_ms))
        pending=move or self.services.get(actor)
        if not pending or pending['queued']:return True
        if sampled_ms<pending['started_ms']:return True
        if previous is None or sampled_ms-previous['at']>200:pending['since']=None
        target=self.reference_position(actor,pending['payload']['node'])
        valid=self.within(actor,target) and (not move or self.card['fleet'][actor]['mode']=='air' or navigation_succeeded)
        if not valid:pending['since']=None;return True
        if pending['since'] is None:pending['since']=sampled_ms
        duration=1000 if move else self.card['service_ms']
        # Air and ground both need the matching actuator result before the task can advance.
        if sampled_ms-pending['since']>=duration and (not move or navigation_succeeded):
            pending['queued']=True
            super().later(self.now,actor,'arrived' if move else pending['kind'],pending['payload'])
            self.emit(actor,'physical_completion_confirmed',dict(goal_id=goal_id,kind='move' if move else pending['kind'],sampled_ms=sampled_ms,dwell_ms=sampled_ms-pending['since']))
        return True

    def advance(self,now):
        if now<self.now:raise ValueError('physical clock must be monotone')
        for actor,pending in list(self.moves.items())+list(self.services.items()):
            if actor not in self.samples or now-self.samples[actor]['at']>200:pending['since']=None
        super().advance(now)
        for collection in (self.moves,self.services):
            for actor,pending in list(collection.items()):
                if pending['queued'] and actor not in self.busy:
                    if collection is self.moves and pending['payload']['node'] in self.card.get('physical_arrival_mutex_nodes',[]):
                        if not self.release_arrival(actor,pending['token']):raise RuntimeError('actual arrival claim did not release: '+actor)
                    del collection[actor]

    def metrics(self):
        result=super().metrics();result['backend']='external_pose_feedback'
        return result
