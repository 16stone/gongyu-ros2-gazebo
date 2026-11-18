import heapq
import copy
import json
from dataclasses import asdict
from pathlib import Path

from .communication import Network,ImpairedNetwork
from .mission import Channel, Mission
from .model import Event, LocalView, Report
from .geometry import Geometry,path_length
from .timing import edge_times,travel_ms


def load_card(path):
    card = json.loads(Path(path).read_text(encoding='utf-8'))
    if card['step_ms'] <= 0 or card['message_delay_ms'] <= 0:
        raise ValueError('positive timestep and message delay required')
    jitter = card.get('channel_jitter_ms',0)
    loss = card.get('channel_loss_rate',0.0)
    if type(jitter) is not int or not 0 <= jitter < card['message_delay_ms']:
        raise ValueError('channel jitter must be an int below the nominal message delay')
    if not isinstance(loss,(int,float)) or not 0 <= loss < 1:
        raise ValueError('channel loss rate must lie in [0, 1)')
    if card.get('controller_sees_channel') and not jitter and not loss:
        raise ValueError('controller_sees_channel requires a jitter or loss setting')
    if card.get('m2') and card['m2'].get('arbitration','central') not in ('central','peer'):
        raise ValueError('slot arbitration must be central or peer')
    if 'target_mode' in card:
        from .modes import MODES
        limits=card.get('target_constraints',{});budgets=limits.get('movement_budget_ms',{})
        if (card['target_mode'] not in MODES or set(budgets)!={a for a in card['fleet'] if a.startswith('R')}
            or any(type(v) is not int or v<=0 for v in budgets.values())
            or limits.get('minimum_on_time_deliveries')!={'R1':1,'R2':1}
            or limits.get('observation_nodes',['E']) not in (['E'],['E','L'])
            or any(type(limits.get(k)) is not int or limits[k]<=0 for k in ('observation_period_ms','observation_max_age_ms'))):
            raise ValueError('invalid target mode, movement budgets or traffic observation limits')
    graph = {}
    for a,b in card['task_dependencies']:
        graph.setdefault(a,[]).append(b)
    visiting,done = set(),set()
    def visit(v):
        if v in visiting:
            raise ValueError('cyclic task dependency')
        if v in done:
            return
        visiting.add(v)
        for u in graph.get(v,[]):
            visit(u)
        visiting.remove(v)
        done.add(v)
    for node in graph:
        visit(node)
    counts = {}
    for spec in card['fleet'].values():
        if spec['node'] not in card['nodes'] or spec['mode'] not in ('ground','air'):
            raise ValueError('invalid initial fleet state')
        counts[spec['node']] = counts.get(spec['node'],0)+1
    if any(n > card['berth_capacity'][node] for node,n in counts.items()):
        raise ValueError('initial berth capacity exceeded')
    if 'geometry' in card:
        for key,points in card['geometry']['edge_polylines'].items():
            a,b=key.split('>')
            edge=next((e for e in card['edges'] if {e[0],e[1]}=={a,b}),None)
            if edge is None or abs(path_length(points)-edge[2])>1e-6:
                raise ValueError('Geometry polyline length must match frozen movement edge')
            if list(points[0][:2])!=card['nodes'][a][:2] or list(points[-1][:2])!=card['nodes'][b][:2]:
                raise ValueError('Geometry polyline endpoints mismatch')
    return card


def without_red_traffic(card):
    card = copy.deepcopy(card)
    card['id'] = 'M1_no_red_channel'
    card['red_channel_enabled'] = False
    for actor in ('R1','R2'):
        card['fleet'][actor]['node'] = 'D'
    card['note'] += ' Causal ablation: R1/R2 initially parked in D berths; their delivery tasks remain unfinished in denominator.'
    return card


class World:
    def __init__(self, card, run_id):
        self.card,self.run_id = card,run_id
        self.now = 0
        self.events,self.violations = [],[]
        self.poses = {a:s['node'] for a,s in card['fleet'].items()}
        self.busy,self.inbox,self.jobs = {},{a:[] for a in self.poses},[]
        self.held_for_berth = []
        self.counter = 0
        self.geometry=Geometry(card['geometry']) if 'geometry' in card else None
        self.edges = {}
        durations=edge_times(card)
        for a,b,length,mode in card['edges']:
            for source,target in ((a,b),(b,a)):
                self.edges[source,target] = (durations[source,target],mode)
        radio = {frozenset(x) for x in card['radio_edges']}
        radio.update(frozenset(('entrance',n)) for n in ('L','E','W'))
        link = self.geometry.radio if self.geometry else (lambda a,b: a==b or frozenset((a,b)) in radio)
        jitter = int(card.get('channel_jitter_ms',0))
        loss = float(card.get('channel_loss_rate',0.0))
        # Registered cards carry no impairment keys, so they keep the frozen
        # fixed-delay link and stay bit-for-bit reproducible.
        self.network = (ImpairedNetwork(card['message_delay_ms'],link,jitter,loss,card['seed'])
                        if jitter or loss else Network(card['message_delay_ms'],link))
        # Impairment is applied to the link either way; publishing it in the shared
        # view is the separate controller-awareness condition. Registered cards set
        # neither key, so their views stay exactly as frozen.
        self.channel_impairment = ({'nominal_message_delay_ms':card['message_delay_ms'],
                                    'jitter_ms':jitter,'loss_rate':loss}
                                   if card.get('controller_sees_channel') else None)
        self.channel = Channel(card['channel_gap_ms'])
        self.mission = Mission(card['cargo'])
        self.station = 'red_station'
        self.poses[self.station] = self.station
        self.poses['entrance'] = 'entrance'
        self.reservations = []
        self.tasks = {x['id']:x for x in card['tasks']}
        self.inspection_sources=card.get('g2',{}).get('reports_from',{})
        if len(set(self.inspection_sources.values()))!=len(self.inspection_sources):raise ValueError('inspection report has multiple sources')
        for source,target in self.inspection_sources.items():
            a=self.tasks.get(source,{});b=self.tasks.get(target,{})
            if (not card.get('g2',{}).get('manual_inspection_reports') or a.get('kind')!='inspection' or b.get('kind')!='report_delivery'
                or a.get('actor') not in card['fleet'] or any(a.get(k)!=b.get(k) for k in ('actor','region','mode'))):
                raise ValueError('inspection/report linkage requires the same actual actor, mode and region')
        for actor,t in card['initial_reports'].items():
            self.mission.receive(actor,Report('B2','device',t,card['tau_ms'],1,'O'))
        for actor,cargo in (('R1','red1'),('R2','red2')):
            self.mission.claimed[cargo] = actor
            self.mission.inventory[actor] = cargo
        self.completed = {}
        self.inspection_reports={a:{} for a in self.card['fleet']};self.inspection_receipts={}
        self.report_copies={a:{} for a in self.card['fleet']}
        self.station_receipt_copies={}
        self.local_results={a:{} for a in self.card['fleet']}
        self.local_assignments={a:set() for a in self.card['fleet']}
        for task in card['tasks']:
            actor=task.get('actor') or self.mission.claimed.get(task['id'])
            if actor is None and task['team']=='B' and task['kind']=='delivery':
                actor='B1'
            if actor:
                self.local_assignments[actor].add(task['id'])
        for task_id,receipt in card.get('initial_completed',{}).items():
            task=self.tasks.get(task_id);actor=receipt['actor'];at=receipt['completed_ms']
            if (not task or actor not in self.card['fleet'] or at>0 or task.get('actor',actor)!=actor
                or at<task.get('release_ms',0)
                or task.get('kind')=='delivery' and self.card['fleet'][actor]['mode']!='ground'
                or self.mission.claimed.get(task_id,actor)!=actor):
                raise ValueError('invalid pre-checkpoint completion')
            self.completed[task_id]=at;self.local_results[actor][task_id]=at
            self.local_assignments[actor].add(task_id)
            if task_id in self.card['cargo']:
                self.mission.claimed[task_id]=actor;self.mission.delivered.append(task_id)
                if self.mission.inventory.get(actor)==task_id:
                    self.mission.inventory.pop(actor)
        self.trajectories = []
        self.decisions = []
        self.diagnostics = []
        self.slot_exchange=None
        self.peer_commits={}
        self.movement_committed_ms={a:0 for a in card['fleet']}
        self.entrance_wait_since={};self.last_entrance_observation=-1000;self.budget_exhausted=set()
        # phase112: monotonic counter used by the rolling re-plan layer.
        self.channel_release_recomputed=0

    def emit(self,actor,kind,payload=None,task_id=None,caused_by=None,contract_id=None):
        event = Event(self.run_id,str(len(self.events)+1),self.now,actor,kind,payload or {},task_id,contract_id=contract_id,caused_by=caused_by)
        self.events.append(event)
        return event.event_id

    def later(self,at,actor,kind,payload):
        self.counter += 1
        heapq.heappush(self.jobs,(at,self.counter,actor,kind,payload))

    def reserve(self,actor,earliest,direction=None,exchangeable=False):
        if direction is not None and set(direction)!={'E','W'}:
            raise ValueError('channel booking direction must name E and W')
        duration = self.edges[tuple(direction) if direction is not None else ('E','W')][0]
        start = max(earliest,self.now)
        for r in sorted(self.reservations,key=lambda x:x['start']):
            if r.get('cancelled_at') is not None:
                continue
            if start+duration+self.channel.gap <= r['start']:
                break
            if start < r['end']+self.channel.gap:
                start = r['end']+self.channel.gap
        r = {'actor':actor,'start':start,'end':start+duration,'used':False}
        if direction is not None:
            r.update(direction=list(direction),slot_id=f'{actor}_{start}',revision=0,exchangeable=exchangeable)
        self.reservations.append(r)
        self.emit(actor,'reservation_granted',dict(r))
        self.broadcast_reservation(r,f'reservation_{actor}_{start}')
        return r

    def initialize_bookings(self):
        if self.card.get('m2'):
            self.reserve('R2',self.card['red_release_ms'][1],direction=('E','W'))
            self.reserve('R1',self.card['m2']['red_future_ms'],direction=('E','W'),exchangeable=True)
            self.reserve('B1',self.card['m2']['blue_future_ms'],direction=('E','W'),exchangeable=True)
        elif self.card['red_channel_enabled']:
            for actor,release in zip(('R1','R2'),self.card['red_release_ms']):
                self.reserve(actor,release,direction=('E','W') if self.card.get('travel_time_ms') else None)

    def broadcast_reservation(self,r,prefix):
        for receiver,spec in self.card['fleet'].items():
            if spec['mode']=='ground':
                self.send('entrance',receiver,{'kind':'reservation','reservation':dict(r)},
                          f'{prefix}_{receiver}')

    def grant_may_expire(self,r,now):
        """Hook for backends that can keep a lawful grant alive.

        Graph-model runs keep the historical rule: an unused grant expires
        reservation_grace_ms after its nominal start.  Physical backends
        override this when the holder is queued at the entrance while the
        single-capacity channel is still occupied (phase113 execution repair).
        """
        return True

    def release_booking(self,r,kind):
        r['cancelled_at']=self.now;r['revision']+=1
        self.emit('entrance',kind,dict(r))
        self.broadcast_reservation(r,f'{kind}_{r["slot_id"]}_{r["revision"]}')

    def cancel_reservation(self,actor,slot_id):
        r=next((r for r in self.reservations if r.get('slot_id')==slot_id),None)
        if r is None or r['actor']!=actor or r['used']:
            return False
        if r.get('cancelled_at') is not None:
            return True
        if self.slot_exchange and any(slot_id in q['slots'] and self.now<=q['accept_by_ms']
                                     for q,_ in self.slot_exchange.pending.values()):
            return False
        self.release_booking(r,'reservation_cancelled')
        return True

    def slot_owners(self):
        """Who holds which slot, as the exchange gate would certify it.

        A request, not a read: a unit under strict isolation cannot see the booking
        table, so the authority that already arbitrates the trade answers this when
        asked. The returned mapping is exactly the rows `exchange_gate` certifies,
        which is why a per-entity replica built from it is not a second opinion.
        """
        return {r['slot_id']: r['actor'] for r in self.reservations if r.get('slot_id')}

    def exchange_gate(self, quote):
        """Physical truth of a slot trade: real bookings that are still free on a free channel.

        Read-only and never authoritative. Central arbitration consults it before
        matching the two confirms; peer arbitration consults it in each owner before
        closing its own replica, so decentralising the award keeps the same
        occupancy guarantee.
        """
        rows = {r.get('slot_id'):r for r in self.reservations if r.get('exchangeable')}
        chosen = [rows.get(s) for s in quote['slots']]
        if len(chosen) != 2 or any(r is None for r in chosen):
            return False, 'unknown_bookings'
        for key,r in zip(('blue_slot','red_slot'),chosen):
            if key in quote and any(quote[key].get(k)!=r.get(k) for k in ('slot_id','start','end','direction')):
                return False, 'quote_mismatch'
        if any(r['used'] or r.get('cancelled_at') is not None or self.now>=r['start'] for r in chosen) or self.now>quote['accept_by_ms']:
            return False, 'unavailable'
        if [r['actor'] for r in chosen]!=quote['parties']:
            return False, 'wrong_parties'
        if self.channel.occupant is not None:
            return False, 'channel_occupied'
        return True, ''

    GATE_ERRORS = {'unknown_bookings':'exchange requires two real transferable bookings',
                   'quote_mismatch':'quoted time or direction differs from the actual booking',
                   'wrong_parties':'exchange parties do not own the stated bookings'}

    def apply_owner_swap(self, quote, rows):
        owners = dict(zip(quote['slots'],reversed(quote['parties'])))
        for slot,actor in owners.items():
            r = rows[slot]
            r['actor'] = actor
            r['revision'] += 1
            self.broadcast_reservation(r,f'exchange_{quote["contract_id"]}_{slot}')
        return owners

    def exchange_slots(self,sender,quote):
        from .contracts import SlotExchange
        cid=quote['contract_id']
        if self.slot_exchange and cid in self.slot_exchange.committed:
            return self.slot_exchange.confirm(sender,quote,self.now)
        feasible,reason = self.exchange_gate(quote)
        if not feasible:
            if reason in self.GATE_ERRORS:
                raise ValueError(self.GATE_ERRORS[reason])
            if reason == 'channel_occupied':
                self.emit('entrance','slot_exchange_deferred',{'contract_id':cid,'reason':'channel physically occupied'},contract_id=cid)
            return False
        rows={r.get('slot_id'):r for r in self.reservations if r.get('exchangeable')}
        if self.slot_exchange is None:
            self.slot_exchange=SlotExchange({s:r['actor'] for s,r in rows.items()})
        before=self.slot_exchange.commits
        committed=self.slot_exchange.confirm(sender,quote,self.now)
        if self.slot_exchange.commits!=before:
            self.apply_owner_swap(quote,rows)
            self.emit('entrance','slot_exchange_committed',{'contract_id':cid,'owners':dict(self.slot_exchange.owners)},contract_id=cid)
        return committed

    def bilateral_recorded(self,quote):
        """True when the ledger already holds exactly this agreed peer commit."""
        return self.peer_commits.get(quote['contract_id'])==quote

    def record_bilateral_commit(self,sender,quote):
        """File the owners' peer agreement with the berth ledger, once and idempotently.

        The ledger is a record keeper here, not an arbiter: it cannot veto a
        physically valid trade that both owners already confirmed, it only reflects
        the agreed owner swap so the entry check keeps using real bookings.
        """
        cid=quote['contract_id']
        if sender not in quote['parties']:
            raise ValueError('only an exchange party may file a bilateral commit')
        already = cid in self.peer_commits
        if already and self.peer_commits[cid]!=quote:
            raise ValueError('bilateral parties disagree on the committed quote')
        applied = False
        if not already:
            feasible,reason = self.exchange_gate(quote)
            if not feasible:
                if reason == 'channel_occupied':
                    self.emit('entrance','slot_exchange_deferred',{'contract_id':cid,'reason':'channel physically occupied'},contract_id=cid)
                return False
            rows={r.get('slot_id'):r for r in self.reservations if r.get('exchangeable')}
            owners=self.apply_owner_swap(quote,rows)
            self.peer_commits[cid]=copy.deepcopy(quote)
            self.emit('entrance','slot_exchange_committed',{'contract_id':cid,'owners':owners,'arbitration':'peer'},contract_id=cid)
            applied = True
        self.send('entrance',sender,{'kind':'m2_record_ack','contract_id':cid},f'record_ack_{cid}_{sender}')
        return applied

    @property
    def berth_occupancy(self):
        """How many parking slots are claimed at each node.

        A unit may legitimately know that a slot is taken -- it can see the
        vehicle -- without knowing which private table says so.  Publishing the
        count keeps `berth_free` answerable across a process boundary while
        leaving the claims table itself in the referee.
        """
        berths = getattr(self, 'berths', None)
        claims = getattr(berths, 'claims', None) or {}
        counts = {}
        for (_actor, node) in claims:
            counts[node] = counts.get(node, 0) + 1
        return counts

    def view(self,actor):
        status,reservations = {},{}
        released={}
        for message in self.inbox[actor]:
            p = message.payload
            if isinstance(p,dict) and p.get('kind')=='status':
                old = status.get(message.sender)
                if old is None or p['observed_at']>=old['observed_at']:
                    status[message.sender] = p
            if isinstance(p,dict) and p.get('kind') in ('reservation','reservation_cancel_ack') and isinstance(p.get('reservation'),dict):
                r = p['reservation']
                key=r.get('slot_id',(r['actor'],r['start']))
                if key not in reservations or r.get('revision',0)>=reservations[key].get('revision',0):
                    reservations[key]=r
            if isinstance(p,dict) and p.get('kind')=='release_ack':
                released[message.sender]=max(released.get(message.sender,-1),p.get('released_at',-1))
        status={peer:s for peer,s in status.items() if s['observed_at']>=released.get(peer,-1)}
        public = {k:self.card[k] for k in ('edges','ground_speed','air_speed','service_ms',
                   'message_delay_ms','tau_ms','channel_gap_ms','end_ms','reconnect_period_ms')}
        public['radio_edges']=self.card['radio_edges']
        public['online_replanning']=self.card.get('online_replanning',False)
        if self.channel_impairment:public['channel_impairment']=dict(self.channel_impairment)
        public['reservation_grace_ms']=self.card['reservation_grace_ms']
        public['step_ms']=self.card['step_ms']
        if self.card.get('target_mode') and actor.startswith('R'):
            limits=self.card['target_constraints']
            public['target_constraints']=dict(move_budget_ms=limits['movement_budget_ms'][actor],spent_move_ms=self.movement_committed_ms[actor],
                observation_max_age_ms=limits['observation_max_age_ms'],
                observation_period_ms=limits['observation_period_ms'],
                on_time_required=limits['minimum_on_time_deliveries'].get(actor,0)>0)
        if self.card.get('g2'):
            public['hardware']={a:dict(mode=s['mode'],payload_interface=s.get('payload_interface',s['mode']=='ground') is True)
                                for a,s in self.card['fleet'].items()}
        for key in ('travel_time_ms','protocol_margin_ms','physical_contact_hold_ms','departure_clearance_ms','physical_departure_clearance_m'):
            if key in self.card:public[key]=copy.deepcopy(self.card[key])
        if self.geometry:
            public.update(geometry=self.card['geometry'],nodes=self.card['nodes'])
        public['shared_blue_plan'] = {'air_inspection_expected_ms':12000,
                                      'air_inspection_deadline_ms':next(t['deadline_ms'] for t in self.card['tasks'] if t['id']=='blue_inspect')}
        if public.get('physical_contact_hold_ms'):
            public['shared_blue_plan']['air_inspection_expected_ms']=(max(6000,travel_ms(public,'F','K')
                +public['physical_contact_hold_ms'])+travel_ms(public,'K','F')+public['service_ms'])
        own_tasks = tuple({**t,'completed_ms':self.local_results[actor].get(t['id'])} for t in self.card['tasks']
                          if t['id'] in self.local_assignments[actor])
        return LocalView(actor,self.now,self.poses[actor],
                         tuple(r for (a,_),r in self.mission.reports.items() if a==actor),
                         tuple(self.inbox[actor]),own_tasks,public,status,tuple(reservations.values()),self.mission.inventory.get(actor),
                         inspection_reports=tuple(copy.deepcopy(r) for r in self.inspection_reports[actor].values()))

    def node_position(self,actor,node):
        if self.geometry and node in self.card['geometry']['infrastructure']:
            return tuple(self.card['geometry']['infrastructure'][node])
        x,y=self.card['nodes'][node][:2]
        if not self.geometry:
            return x,y,0.
        spec=self.card['fleet'][actor]
        mode='ground' if spec['mode']=='ground' else 'blue_air' if actor.startswith('B') else 'red_air'
        return x,y,self.card['geometry']['heights'][mode]

    def radio_positions(self):
        if not self.geometry:
            return self.poses
        return {actor:self.node_position(actor,node) if node is not None else None for actor,node in self.poses.items()}

    def edge_points(self,actor,source,target):
        if self.geometry:
            polylines=self.card['geometry']['edge_polylines']
            if f'{source}>{target}' in polylines:
                return polylines[f'{source}>{target}']
            if f'{target}>{source}' in polylines:
                return list(reversed(polylines[f'{target}>{source}']))
        return [self.node_position(actor,source),self.node_position(actor,target)]

    def departure_ready(self,actor,source,target):
        gap=self.card.get('departure_clearance_ms',0)
        if self.card['fleet'][actor]['mode']!='ground':return True
        return not any(peer!=actor and job[0]=='move' and job[1:3]==(source,target)
            and self.now<job[3]+gap for peer,job in self.busy.items())

    def berth_room_at(self,actor,node):
        """Whether this unit may take a parking position at `node` right now.

        `berth_capacity` is a card constraint that only the referee used to read, and it read it
        after the fact -- three units parked at a two-berth node on a legal card with a short
        message delay produced 25 violations instead of a queue. The reservation machinery covers
        the E-W corridor and nothing covered the node.
        """
        capacity=self.card['berth_capacity'].get(node)
        if capacity is None:return True
        return sum(1 for peer in self.card['fleet'] if self.poses[peer]==node)+1<=capacity

    def hold_for_berth(self,actor,payload,job):
        """Park the unit outside the node until a position frees, without refusing the move.

        Refusing the departure instead would be pessimistic in a way the channel scheduler
        deliberately is not: the destination may empty during the traversal, and nothing schedules
        a local departure, so a snapshot of who sits there now cannot prove the arrival illegal.
        The traversal window stays in `busy`, so the unit keeps its actuator and stays radio-silent
        exactly like a unit still in transit, and its trajectory pins at the node mouth. The
        corridor it came through is already cleared, so a hold cannot deadlock the very departure
        that would free the position it is waiting for.
        """
        if job is not None:self.busy[actor]=job
        self.held_for_berth.append({'actor':actor,'node':payload['node'],'from':payload['from'],
                                    'held_at':self.now})
        self.emit(actor,'berth_hold',dict(payload,held_at_ms=self.now))

    def admit_waiting(self,node):
        """Hand a freed position to the unit that has waited longest, then let it arrive.

        One departure frees one position, so at most one unit is admitted per call. `berth_room_at`
        does not look at the unit, so if the head of the queue cannot enter, nobody behind it can.
        """
        held=next((h for h in self.held_for_berth if h['node']==node),None)
        if held is None or not self.berth_room_at(held['actor'],node):return
        self.held_for_berth.remove(held)
        self.busy.pop(held['actor'],None)
        self.poses[held['actor']]=node
        self.emit(held['actor'],'arrived',{'node':node,'from':held['from'],
                                           'held_ms':self.now-held['held_at']})

    def start_move(self,actor,target,now=None):
        if now is not None:
            self.now = now
        source = self.poses[actor]
        edge = self.edges.get((source,target))
        if edge is None or edge[1] != self.card['fleet'][actor]['mode']:
            raise ValueError(f'illegal edge {actor}: {source}->{target}')
        if actor in self.busy:
            return False
        cargo=self.mission.inventory.get(actor)
        if cargo and self.now<self.tasks[cargo].get('release_ms',0):return False
        if self.card.get('target_mode') and actor.startswith('R') and self.movement_committed_ms[actor]+edge[0]>self.card['target_constraints']['movement_budget_ms'][actor]:
            if actor not in self.budget_exhausted:self.budget_exhausted.add(actor);self.emit(actor,'target_movement_budget_exhausted',dict(spent_ms=self.movement_committed_ms[actor],requested_ms=edge[0]))
            return False
        if not self.departure_ready(actor,source,target):return False
        if {source,target} == {'E','W'}:
            r = next((r for r in self.reservations if r['actor']==actor and not r['used'] and r.get('cancelled_at') is None
                      and r.get('direction',[source,target])==[source,target]),None)
            if r is None:
                r = self.reserve(actor,self.now,direction=(source,target) if self.card.get('m2') or self.card.get('travel_time_ms') else None)
            if self.now < r['start']:
                return False
            if self.now > r['start']+self.card['reservation_grace_ms'] and self.grant_may_expire(r,self.now):
                r['used'] = True
                if r.get('slot_id'):
                    r['revision']+=1
                self.emit(actor,'reservation_expired',dict(r))
                return False
            if not self.channel.enter(actor,self.now):
                return False
            r['used'] = True
            if r.get('slot_id'):
                r['revision']+=1
            self.emit(actor,'channel_enter',{'from':source,'to':target})
        duration = edge[0]
        self.movement_committed_ms[actor]+=duration
        self.busy[actor] = ('move',source,target,self.now,self.now+duration)
        self.poses[actor] = None
        self.emit(actor,'move_started',{'from':source,'to':target,'duration_ms':duration})
        self.later(self.now+duration,actor,'arrived',{'node':target,'from':source})
        self.admit_waiting(source)
        return True

    def service(self,actor,kind,task_id=None):
        if kind in ('load','unload') and self.card['fleet'][actor].get('payload_interface',self.card['fleet'][actor]['mode']=='ground') is not True:
            raise ValueError('actor has no payload interface')
        if actor in self.busy:
            return False
        if task_id in self.tasks and self.now<self.tasks[task_id].get('release_ms',0):return False
        node = self.poses[actor]
        if kind == 'inspect':
            if self.card.get('g2',{}).get('manual_inspection_reports') and task_id in self.completed:raise ValueError('inspection task already completed')
            if task_id in self.inspection_sources.values():raise ValueError('delivery report is produced by its source inspection')
            if task_id in self.inspection_reports[actor]:raise ValueError('inspection report already issued')
            task = self.tasks.get(task_id,{})
            if (task.get('kind') not in ('inspection','report_delivery') or task.get('actor') != actor
                    or task.get('region') != node or task.get('mode') != self.card['fleet'][actor]['mode']):
                raise ValueError('inspection requires assigned actor, sensor mode and region')
        if kind == 'observe':
            visible=self.geometry.can_observe(self.node_position(actor,node),self.card['fleet'][actor]['mode']) if self.geometry else node in self.card['observation_nodes']
            if not visible:
                raise ValueError('device not observable from this position, capability and occlusion')
        if kind == 'load':
            self.mission.start_load(actor,task_id,self.now,node,
                                    self.card['fleet'][actor]['mode']=='ground')
            r = self.mission.reports[actor,self.card['cargo'][task_id]]
            self.local_assignments[actor].add(task_id)
            self.emit(actor,'load_started',{'report_age_ms':self.now-r.sampled_at,'report':asdict(r)},task_id)
        if kind == 'unload' and (node != 'D' or actor not in self.mission.inventory):
            raise ValueError('unload without cargo or arrival')
        self.busy[actor] = (kind,node,node,self.now,self.now+self.card['service_ms'])
        if kind != 'load':
            self.emit(actor,kind+'_started',{'node':node},task_id)
        self.later(self.now+self.card['service_ms'],actor,kind+'_completed',{'node':node,'task_id':task_id})
        return True

    def retry_station_report(self,actor):
        """Re-offer a station report whose receipt has not come back.

        Reliability belongs to the sender, not to the environment: the grace window is a
        round trip plus the link's own jitter, so a healthy link never re-sends anything,
        and a lost receipt stops being a task that can never finish.
        """
        pending=self.report_copies[actor]
        if not pending:return
        grace=3*self.network.delay+getattr(self.network,'jitter',0)
        for task_id,state in list(pending.items()):
            if self.local_results[actor].get(task_id) is not None:
                pending.pop(task_id)
            elif self.now-state['sent_at']>=grace:
                state['copies']+=1;state['sent_at']=self.now
                self.send(actor,self.station,{'kind':'inspection_report','task_id':task_id},
                          f'inspection_{task_id}_r{state["copies"]}')
                self.emit(actor,'report_retransmitted',{'task_id':task_id,'copies':state['copies'],
                                                        'grace_ms':grace})

    def send(self,actor,target,payload,message_id,contract_id=None):
        override=self.card.get('message_delay_overrides',{}).get(payload.get('kind')) if isinstance(payload,dict) else None
        cid=contract_id or (payload.get('contract_id') if isinstance(payload,dict) else None)
        queued=self.network.send(actor,target,payload,self.now,message_id,poses=self.radio_positions(),delay_ms=override,contract_id=cid)
        if queued is None:
            self.emit(actor,'duplicate_send_ignored',{'to':target,'message_id':message_id})
            return
        self.emit(actor,'message_queued',{'to':target,'message_id':message_id,
                                         'payload':asdict(payload) if isinstance(payload,Report) else payload},contract_id=cid)

    def recompute_channel_release(self,actor,now):
        """Truncate a used grant to its real physical clearance (phase112).

        A forward-dated grant is a *nominal* 48 s allocation. The referee already
        emits `channel_cleared` when the actor physically leaves the channel; until
        this recompute, every downstream forecast still saw the unused remainder
        (150-198 s while the real hold was 150.008-177.374 s). Only the holder's
        own used, non-cancelled grant is shortened; the referee's on_time verdict,
        deadlines and quotas are untouched. A fresh broadcast with a higher
        revision makes every local view adopt the new end.
        """
        from .release_aware import enabled,measured_occupancy_ms
        if not enabled('release'):return None
        candidates=[r for r in self.reservations if r.get('actor')==actor
                    and r.get('used') and r.get('cancelled_at') is None
                    and r.get('start',0)<=now and r.get('end',0)>now]
        if not candidates:return None
        r=max(candidates,key=lambda x:x['start'])
        before=r['end']
        r['end']=now
        r['revision']=r.get('revision',0)+1
        self.channel_release_recomputed+=1
        payload={'actor':actor,'slot_id':r.get('slot_id'),'nominal_end_ms':before,
                 'effective_end_ms':now,'released_early_ms':before-now,
                 'measured_occupancy_ms':measured_occupancy_ms(self),
                 'at_ms':now,'revision':r['revision'],
                 'reason':'physical channel_cleared; unused nominal remainder no longer blocks lawful rebooking'}
        self.emit('entrance','channel_release_recomputed',payload)
        self.broadcast_reservation(r,'channel_release_%s_%s'%(r.get('slot_id','na'),r['revision']))
        return payload

    def advance(self,now):
        self.now = now
        while self.jobs and self.jobs[0][0] <= now:
            at,_,actor,kind,p = heapq.heappop(self.jobs)
            job = self.busy.pop(actor, None)
            if kind == 'arrived':
                if {p['node'],p['from']} == {'E','W'}:
                    self.channel.leave(actor,now)
                    self.emit(actor,'channel_cleared',p)
                    self.recompute_channel_release(actor,now)
                if not self.berth_room_at(actor,p['node']):
                    self.hold_for_berth(actor,p,job)
                    continue
                self.poses[actor] = p['node']
            elif kind == 'observe_completed':
                r = Report(actor,'device',now,self.card['tau_ms'],1,p['node'])
                self.mission.receive(actor,r)
                self.emit(actor,'observation_completed',{'report':asdict(r)})
            elif kind == 'load_completed':
                self.mission.finish_load(actor,p['task_id'])
            elif kind == 'unload_completed':
                cargo = self.mission.inventory[actor]
                if not self.mission.deliver(actor,self.poses[actor]):
                    raise ValueError('delivery failed')
                self.complete(actor,cargo,'delivery')
            elif kind == 'inspect_completed':
                task_id = p['task_id']
                if self.poses[actor] != self.tasks[task_id]['region']:
                    raise ValueError('inspection completed outside assigned region')
                report_task=task_id if self.tasks[task_id]['kind']=='report_delivery' else self.inspection_sources.get(task_id)
                if self.tasks[task_id]['kind']!='report_delivery':self.complete(actor,task_id,'inspection')
                if report_task:
                    if self.card.get('g2',{}).get('manual_inspection_reports'):
                        report=dict(kind='inspection_report',task_id=report_task,inspection_task_id=task_id,source_id=actor,region=self.poses[actor],sampled_at=now,
                                    report_id=self.run_id+':'+actor+':'+report_task)
                        self.inspection_reports[actor][report_task]=report
                        self.emit(actor,'inspection_report_created',dict(report))
                    else:
                        self.send(actor,self.station,{'kind':'inspection_report','task_id':task_id},'inspection_'+task_id)
                        self.report_copies[actor][task_id]={'sent_at':now,'copies':1}
            self.emit(actor,kind,p,p.get('task_id'))
        before_failures=len(self.network.failures)
        for m in self.network.advance(now,self.radio_positions()):
            self.inbox.setdefault(m.receiver,[]).append(m)
            self.emit(m.receiver,'message_arrived',{'sender':m.sender,'message_id':m.message_id,
                       'sent_at':m.sent_at,'arrived_at':m.arrived_at,
                    'transmission_delay_ms':m.delivery_delay_ms or self.network.delay,
                    'payload':asdict(m.payload) if isinstance(m.payload,Report) else m.payload},contract_id=m.contract_id)
            if self.card.get('m2') and m.receiver=='entrance' and isinstance(m.payload,dict):
                if m.payload.get('kind')=='m2_slot_query':
                    for i,r in enumerate(self.reservations):
                        self.send('entrance',m.sender,{'kind':'reservation','reservation':dict(r)},f'query_{m.message_id}_{i}')
                elif m.payload.get('kind')=='reservation_cancel':
                    slot=m.payload['slot_id'];released=self.cancel_reservation(m.sender,slot)
                    r=next((r for r in self.reservations if r.get('slot_id')==slot),None)
                    self.send('entrance',m.sender,{'kind':'reservation_cancel_ack','slot_id':slot,
                        'released':released,'reservation':dict(r) if r else None},f'cancel_ack_{m.message_id}')
                elif m.payload.get('kind')=='m2_confirm':
                    try:
                        committed=self.exchange_slots(m.sender,m.payload['quote'])
                    except (ValueError,KeyError,TypeError) as error:
                        self.emit('entrance','invalid_exchange',{'reason':str(error)},contract_id=m.contract_id)
                        self.send('entrance',m.sender,{'kind':'m2_reject','contract_id':m.contract_id,
                            'reason':'resource validation failed'},f'reject_{m.message_id}')
                        committed=False
                    if committed:
                        for party in m.payload['quote']['parties']:
                            self.send('entrance',party,{'kind':'m2_commit','contract_id':m.contract_id,
                                'quote':m.payload['quote']},f'commit_{m.message_id}_{party}')
                elif m.payload.get('kind')=='m2_commit_record':
                    try:
                        self.record_bilateral_commit(m.sender,m.payload['quote'])
                    except (ValueError,KeyError,TypeError) as error:
                        self.emit('entrance','invalid_exchange',{'reason':str(error)},contract_id=m.contract_id)
            if isinstance(m.payload,Report):
                self.mission.receive(m.receiver,m.payload)
            elif m.receiver == self.station and m.payload.get('kind') == 'inspection_report':
                task_id=m.payload.get('task_id')
                if self.card.get('g2',{}).get('manual_inspection_reports'):
                    origin=m.payload.get('source_id')
                    issued=self.inspection_reports.get(origin,{}).get(task_id)
                    forwarded=any(r.sender==origin and r.payload==m.payload and r.arrived_at<=m.queued_at for r in self.inbox.get(m.sender,[]))
                    if issued!=m.payload or (m.sender!=origin and not forwarded):
                        self.emit(self.station,'invalid_inspection_report',dict(sender=m.sender,task_id=task_id));continue
                    if task_id not in self.completed:self.complete(origin,task_id,'report_delivery',locally_observed=False)
                    receipt=dict(kind='task_result',task_id=task_id,completed_ms=self.completed[task_id],final_receiver=origin,
                                 receipt_id=self.run_id+':station_ack:'+task_id)
                    self.inspection_receipts[task_id]=receipt
                    self.send(self.station,m.sender,copy.deepcopy(receipt),'station_ack_'+task_id+'_'+m.message_id)
                    continue
                if task_id not in self.completed:
                    self.complete(m.sender,task_id,'report_delivery',locally_observed=False)
                # Re-offering a receipted report must produce a deliverable receipt, so the
                # second and later copies get a fresh message id; the first copy keeps the
                # frozen id and every registered run stays byte-identical.
                copies=self.station_receipt_copies[task_id]=self.station_receipt_copies.get(task_id,0)+1
                self.send(self.station,m.sender,{'kind':'task_result','task_id':task_id,
                    'completed_ms':self.completed[task_id]},
                    'station_ack_'+task_id if copies==1 else f'station_ack_{task_id}_r{copies}')
            elif isinstance(m.payload,dict) and m.payload.get('kind')=='task_result' and m.payload.get('task_id') in self.local_assignments.get(m.receiver,set()):
                if self.card.get('g2',{}).get('manual_inspection_reports') and self.tasks[m.payload['task_id']]['kind']=='report_delivery':
                    receipt=self.inspection_receipts.get(m.payload['task_id'])
                    forwarded=any(r.sender==self.station and r.payload==m.payload and r.arrived_at<=m.queued_at for r in self.inbox.get(m.sender,[]))
                    if receipt!=m.payload or m.payload.get('final_receiver')!=m.receiver or (m.sender!=self.station and not forwarded):
                        self.emit(m.receiver,'invalid_inspection_receipt',dict(sender=m.sender,task_id=m.payload['task_id']));continue
                self.local_results[m.receiver][m.payload['task_id']]=m.payload['completed_ms']
        for at,mid,reason in self.network.failures[before_failures:]:
            self.emit('network','message_failed',{'message_id':mid,'reason':reason,'failed_at':at})
        for r in self.reservations:
            if (r.get('slot_id') and not r['used'] and r.get('cancelled_at') is None
                and now>r['start']+self.card['reservation_grace_ms']
                and self.grant_may_expire(r,now)):
                self.release_booking(r,'reservation_expired')
        if self.card.get('target_mode'):
            observed_nodes=self.card['target_constraints'].get('observation_nodes',['E'])
            waiting={a for a in self.card['fleet'] if self.poses[a] in observed_nodes and a not in self.busy}
            self.entrance_wait_since={a:self.entrance_wait_since.get(a,now) for a in waiting}
            if now-self.last_entrance_observation>=self.card['target_constraints']['observation_period_ms']:
                self.last_entrance_observation=now
                payload=dict(kind='entrance_observation',observed_at=now,waiting=[dict(actor=a,node=self.poses[a],since_ms=self.entrance_wait_since[a]) for a in sorted(waiting) if now-self.entrance_wait_since[a]>=self.card['target_constraints']['observation_period_ms']])
                for a in ('R1','R2'):self.send('entrance',a,copy.deepcopy(payload),f'entrance_observation_{a}_{now}')
        for actor in self.card['fleet']:
            node = self.poses[actor]
            feedback_position=self.feedback_position(actor)
            if feedback_position is not None:
                x,y,z=feedback_position
            elif node is not None:
                x,y,z=self.node_position(actor,node)
            else:
                _,source,target,start,end = self.busy[actor]
                # A unit held outside a full node keeps its traversal window while the clock runs
                # past it, so the walk has to stop at the node mouth instead of extrapolating off
                # the polyline.
                fraction = 0. if end<=start else min(1.,max(0.,(now-start)/(end-start)))
                points=self.edge_points(actor,source,target)
                remaining=path_length(points)*fraction
                x,y,z=points[-1]
                from math import dist
                for a,b in zip(points,points[1:]):
                    length=dist(a,b)
                    if remaining<=length+1e-9:
                        ratio=min(1.,remaining/length)
                        x,y,z=[a[i]+ratio*(b[i]-a[i]) for i in range(3)]
                        break
                    remaining-=length
            self.trajectories.append({'t_ms':now,'actor':actor,'x':x,'y':y,'z':z if self.geometry else None,'node':node})
        counts = {}
        for actor in self.card['fleet']:
            node = self.poses[actor]
            if node is not None:
                counts[node] = counts.get(node,0)+1
        for node,count in counts.items():
            if count > self.card['berth_capacity'][node]:
                violation = {'t_ms':now,'kind':'berth_capacity','node':node,'count':count}
                self.violations.append(violation)
                self.emit('referee','constraint_violation',violation)

    def feedback_position(self,actor):
        return None

    def complete(self,actor,task_id,kind,locally_observed=True):
        if task_id in self.completed:
            raise ValueError('duplicate task completion')
        self.completed[task_id] = self.now
        if locally_observed:
            self.local_results[actor][task_id]=self.now
        self.local_assignments[actor].add(task_id)
        self.emit(actor,kind,{'deadline_ms':self.tasks[task_id]['deadline_ms'],
                             'on_time':self.now<=self.tasks[task_id]['deadline_ms']},task_id)
        if actor!='B1' and task_id in self.local_assignments['B1']:
            self.send(actor,'B1',{'kind':'task_result','task_id':task_id,'completed_ms':self.now},'task_result_'+task_id)

    def metrics(self):
        result = {'backend':'graph','constraint_violations':self.violations,'tasks':{},'teams':{}}
        for task in self.card['tasks']:
            t = self.completed.get(task['id'])
            result['tasks'][task['id']] = {'completed_ms':t,'on_time':t is not None and t<=task['deadline_ms'],
                                         'deadline_ms':task['deadline_ms'],'team':task['team']}
        for team in ('B','R'):
            tasks = [r for r in result['tasks'].values() if r['team']==team and r['deadline_ms']<=self.card['end_ms']]
            result['teams'][team] = {'on_time':sum(t['on_time'] for t in tasks),'released':len(tasks),
                                    'rate':sum(t['on_time'] for t in tasks)/len(tasks) if tasks else None}
        result['recovery'] = 'insufficient_observation_window'
        result['messages']={'queued':sum(e.kind=='message_queued' for e in self.events),
                            'delivered':sum(e.kind=='message_arrived' for e in self.events),
                            'failed':len(self.network.failures),'pending':len(self.network.queue)}
        if isinstance(self.network,ImpairedNetwork):
            offsets=sorted(self.network.offsets.values())
            result['messages'].update({'jitter_ms':self.network.jitter,'loss_rate':self.network.loss_rate,
                                       'dropped':len(self.network.dropped),
                                       'failure_reasons':self.network.failure_reasons(),
                                       'realized_delay_min_ms':(self.network.delay+offsets[0]) if offsets else self.network.delay,
                                       'realized_delay_max_ms':(self.network.delay+offsets[-1]) if offsets else self.network.delay})
        result['role_state_counts']={state:sum(e.kind=='role_state' and e.payload['state']==state for e in self.events)
                                    for state in ('PROPOSED','CONFIRMED','MOVING','READY','ACTIVE','RELEASED')}
        return result
