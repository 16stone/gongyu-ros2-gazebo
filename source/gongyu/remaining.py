"""Forecast the residual delivery without reviving completed or transferring held cargo."""
from heapq import heappop,heappush
from dataclasses import replace

from .geometry import Geometry,ground_observation
from .mission import report_valid
from .model import Report
from .timing import edge_times,travel_ms


def custom(kind,**args):
    return ('custom',{'kind':kind,**args})


def ground_travel(view,route,source,target,at,who='B1'):
    m=view.public_map;edges={};durations=edge_times(m)
    gap=m['channel_gap_ms'];grace=m.get('reservation_grace_ms',2000)
    for a,b,length,mode in m['edges']:
        if mode=='ground' and not (route=='channel' and {a,b}=={'L','D'}) and not (route=='bypass' and {a,b}=={'E','W'}):
            edges.setdefault(a,[]).append((b,durations[a,b]));edges.setdefault(b,[]).append((a,durations[b,a]))
    queue=[(at,source,(),0)];seen=set()
    while queue:
        end,node,path,movement=heappop(queue)
        if node in seen:
            continue
        seen.add(node)
        if node==target:
            return end,[('move',n) for n in path],movement
        for nxt,duration in edges.get(node,[]):
            start=end
            if {node,nxt}=={'E','W'}:
                # A grant held by this actor is an authoritative allocation: the referee
                # already resolved it against every other grant in force. Entering up to
                # `grace` late does not create a new conflict, so the forecast occupies the
                # *reserved* window instead of re-deriving a conflict against a later grant.
                # The legacy scan pushed an earlier holder behind a later one (R1 150-198 s
                # vs B1 200-248 s at 150.2 s: 150.2+48+2 > 200 s -> 250 s), which turned a
                # legitimately deliverable plan into a forecasted overtime rejection.
                own=next((r for r in view.reservations if r['actor']==who and not r.get('used')
                    and r.get('cancelled_at') is None and r.get('direction',[node,nxt])==[node,nxt]
                    and start<=r['start']+grace),None)
                if own is not None:
                    heappush(queue,(max(own['start']+duration,own['end']),nxt,path+(nxt,),movement+duration))
                    continue
                for booking in sorted(view.reservations,key=lambda r:r['start']):
                    if booking.get('cancelled_at') is not None:
                        continue
                    if booking['actor']==who:
                        continue
                    if start+duration+gap<=booking['start']:
                        break
                    if start<booking['end']+gap:
                        start=booking['end']+gap
            heappush(queue,(start+duration,nxt,path+(nxt,),movement+duration))
    raise ValueError('no ground route '+str((source,target)))


def channel_rebooking(view,source,target,at,who):
    own=next((r for r in view.reservations if r['actor']==who and r.get('slot_id')
        and not r.get('used') and r.get('cancelled_at') is None and r.get('direction')==[source,target]),None)
    if own is None:return None
    freed=replace(view,reservations=tuple(r for r in view.reservations if r.get('slot_id')!=own['slot_id']))
    end,_,_=ground_travel(freed,'channel',source,target,at+2*view.public_map['message_delay_ms'],who)
    entry=end-travel_ms(view.public_map,source,target)
    return dict(slot_id=own['slot_id'],entry_ms=entry,arrived_ms=end) if entry<own['start'] else None


def forecast_remaining(view,candidate):
    tasks={t['id']:t for t in view.own_tasks if t['id'] in ('blue1','blue2')}
    remaining=[name for name,t in tasks.items() if t.get('completed_ms') is None]
    if len(remaining)>1:
        return None
    c=dict(candidate);m=view.public_map;t=view.now_ms;d=m['message_delay_ms'];s=m['service_ms']
    deliveries=[tasks.get(name,{}).get('completed_ms') for name in ('blue1','blue2')]
    c.update(remaining_tasks=remaining,deliveries_ms=deliveries,sampling_ms=[],peer_commands={},
        own_commands=[],staging_commands=[],migration_ms=0,handoff_gap_ms=0,air_inspection_ms=None,
        required=[],legal=True,reason='residual forecast from delivered knowledge',forecast_comparable=True)
    def reject(reason):
        c.update(legal=False,reason=reason,score=(-1,0,0))
        return c
    if not remaining:
        c.update(score=(0,0,0),reason='all assigned deliveries have completion receipts')
        return c
    cargo=remaining[0];actor='B1' if c['assignment']=='single' else 'B2'
    c.update(cargo_id=cargo,transport_actor=actor)
    if c['information']=='wait':
        if c['assignment']!='single' or c['support']!='fixed':
            return reject('waiting does not authorize a new assignment or support commitment')
        c.update(score=(0,0,0),forecast_comparable=False,reason='safe waiting; future service remains unknown',
            own_commands=[('hold',None)])
        return c
    if view.node is None:
        return reject('coordinator is moving; defer to a real arrival checkpoint')
    held=view.inventory==cargo
    if view.inventory and not held:
        return reject('another held cargo cannot be replaced by this plan')
    if held and (actor!='B1' or c['support']!='fixed'):
        return reject('held cargo stays with its lawful owner and needs no new observation')
    statuses=view.teammate_status
    locked=set(m.get('unresolved_commitments',()))
    b2=statuses.get('B2');b3=statuses.get('B3')
    if actor=='B2' and (not b2 or 'B2' in locked or b2.get('inventory') or b2.get('available_until',-1)<t+d):
        return reject('no released, delivered transport availability')
    def travel(source,target,at,who):
        return ground_travel(view,c['route'],source,target,at,who)
    def radio(node_a,node_b,mode_b):
        if node_a==node_b:
            return True
        if 'geometry' in m:
            g=m['geometry'];height=g['heights']['blue_air' if mode_b=='air' else 'ground']
            return Geometry(g).radio((*m['nodes'][node_a][:2],g['heights']['ground']),(*m['nodes'][node_b][:2],height))
        return frozenset((node_a,node_b)) in [frozenset(pair) for pair in m.get('radio_edges',[['J','L'],['K','L'],['H','L']])]
    if held:
        end,commands,movement=travel(view.node,'D',t,'B1')
        c['own_commands']=commands+[('unload',cargo)]
        c['migration_ms']=movement;c['deliveries_ms'][('blue1','blue2').index(cargo)]=end+s
        c['score']=(int(end+s<=tasks[cargo]['deadline_ms']),-movement,0)
        return c
    coordinator=view.node
    peer_nodes=[]
    if actor=='B2':
        peer_nodes.append((b2['node'],'ground'))
    if c['support']=='air':
        if not b3 or 'B3' in locked or b3['node']!='K':
            return reject('no released air-support availability')
        peer_nodes.append(('K','air'))
    # Local observation work starts at L; remote assignment may stay at a genuine radio contact.
    need_stage=(actor=='B1' or any(not radio(coordinator,n,mode) for n,mode in peer_nodes))
    stage_t=t;stage=[];movement=0
    if need_stage and coordinator!='L':
        stage_t,stage,movement=travel(coordinator,'L',t,'B1');coordinator='L'
    c['staging_commands']=stage
    protocol=actor=='B2' or c['support']=='air'
    request_at=stage_t
    if c['support']=='air':
        request_at=max(request_at,b3.get('predicted_contact_at',t))
        if b3.get('available_until',-1)<request_at+d:
            return reject('air contact expires before the actual prepare can arrive')
    if actor=='B2' and b2.get('available_until',-1)<request_at+d:
        return reject('transport availability expires before prepare arrival')
    committed=request_at+3*d if protocol else stage_t
    source=view.node if actor=='B1' else b2['node']
    transport_at,entry,entry_cost=travel('L' if actor=='B1' else source,'L',committed if actor=='B2' else stage_t,actor)
    movement+=entry_cost
    reports=view.reports if actor=='B1' else (Report(**b2['report']),) if b2.get('report') else ()
    cached=any(report_valid(r,'device',transport_at) for r in reports)
    observer_commands=[];air_commands=[];load_at=transport_at;required=[]
    if actor=='B2':
        required.append('B2')
    if c['support']=='air':
        required.append('B3')
        air_at=committed+travel_ms(m,'K','H')
        ready=max(air_at,transport_at+d) if actor=='B2' else air_at
        load_at=max(transport_at,ready+s+d)
        air_finish=ready+s+d+travel_ms(m,'H','K')+travel_ms(m,'K','F')+s
        if not b3.get('inspection_done') and air_finish>b3['inspection_deadline_ms']:
            return reject('would violate the provider own inspection commitment')
        movement+=travel_ms(m,'K','H')+travel_ms(m,'H','K');c['air_inspection_ms']=air_finish
        air_commands=[('move','H'),custom('ready'),custom('support_service')]
    elif not cached:
        mode=c['information']
        if mode in ('self','carry') and actor=='B2':
            route=ground_observation(m,source,'L')
            if route is None:
                return reject('self-carried report cannot reach the remaining load fresh')
            entry=[custom('observe_to',target='L')]
            load_at=committed+route['duration_ms'];movement+=route['movement_ms']-entry_cost
        elif mode=='self':
            route=ground_observation(m,'L','L')
            if route is None:
                return reject('coordinator cannot self-collect a fresh remaining report')
            load_at=transport_at+route['duration_ms'];movement+=route['movement_ms']
        elif actor=='B1':
            if not b2 or 'B2' in locked:
                return reject('no released observer for the remaining report')
            dest='J' if mode=='refresh' else 'L'
            route=ground_observation(m,b2['node'],dest,True)
            if route is None:
                return reject('observer report cannot arrive fresh')
            load_at=transport_at+2*d+route['duration_ms'];movement+=route['movement_ms']
            if dest=='L':
                _,_,return_cost=travel('L','J',load_at,'B2')
                movement+=return_cost
        else:
            if coordinator!='L':
                return reject('coordinator must relocate before providing the fallback observation')
            route=ground_observation(m,'L','J',True)
            if route is None:
                return reject('no coordinator observation service can reach the delegate fresh')
            load_at=max(transport_at,committed+route['duration_ms']+d)
            movement+=route['movement_ms']
            observer_commands=[custom('commit_barrier'),custom('observe_for',target='J',receiver='B2')]
    end,outbound,cost=travel('L','D',load_at+s,actor);movement+=cost
    cargo_commands=entry+[custom('ready')]+[custom('fresh'),('load',cargo),custom('active')]+outbound+[('unload',cargo)] if actor=='B2' else [custom('commit_barrier'),custom('fresh'),('load',cargo)]+outbound+[('unload',cargo)]
    c['own_commands']=cargo_commands if actor=='B1' else observer_commands+[('hold',None)]
    if actor=='B2':
        c['peer_commands']['B2']=cargo_commands
    if air_commands:
        c['peer_commands']['B3']=air_commands
    c.update(required=required,request_at=request_at,transport_cached=cached,
        requires_new_report=not cached,migration_ms=movement,
        handoff_gap_ms=max(0,load_at-transport_at) if actor=='B2' else 0)
    c['deliveries_ms'][('blue1','blue2').index(cargo)]=end+s
    c['sampling_ms']=[load_at]
    c['score']=(int(end+s<=tasks[cargo]['deadline_ms']),-movement,-c['handoff_gap_ms'])
    return c
