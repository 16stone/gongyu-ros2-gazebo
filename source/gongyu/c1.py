"""Appendix-B three-robot checkpoint, sharing mission/network/resource semantics.

shortcut: C1 has fixed local route forecasts; replace them with remaining-task
forecasts before connecting contracts to the full six-robot M2 scenario.
"""
import heapq
from collections import deque
from dataclasses import asdict

from .communication import Network
from .contracts import ContractPeer,SlotExchange
from .mission import Mission,Channel,report_valid
from .model import Event,Report,LocalView


def simulate(air_deadline_ms=18000,delay_ms=1000,service=True):
    run_id=f'C1_d{delay_ms}_air{air_deadline_ms}_service{int(service)}'
    now=0;events=[];jobs=[];counter=0;sequence=0
    poses={'B1':'L','R1':'E','R5':'H','entrance':'entrance'}
    inbox={a:[] for a in poses};busy={};commands={a:deque() for a in ('B1','R1','R5')}
    active={a:0 for a in commands};completed={};violations=[];expired_slots=set()
    positions={'L':(0,0),'O':(0,3),'E':(1,0),'W':(4,0),'D':(5,0),'H':(1,3),'F':(5,3)}
    trajectory=[]
    mission=Mission({'blue':'device','red':'red_device'})
    mission.claimed['red']='R1';mission.inventory['R1']='red'
    channel=Channel(2000);slots=SlotExchange({'early':'B1','late':'R1'})
    starts={'early':20000,'late':28000}
    network=Network(delay_ms,lambda a,b:a==b or a in ('L','E','H','entrance') and b in ('L','E','H','entrance'))
    peers={'B1':ContractPeer('B1'),'R1':ContractPeer('R1',{
        'sampled_at':0,'valid_for_ms':6000,'deadline_ms':air_deadline_ms,'own_finish_with_service_ms':15000})}
    air_task=None;air_started=False;blue_started=False

    def emit(actor,kind,payload=None,task=None,cid=None):
        events.append(Event(run_id,f'e{len(events)+1:05d}',now,actor,kind,payload or {},task,cid))

    def send(sender,receiver,payload):
        nonlocal sequence
        sequence+=1;mid=f'{run_id}:m{sequence}'
        network.send(sender,receiver,payload,now,mid,'C1_exchange',poses)
        emit(sender,'message_queued',{'receiver':receiver,'message_id':mid,
            'payload':asdict(payload) if isinstance(payload,Report) else payload},cid='C1_exchange')

    def start(actor,kind,duration,target=None):
        nonlocal counter
        source=poses[actor]
        counter+=1;heapq.heappush(jobs,(now+duration,counter,actor,kind,target))
        busy[actor]=(kind,source,target,now,now+duration)
        if kind!='wait':
            active[actor]+=duration
        if kind in ('move','cross'):
            poses[actor]=None
        emit(actor,('load_service' if kind=='load' else kind)+'_started',{'source':source,'target':target,'duration_ms':duration})

    def blue_self():
        return [('move','O'),('observe',None),('move','L'),('load',None),
                ('move','E'),('cross',None),('move','D'),('unload','blue')]

    commands['R1'].extend([('cross',None),('move','D'),('unload','red')])
    start('R5','committed_observation',6000)
    emit('referee','run_started',{'backend':'graph_checkpoint_C1','service':service,
        'quote_delay_assumption_ms':1000,'actual_delay_ms':delay_ms,
        'boundary_injection':delay_ms!=1000,'pre20_occupancy':'given checkpoint reservations; causal prefix not simulated'})
    if service:
        for receiver,payload in peers['B1'].request():
            send('B1',receiver,payload)
        emit('B1','contract_state',{'state':'REQUESTED'},cid='C1_exchange')
    else:
        commands['B1'].extend(blue_self());blue_started=True

    for now in range(0,60001,100):
        while jobs and jobs[0][0]<=now:
            _,_,actor,kind,target=heapq.heappop(jobs)
            del busy[actor]
            if kind in ('move','cross'):
                poses[actor]=target
                if kind=='cross':
                    channel.leave(actor,now)
                    emit(actor,'channel_cleared',{})
            elif kind=='observe':
                report=Report(actor,'device',now,20000,1.,poses[actor])
                mission.receive(actor,report)
                emit(actor,'observation_completed',{'report':asdict(report)})
                if actor=='R5':
                    send(actor,'B1',report)
            elif kind=='load':
                mission.finish_load(actor,'blue')
            elif kind=='unload':
                if not mission.deliver(actor,poses[actor]):
                    raise ValueError('delivery requires actual cargo at D')
                completed[target]=now
                emit(actor,'delivery',{'on_time':now<=({'blue':39000,'red':31000}[target])},target)
            elif kind=='inspect':
                if poses[actor]!='F':
                    raise ValueError('air inspection requires arrival at F')
                completed['red_inspect']=now
                emit(actor,'inspection',{'on_time':now<=air_deadline_ms},'red_inspect')
            emit(actor,kind+'_completed',{'target':target})
        failed_before=len(network.failures)
        for m in network.advance(now,poses):
            inbox[m.receiver].append(m)
            emit(m.receiver,'message_arrived',{'sender':m.sender,'message_id':m.message_id,
                'sampled_at':m.payload.sampled_at if isinstance(m.payload,Report) else None,
                'payload':asdict(m.payload) if isinstance(m.payload,Report) else m.payload},cid=m.contract_id)
            if isinstance(m.payload,Report):
                mission.receive(m.receiver,m.payload)
                peer=peers['B1'];q=peer.quote
                if (peer.state=='ACTIVE' and q and now<=q['report_by_ms']
                    and report_valid(m.payload,q['subject_id'],now)
                    and m.payload.quality>=q['minimum_quality']
                    and 0<=now-m.payload.sampled_at<=q['maximum_age_ms']):
                    peer.state='FULFILLED'
                    emit('B1','contract_state',{'state':'FULFILLED','report_sample_ms':m.payload.sampled_at,
                        'report_received_ms':now,'quality':m.payload.quality},cid='C1_exchange')
                    send('B1','R1',{'kind':'fulfilled','contract_id':'C1_exchange',
                        'report_sample_ms':m.payload.sampled_at,'accepted_at_ms':now})
            elif m.receiver=='entrance' and m.payload.get('kind') in ('accept','confirm'):
                before=slots.commits
                committed=slots.confirm(m.sender,m.payload['quote'],now)
                if slots.commits!=before:
                    emit('entrance','slot_exchange_committed',{'owners':dict(slots.owners)},cid='C1_exchange')
                if committed:
                    for actor in ('B1','R1'):
                        send('entrance',actor,{'kind':'commit','contract_id':'C1_exchange','quote':m.payload['quote']})
            elif m.receiver=='R5' and m.sender=='R1' and m.payload.get('kind')=='service_task':
                air_task=m.payload
        for _,mid,reason in network.failures[failed_before:]:
            emit('network','message_failed',{'message_id':mid,'reason':reason})
        for actor,peer in peers.items():
            before=peer.state
            own=({'id':'blue','deadline_ms':39000},) if actor=='B1' else ({'id':'red','deadline_ms':31000},)
            view=LocalView(actor,now,poses[actor],inbox=tuple(inbox[actor]),own_tasks=own)
            for receiver,payload in peer.step(view):
                send(actor,receiver,payload)
            if peer.state!=before:
                emit(actor,'contract_state',{'state':peer.state,'candidates':peer.candidates},cid='C1_exchange')
                if peer.state=='EXPIRED':
                    emit(actor,'contract_expired',{'accept_by_ms':peer.quote['accept_by_ms']},cid='C1_exchange')
        if not blue_started and (peers['B1'].state=='FULFILLED' or peers['B1'].state in ('REJECTED','EXPIRED','FAILED')):
            if peers['B1'].state=='FULFILLED':
                commands['B1'].extend([('load',None),('move','E'),('cross',None),('move','D'),('unload','blue')])
            else:
                commands['B1'].extend(blue_self())
            blue_started=True
        if not air_started and now>=6000 and 'R5' not in busy:
            if air_task:
                commands['R5'].extend([('observe',None),('wait',1000),('move','F'),('inspect',None)])
            else:
                commands['R5'].extend([('move','F'),('inspect',None)])
            air_started=True
        for slot,start_ms in starts.items():
            if now>start_ms+2000 and slot not in expired_slots:
                expired_slots.add(slot)
                emit('entrance','reservation_expired',{'slot':slot,'owner':slots.owners[slot]})
        for actor in commands:
            if actor in busy or not commands[actor]:
                continue
            kind,target=commands[actor][0]
            if kind=='cross':
                if poses[actor]!='E':
                    raise ValueError('channel entry requires actual arrival at E')
                owned=next((s for s in starts if slots.owners[s]==actor and s not in expired_slots),None)
                if owned:
                    allowed=starts[owned]<=now<=starts[owned]+2000
                else:
                    future=[v for s,v in starts.items() if s not in expired_slots and v+6000>now]
                    allowed=now>=20000 and all(now+8000<=v for v in future)
                if not allowed or not channel.enter(actor,now):
                    continue
                emit(actor,'channel_enter',{'slot_owners_observed_locally':dict(slots.owners)})
                start(actor,'cross',6000,'W')
            elif kind=='move':
                duration={frozenset(('L','O')):6000,frozenset(('L','E')):2000,
                    frozenset(('W','D')):2000,frozenset(('H','F')):4000}[frozenset((poses[actor],target))]
                start(actor,'move',duration,target)
            elif kind=='observe':
                if poses[actor] not in ('H','O'):
                    raise ValueError('observation requires a permitted checkpoint region')
                start(actor,'observe',2000)
            elif kind=='load':
                report=mission.reports.get((actor,'device'))
                mission.start_load(actor,'blue',now,poses[actor])
                emit(actor,'load_started',{'report_age_ms':now-report.sampled_at,'sampled_at':report.sampled_at},'blue')
                start(actor,'load',2000)
            elif kind=='unload':
                start(actor,'unload',2000,target)
            elif kind=='inspect':
                start(actor,'inspect',2000)
            elif kind=='wait':
                start(actor,'wait',target)
            commands[actor].popleft()
        for actor in commands:
            if actor in busy and busy[actor][0] in ('move','cross'):
                _,source,target,t0,t1=busy[actor];fraction=(now-t0)/(t1-t0)
                a,b=positions[source],positions[target]
                x,y=(a[i]+fraction*(b[i]-a[i]) for i in (0,1))
            else:
                x,y=positions[poses[actor]]
            trajectory.append({'t_ms':now,'actor':actor,'x':x,'y':y,'node':poses[actor]})
    entries=[e for e in events if e.kind=='channel_enter']
    for first,second in zip(entries,entries[1:]):
        if second.t_ms<first.t_ms+8000:
            violations.append({'kind':'channel_gap','t_ms':second.t_ms})
    for e in events:
        if e.kind=='load_started' and not 0<=e.payload['report_age_ms']<=20000:
            violations.append({'kind':'invalid_load_report','t_ms':e.t_ms})
    emit('referee','run_finished',{'completed':completed,'constraint_violations':violations})
    return {'run_id':run_id,'completed':completed,'active_ms':active,
        'waiting_ms':{'B1':completed.get('blue',60000)-active['B1']},
        'contracts':{a:p.state for a,p in peers.items()},'slot_commits':slots.commits,
        'events':events,'trajectories':trajectory,'violations':violations,
        'limitations':['three-robot checkpoint, not six-robot M2 or physical execution',
            'fixed Appendix-B local forecasts; pre20 traffic and initial air status supplied at checkpoint',
            '3-second delay case is an injected fixed-quote protocol boundary, not an informed online quote']}
