"""Six-entity local slot-for-observation decisions on the shared executor."""
from collections import deque
from dataclasses import asdict,replace
from time import perf_counter

from .adaptive import Adaptive,custom
from .contracts import team_utility
from .mission import report_valid
from .model import Report
from .planning import forecast,propose,with_shared_plan
from .policies import Controller,move
from .remaining import ground_travel
from .red_routes import RedRouteController
from .timing import travel_ms


def transition(peer,w,state,**details):
    peer.market_state=state
    w.emit(peer.actor,'contract_state',{'state':state,**details},contract_id=peer.cid)


def send(peer,w,target,kind,**fields):
    peer.counter+=1
    payload={'kind':kind,'contract_id':peer.cid,**fields}
    w.send(peer.actor,target,payload,f'{peer.actor}_{kind}_{peer.counter}')
    peer.last_market_send=w.now


def blue_utility(view,row):
    deadlines=[next(t['deadline_ms'] for t in view.own_tasks if t['id']==name) for name in ('blue1','blue2')]
    if not row['legal'] or any(t is None for t in row['deliveries_ms']):
        return (-1,0,0,0)
    reports=list(view.reports)
    second=Report(**view.teammate_status['B2']['report']) if view.teammate_status.get('B2',{}).get('report') else None
    new_observations=1 if row['support']=='air' else sum(
        at is not None and not any(report_valid(r,'device',at) for r in
            ([second] if i==1 and row['assignment']=='split' and second else reports))
        for i,at in enumerate(row['sampling_ms']))
    active=row['migration_ms']+4*view.public_map['service_ms']+new_observations*view.public_map['service_ms']
    return team_utility(row['deliveries_ms'],deadlines,active)


def exchanged_view(view,quote):
    owners=dict(zip(quote['slots'],reversed(quote['parties'])))
    return replace(view,reservations=tuple({**r,'actor':owners[r['slot_id']],'revision':r.get('revision',0)+1}
        if r.get('slot_id') in owners else r for r in view.reservations))


RETRY_MS=2000


def hop_budget(w):
    """Deadline budget for one negotiation hop.

    Without a published channel impairment this is the nominal message delay, so
    registered runs keep their frozen margins. When the run publishes impairment the
    budget carries worst-case jitter plus the retransmission time the loss rate makes
    likely, because a margin built on the nominal delay silently accepts quotes that
    cannot survive the link they travel on.
    """
    d=w.network.delay
    impairment=w.channel_impairment
    if not impairment:
        return d
    return d+impairment['jitter_ms']+int(round(impairment['loss_rate']*RETRY_MS))


def link_impaired(w):
    """True when the transport itself is jittered or lossy, whatever the controllers are told.

    `hop_budget` is a planning input and must use only what a controller can see, so it reads
    the published impairment. A refusal reason and the reliability machinery are not planning
    inputs: they describe or repair the physical link, so they follow the link instead of the
    awareness switch. Registered cards build a plain fixed-delay link and match neither.
    """
    return bool(getattr(w.network,'jitter',0) or getattr(w.network,'loss_rate',0.0))


class Peer:
    """Peer arbitration: the two owners close the trade in their own replicas.

    Central mode asks a fixed node to collect both confirms and grant the swap.
    Peer mode keeps the same two-phase commit, but each owner holds a SlotExchange
    replica, confirms straight to the other owner, and files the agreed quote with
    the berth ledger afterwards. The ledger and the entry check still re-read the
    physical booking state, so removing the arbiter does not remove the conflict
    guarantee; it only removes the node whose silence can stall an agreement.
    """

    def init_peer(self,arbitration):
        self.arbitration=arbitration
        self.replica=None
        self.peer_confirmed=None
        self.record_acked=False

    @property
    def counterpart(self):
        return 'R1' if self.actor=='B1' else 'B1'

    def open_replica(self,w,quote):
        """Open this owner's two-phase-commit replica on the physical booking state.

        The replica only records which owners have confirmed; who holds which berth is
        read from the same rows `exchange_gate` certifies, not from the actor's message
        view. The view is assembled from reservation broadcasts, so a lost broadcast
        leaves it missing or stale, and the replica's party check then refuses a trade
        the physical gate just approved -- the ledger would go on recording the swap
        while the other owner expired, which is the divergence the loss sweep measured.
        Duplicating the gate's ownership check on a channel-fragile copy of the truth
        added no safety, only a second way to disagree.
        """
        from .contracts import SlotExchange
        owners=dict(w.slot_owners())
        if w.bilateral_recorded(quote):
            owners.update(dict(zip(quote['slots'],quote['parties'])))
        return SlotExchange(owners)

    def commit_by_ms(self,w):
        """When an owner may conclude that the ledger never told it about a swap it recorded.

        `accept_by_ms` bounds the *acceptance*, not the commit: the ledger only fans the commit
        out once it has collected both confirms, so the copy departs after the quote's own
        deadline, and its retransmission departs one retry cycle after that. An owner that stops
        listening before the retransmission can land expires while the berth ledger keeps the
        booking swapped -- the two views then disagree about who owns which berth, which is what
        the divergent runs in the channel sweep showed. A link that cannot lose a copy delivers
        the first commit inside one hop budget, so the shipped margin stays exactly as frozen.
        """
        return self.quote['accept_by_ms'] + hop_budget(w) + (RETRY_MS if link_impaired(w) else 0)

    def confirm_to(self,w,quote,by):
        """Apply one evidenced owner confirm to this replica; True once both sides are in."""
        if self.replica is None:
            self.replica=self.open_replica(w,quote)
        feasible,reason=w.exchange_gate(quote)
        if not feasible and reason=='wrong_parties' and w.bilateral_recorded(quote):
            feasible,reason=True,''
        if not feasible:
            if reason=='channel_occupied':
                w.emit(self.actor,'slot_exchange_deferred',{'contract_id':quote['contract_id'],
                    'reason':'channel physically occupied','by':by},contract_id=quote['contract_id'])
            return False
        try:
            committed=self.replica.confirm(by,quote,w.now)
        except ValueError as error:
            w.emit(self.actor,'invalid_exchange',{'reason':str(error)},contract_id=quote['contract_id'])
            return False
        if committed and not self.record_acked:
            send(self,w,'entrance','m2_commit_record',quote=quote)
        return committed

    def own_confirm(self,w,quote):
        send(self,w,self.counterpart,'m2_bilateral',quote=quote)
        return self.confirm_to(w,quote,self.actor)

    def close(self,w,quote):
        """Close from this side: own confirm, then the peer confirm already carried by a received message."""
        return self.confirm_to(w,quote,self.actor) or (
            self.peer_confirmed is not None and self.confirm_to(w,quote,self.peer_confirmed))

    def ledger_committed(self,w):
        """True when the berth ledger already holds exactly the quote this owner accepted.

        Only an owner whose replica committed files that record, and a replica commits only on
        evidence of both confirms, so the record is proof that the peer received our confirm even
        when our copy of the peer's confirm never landed. The filing owner then activates; the
        laggard used to sit in ACCEPTED until `commit_by_ms` and expire while the ledger kept the
        bookings swapped, which is the disagreement the loss sweep counted as divergence. Honouring
        the record is the completion half of the two-phase commit and still adds no arbiter: the
        ledger cannot veto or choose, it only remembers what an owner filed.
        """
        return (self.arbitration=='peer' and self.quote is not None
                and w.bilateral_recorded(self.quote))


class BlueMarket(Adaptive,Peer):
    def __init__(self,actor,commands,policy,arbitration='central'):
        super().__init__(actor,commands,policy)
        self.init_peer(arbitration)
        self.market_state='IDLE';self.cid=None;self.request=None;self.quote=None
        self.last_market_send=-RETRY_MS;self.last_slot_query=-RETRY_MS;self.service_choice=None;self.receipt_acked=False

    def before_actions(self,w):
        if self.market_state in ('REQUESTED','ACCEPTED','ACTIVE','FULFILLED'):
            if self.market_state=='REQUESTED' and w.now-self.last_market_send>=RETRY_MS:
                send(self,w,'R1','m2_request',request=self.request)
            elif self.market_state=='ACCEPTED' and self.ledger_committed(w):
                transition(self,w,'ACTIVE',adopted_from='ledger record')
            elif self.market_state=='ACCEPTED' and w.now-self.last_market_send>=RETRY_MS:
                if self.arbitration=='peer':
                    if self.own_confirm(w,self.quote):
                        transition(self,w,'ACTIVE')
                else:
                    send(self,w,'entrance','m2_confirm',quote=self.quote)
            elif self.market_state=='ACTIVE' and self.arbitration=='peer' and not self.record_acked and w.now-self.last_market_send>=RETRY_MS:
                send(self,w,'entrance','m2_commit_record',quote=self.quote)
            elif self.market_state=='FULFILLED' and not self.receipt_acked and w.now-self.last_market_send>=RETRY_MS:
                send(self,w,'R1','m2_fulfilled',sampled_at=self.accepted_report.sampled_at,received_at=self.accepted_at)
        elif (self.market_state in ('REJECTED','EXPIRED','FAILED','UNAVAILABLE','DISABLED')
              and 'B2' not in w.view(self.actor).teammate_status
              and w.now-self.last_status_request>=RETRY_MS):
            # The self-help plan cannot be chosen without a transport status, and the single
            # request sent when the market closed had no retry path of its own: a lost reply
            # used to leave the coordinator waiting for a message that would never come back.
            self.last_status_request=w.now
            self.send(w,'B2',{'kind':'status_request','include_report':True},'status_request')
            w.emit(self.actor,'market_fallback_status_requested',{'state':self.market_state})
        super().before_actions(w)

    def on_message(self,w,m):
        p=m.payload
        if isinstance(p,Report) and m.sender=='R5' and m.contract_id==self.cid and self.market_state=='ACTIVE':
            q=self.quote
            if (report_valid(p,self.request['subject_id'],w.now) and p.quality>=self.request['minimum_quality']
                and w.now-p.sampled_at<=self.request['maximum_age_ms'] and w.now<=self.request['report_by_ms']):
                self.accepted_report=p;self.accepted_at=w.now
                transition(self,w,'FULFILLED',sampled_at=p.sampled_at,received_at=w.now)
                send(self,w,'R1','m2_fulfilled',sampled_at=p.sampled_at,received_at=w.now)
            else:
                transition(self,w,'FAILED',reason='actual service report violates requested terms')
        if isinstance(p,dict) and p.get('contract_id')==self.cid:
            kind=p.get('kind')
            if kind=='m2_offer' and m.sender=='R1' and self.market_state=='REQUESTED':
                q=p['quote'];self.quote=q;d=hop_budget(w)
                valid=(q['subject_id']==self.request['subject_id'] and q['minimum_quality']>=self.request['minimum_quality']
                    and q['maximum_age_ms']<=self.request['maximum_age_ms'] and q['report_by_ms']<=self.request['report_by_ms']
                    and q['slots']==self.request['slots'] and q['parties']==['B1','R1'])
                if not valid or w.now+2*d>q['accept_by_ms']:
                    transition(self,w,'EXPIRED' if valid else 'REJECTED',reason='quote arrived too late' if valid else 'quote weakens requested terms')
                    send(self,w,'R1','m2_reject',reason='late or invalid quote')
                    return
                start=perf_counter();view=w.view('B1');decision=propose(view,self.policy,61)
                baseline=next(c for c in decision.candidates if c['id']==decision.chosen)
                released=exchanged_view(view,q);release_only=forecast(with_shared_plan(released),baseline)
                future=replace(released,now_ms=q['report_received_ms'],reports=(
                    Report('R5','device',q['report_sample_ms'],view.public_map['tau_ms'],1,'H_R'),))
                future=with_shared_plan(future)
                service=[]
                for route in ('channel','bypass'):
                    row=forecast(future,{'id':'external_'+route,'z':baseline['z'],'assignment':baseline['assignment'],
                        'support':baseline['support'],'route':route,'information':baseline['information']})
                    service.append(row)
                best=max(service,key=lambda c:blue_utility(future,c))
                choices=[{'id':'independent','utility':blue_utility(view,baseline),'prediction':baseline},
                    {'id':'release_without_service','utility':blue_utility(released,release_only),'prediction':release_only},
                    {'id':'exchange','utility':blue_utility(future,best),'prediction':best}]
                elapsed=(perf_counter()-start)*1000
                w.emit('B1','contract_decision',{'candidates':choices,'elapsed_ms':elapsed,
                    'distinct_evaluated':len({c['id'] for c in decision.candidates})+3,
                    'input':asdict(view),'scope':'affected blue deliveries and active service work; unchanged tasks cancel'},contract_id=self.cid)
                if elapsed>100 or choices[2]['utility']<=max(c['utility'] for c in choices[:2]):
                    transition(self,w,'REJECTED',reason='no local utility improvement over lawful independent choices')
                    send(self,w,'R1','m2_reject',reason='independent arrangement is no worse')
                    return
                self.service_choice=best
                transition(self,w,'ACCEPTED')
                if self.arbitration=='peer':
                    self.own_confirm(w,q)
                else:
                    send(self,w,'R1','m2_accept',quote=q)
                    send(self,w,'entrance','m2_confirm',quote=q)
                return
            if kind=='m2_bilateral' and m.sender=='R1' and self.market_state=='ACCEPTED' and p['quote']==self.quote:
                self.peer_confirmed=m.sender
                if self.close(w,p['quote']):
                    transition(self,w,'ACTIVE')
                return
            if kind=='m2_record_ack' and m.sender=='entrance' and p.get('contract_id')==self.cid:
                self.record_acked=True;return
            if kind=='m2_commit' and m.sender=='entrance' and self.market_state=='ACCEPTED' and p['quote']==self.quote:
                transition(self,w,'ACTIVE')
                return
            if kind=='m2_reject' and m.sender in ('R1','entrance') and self.market_state in ('REQUESTED','ACCEPTED'):
                transition(self,w,'REJECTED',reason=p['reason']);return
            if kind=='m2_receipt_ack' and m.sender=='R1':
                self.receipt_acked=True;return
        super().on_message(w,m)

    def command(self,w,arg):
        if arg['kind']=='bootstrap' and self.market_state=='IDLE':
            view=w.view(self.actor)
            tickets={r['actor']:r for r in view.reservations if r.get('exchangeable') and not r['used'] and r.get('cancelled_at') is None}
            if not {'B1','R1'}<=tickets.keys():
                unavailable=any(r.get('exchangeable') and r['actor']=='R1' and
                                (r.get('cancelled_at') is not None or r['used']) for r in view.reservations)
                if unavailable:
                    self.market_state='UNAVAILABLE'
                    w.emit('B1','market_unavailable',{'state':'UNAVAILABLE','reason':'no unused transferable red booking in received resource state'})
                    self.send(w,'B2',{'kind':'status_request','include_report':True},'status_request')
                    return super().command(w,arg)
                if w.now-self.last_slot_query>=2000:
                    self.last_slot_query=w.now
                    send(self,w,'entrance','m2_slot_query')
                return None
            self.send(w,'B2',{'kind':'status_request','include_report':True},'status_request')
            if not w.card['m2']['service_enabled']:
                transition(self,w,'DISABLED')
                return super().command(w,arg)
            self.cid=w.run_id+'_exchange'
            s=view.public_map['service_ms']
            le=travel_ms(view.public_map,'L','E')
            self.request={'subject_id':'device','minimum_quality':1,'maximum_age_ms':view.public_map['tau_ms'],
                'report_by_ms':tickets['R1']['start']+2000-s-le,
                'slots':[tickets['B1']['slot_id'],tickets['R1']['slot_id']], 'parties':['B1','R1'],
                'blue_slot':tickets['B1'],'red_slot':tickets['R1'],
                # One hop for the offer to come back, one hop for the accept and ledger commit
                # to land, both before the berth slot starts. When the link budget exceeds the
                # time left, the branch below closes the market with that arithmetic instead of
                # sending a request that can only expire on arrival.
                'request_until_ms':tickets['B1']['start']-2*hop_budget(w)}
            left=self.request['request_until_ms']-w.now
            if left<=0:
                # The berth slot closes before a budgeted request+offer round trip could even
                # land, so there is nothing to negotiate. Say it with the arithmetic now: sending
                # the request anyway expires on arrival and reads, in the log, like a lost message.
                w.emit(self.actor,'market_window_unviable',{'now_ms':w.now,'hop_budget_ms':hop_budget(w),
                    'blue_slot_start_ms':tickets['B1']['start'],'request_until_ms':self.request['request_until_ms'],
                    'window_ms':left})
                transition(self,w,'EXPIRED',reason=(
                    f'link budget leaves no time to negotiate: round trip {2*hop_budget(w)} ms '
                    f'vs {left} ms before the request deadline'))
                return [custom('bootstrap')]
            transition(self,w,'REQUESTED');send(self,w,'R1','m2_request',request=self.request)
            return [custom('m2_wait')]
        if arg['kind']=='m2_wait':
            if self.market_state=='REQUESTED' and w.now>self.request['request_until_ms']:
                transition(self,w,'EXPIRED',reason='no timely offer received')
            if self.market_state=='ACCEPTED' and w.now>self.commit_by_ms(w):
                transition(self,w,'EXPIRED',reason='no resource commit received')
            if self.market_state=='ACTIVE' and w.now>self.request['report_by_ms']:
                transition(self,w,'FAILED',reason='actual report not delivered by contract deadline')
            if self.market_state=='FULFILLED':
                view=w.view('B1');self.selected=forecast(with_shared_plan(view),self.service_choice)
                w.emit('B1','decision_selected',{'id':self.selected['id'],'policy':self.policy,'prediction':self.selected})
                return [custom('initial_prepare')]
            if self.market_state in ('REJECTED','EXPIRED','FAILED'):
                return [custom('bootstrap')]
            return None
        return super().command(w,arg)


class RedMarket(RedRouteController,Peer):
    def __init__(self,commands,autonomous=False,allow_rebook=True,arbitration='central'):
        super().__init__('R1',commands,autonomous,allow_rebook)
        self.init_peer(arbitration)
        self.market_state='IDLE';self.cid=None;self.quote=None;self.air=None;self.last_market_send=-RETRY_MS
        self.pending_request=None

    def on_message(self,w,m):
        if self.route_message(w,m):
            return
        p=m.payload
        if not isinstance(p,dict):
            return
        if p.get('kind')=='m2_air_status' and m.sender=='R5':
            self.air=p
            if self.market_state=='WAITING_PROVIDER' and 0<=w.now-p['observed_at']<=w.card['m2']['status_max_age_ms']:
                pending=self.pending_request;self.market_state='IDLE';self.pending_request=None
                self.on_message(w,pending)
            return
        if p.get('kind')=='m2_request' and m.sender=='B1' and self.market_state=='IDLE':
            self.cid=p['contract_id'];request=p['request'];view=w.view('R1');status=self.air
            transition(self,w,'REQUESTED')
            if self.autonomous and (view.node!='E' or view.inventory!='red1' or self.cancel_pending):
                transition(self,w,'REJECTED',reason='own transport has departed or resource release is unresolved')
                send(self,w,'B1','m2_reject',reason='own transport or resource release prevents exchange');return
            if w.now>request['request_until_ms']:
                reason='provider availability unresolved before request deadline'
                if link_impaired(w):
                    # Registered cards keep the frozen wording, but here the clock is what ran
                    # out, not the provider: R1 has not looked at availability at all yet. The
                    # two causes need different fixes, so an impaired run names the real one.
                    reason=f'{reason}: request landed after its own window closed'
                transition(self,w,'EXPIRED',reason=reason)
                send(self,w,'B1','m2_reject',reason=reason);return
            if not status or not 0<=w.now-status['observed_at']<=w.card['m2']['status_max_age_ms']:
                self.pending_request=m
                transition(self,w,'WAITING_PROVIDER',reason='querying actual provider availability')
                send(self,w,'R5','m2_status_request');return
            if status['node']!='H_R' or request['minimum_quality']>1:
                transition(self,w,'REJECTED',reason='no fresh delivered provider availability')
                send(self,w,'B1','m2_reject',reason='no fresh delivered provider availability');return
            # The quote is a promise about when the report reaches B1, so it has to be built on
            # the same budget the requester checks the promise against. A provider that prices
            # the link at its nominal delay sells a report the real link will deliver late.
            d=hop_budget(w);s=view.public_map['service_ms']
            commit=w.now+3*d;receipt=commit+d;sample=receipt+d+s;report_at=sample+d
            early=request['blue_slot'];late=request['red_slot']
            channel=travel_ms(view.public_map,'E','W')
            exit_time=travel_ms(view.public_map,'W','D')
            onward=channel+exit_time+s
            own_task=next(t for t in view.own_tasks if t['id']=='red1');red_deadline=own_task['deadline_ms'];release=own_task.get('release_ms',0)
            independent=ground_travel(view,'channel',view.node,'D',max(w.now,release),'R1')[0]+s
            trade=ground_travel(exchanged_view(view,request),'channel',view.node,'D',max(receipt,release),'R1')[0]+s
            provider_finish=sample+d+status['return_ms']
            deadlines=[red_deadline,status['own_return_deadline_ms']]
            base_active=onward+status['base_active_ms']
            choices=[{'id':'independent','utility':team_utility([independent,status['own_return_finish_ms']],deadlines,base_active)},
                     {'id':'exchange','utility':team_utility([trade,provider_finish],deadlines,base_active+s)}]
            w.emit('R1','contract_decision',{'candidates':choices,'provider_status':status,
                'forecast':{'red_baseline_ms':independent,'red_exchange_ms':trade,'provider_finish_ms':provider_finish},
                'input':asdict(view),'scope':'affected red delivery and provider return; completed tasks cancel'},contract_id=self.cid)
            blockers=[('provider cannot finish before its own return deadline',
                        provider_finish>status['own_return_deadline_ms']),
                      ('provider leaves before the report can be sampled',
                        sample+d>status['available_until']),
                      ('report cannot reach the requester by the contract deadline',
                        report_at>request['report_by_ms']),
                      ('exchange is not better than the independent plan',
                        choices[1]['utility']<=choices[0]['utility'])]
            blocked=next((name for name,flag in blockers if flag),None)
            if blocked:
                reason='own hard return commitment or local utility prevents service'
                if link_impaired(w):
                    # Registered cards keep their frozen wording; an impaired run records
                    # which clause actually failed, so a decline is explained, not guessed.
                    reason=f'{reason}: {blocked}'
                transition(self,w,'REJECTED',reason=reason)
                send(self,w,'B1','m2_reject',reason=reason);return
            le=travel_ms(view.public_map,'L','E')
            blue_contact=max(report_at+s+le,late['start'])+onward-s
            self.quote={**request,'contract_id':self.cid,'accept_by_ms':early['start']-d,
                'report_sample_ms':sample,'report_received_ms':report_at,'red_delivery_ms':trade,
                'provider_finish_ms':provider_finish,'fulfillment_ack_by_ms':max(trade,blue_contact)+2*d,
                'receipt_contact_node':'D'}
            transition(self,w,'OFFERED');send(self,w,'B1','m2_offer',quote=self.quote)
        elif p.get('contract_id')==self.cid:
            kind=p.get('kind')
            accepted=(kind=='m2_bilateral' and self.arbitration=='peer' or kind=='m2_accept') and m.sender=='B1'
            if accepted and self.market_state=='OFFERED' and p['quote']==self.quote:
                if w.now>self.quote['accept_by_ms']:
                    transition(self,w,'EXPIRED');return
                transition(self,w,'ACCEPTED')
                if self.arbitration=='peer':
                    self.peer_confirmed=m.sender
                    send(self,w,'B1','m2_bilateral',quote=self.quote)
                    if self.close(w,p['quote']):
                        self.activate(w)
                else:
                    send(self,w,'entrance','m2_confirm',quote=self.quote)
            elif kind=='m2_bilateral' and m.sender=='B1' and self.arbitration=='peer' and self.market_state=='ACCEPTED' and p['quote']==self.quote:
                if w.now>self.quote['accept_by_ms']:
                    transition(self,w,'EXPIRED')
                else:
                    self.peer_confirmed=m.sender
                    if self.close(w,p['quote']):
                        self.activate(w)
            elif kind=='m2_bilateral' and m.sender=='B1' and self.arbitration=='peer' and self.market_state in ('ACTIVE','FULFILLED') and p['quote']==self.quote:
                send(self,w,'B1','m2_bilateral',quote=self.quote)
            elif kind=='m2_record_ack' and m.sender=='entrance':
                self.record_acked=True
            elif kind=='m2_commit' and m.sender=='entrance' and self.market_state=='ACCEPTED' and p['quote']==self.quote:
                self.activate(w)
            elif kind=='m2_service_failed' and m.sender=='R5' and self.market_state=='ACTIVE':
                # The provider says out loud that it cannot serve this contract, and the contract
                # used to ignore the sentence: R1 stayed ACTIVE until the receipt deadline, so the
                # log blamed a missing receipt for a service that was never going to happen.
                transition(self,w,'FAILED',reason=f'provider declined the service: {p.get("reason","")}')
            elif kind=='m2_fulfilled' and m.sender=='B1' and self.market_state in ('ACTIVE','FULFILLED'):
                if (w.now>self.quote['fulfillment_ack_by_ms'] or p['received_at']>self.quote['report_by_ms']
                    or not 0<=p['received_at']-p['sampled_at']<=self.quote['maximum_age_ms']):
                    if self.market_state=='ACTIVE':
                        transition(self,w,'FAILED',reason='invalid or late receiver acceptance receipt')
                    return
                if self.market_state=='ACTIVE':
                    transition(self,w,'FULFILLED',actual_receiver_sampled_at=p['sampled_at'],actual_receiver_time=p['received_at'])
                send(self,w,'B1','m2_receipt_ack')
            elif kind=='m2_reject' and m.sender=='B1' and self.market_state in ('OFFERED','ACCEPTED'):
                transition(self,w,'REJECTED',reason=p['reason'])

    def activate(self,w,adopted=False):
        transition(self,w,'ACTIVE',**({'adopted_from':'ledger record'} if adopted else {}))
        send(self,w,'R5','m2_service',quote=self.quote)
        self.commands=deque(move('W','D')+[('unload','red1')])

    def before_actions(self,w):
        if self.market_state=='WAITING_PROVIDER':
            if w.now>self.pending_request.payload['request']['request_until_ms']:
                transition(self,w,'EXPIRED',reason='provider availability unresolved before request deadline')
                send(self,w,'B1','m2_reject',reason='provider availability unresolved before request deadline')
                self.pending_request=None
            elif w.now-self.last_market_send>=RETRY_MS:
                send(self,w,'R5','m2_status_request')
        if self.market_state=='ACCEPTED' and self.ledger_committed(w):
            self.activate(w,adopted=True)
        if self.quote and self.market_state in ('OFFERED','ACCEPTED'):
            if w.now>(self.commit_by_ms(w) if self.market_state=='ACCEPTED' else self.quote['accept_by_ms']):
                transition(self,w,'EXPIRED',reason='acceptance or commit was not received in time')
            elif w.now-self.last_market_send>=RETRY_MS:
                if self.market_state=='OFFERED':
                    send(self,w,'B1','m2_offer',quote=self.quote)
                elif self.arbitration=='peer':
                    send(self,w,'B1','m2_bilateral',quote=self.quote)
                    if self.close(w,self.quote):
                        self.activate(w)
                else:
                    send(self,w,'entrance','m2_confirm',quote=self.quote)
        if self.market_state=='ACTIVE' and self.arbitration=='peer' and not self.record_acked and w.now-self.last_market_send>=RETRY_MS:
            send(self,w,'entrance','m2_commit_record',quote=self.quote)
        if self.quote and self.market_state=='ACTIVE' and w.now>self.quote['fulfillment_ack_by_ms']:
            transition(self,w,'FAILED',reason='receiver acceptance receipt not delivered')
        self.route_before_actions(w,locked=self.market_state in ('OFFERED','ACCEPTED','ACTIVE','FULFILLED'))


class Provider(Adaptive):
    def __init__(self,commands,policy):
        super().__init__('R5',commands,policy);self.cid=None;self.market_state='IDLE';self.served=set()
        self.cross_team_enabled=True;self.last_status_send=-RETRY_MS

    def home(self,node):
        return (move('K_R','F_R') if node=='H_R' else move('F_R') if node=='K_R' else [])+[('inspect','red_return'),('hold',None)]

    def return_flight(self,w,view):
        """Duration and latest lawful departure of R5's own home flight, from local state only."""
        m=view.public_map;s=m['service_ms']
        flight=travel_ms(m,'H_R','K_R')+travel_ms(m,'K_R','F_R');return_ms=flight+s
        deadline=next(t['deadline_ms'] for t in view.own_tasks if t['id']=='red_return')
        depart=max(w.now,min(w.card['m2']['red_radio_window_end_ms'],deadline-return_ms))
        return flight,s,return_ms,deadline,depart

    def availability(self,w):
        view=w.view('R5');tasks={t['id']:t for t in view.own_tasks}
        if (view.node!='H_R' or 'R5' in w.busy or
            any(tasks[name]['completed_ms'] is None for name in ('red_inspect','red_patrol'))):return None
        flight,s,return_ms,deadline,depart=self.return_flight(w,view)
        return {'kind':'m2_air_status','node':view.node,'observed_at':w.now,'available_until':depart,
            'return_ms':return_ms,'base_active_ms':2*flight+3*s,
            'own_return_finish_ms':depart+return_ms,'own_return_deadline_ms':deadline}

    def send_availability(self,w,payload):
        self.counter+=1;w.send('R5','R1',payload,f'R5_private_status_{self.counter}')
        self.last_status_send=w.now

    def before_actions(self,w):
        # Availability is the only fast path to a quote. With one unacknowledged push, a single
        # eaten copy drops the trade onto the live-query fallback, which needs R1->R5->R1->B1
        # inside a window that budgets only request+offer -- so the trade is not merely late,
        # it becomes unschedulable. Re-push while the answer still describes this aircraft;
        # availability() turns None the moment that stops being true, and registered cards
        # never enter here, so their frozen single push stays exactly one message.
        if link_impaired(w) and w.now-self.last_status_send>=RETRY_MS:
            payload=self.availability(w)
            if payload is not None:self.send_availability(w,payload)
        super().before_actions(w)

    def command(self,w,arg):
        if arg['kind']=='provider_status':
            payload=self.availability(w)
            if payload is not None:self.send_availability(w,payload)
            # The market offer needs receipted reports; the aircraft's own return does not.
            # Coupling them handed the mandatory flight to a receipt the link may never deliver.
            view=w.view('R5')
            return [('at',self.return_flight(w,view)[4])]+self.home(view.node)
        if arg['kind']=='provider_report':
            report=max(w.view('R5').reports,key=lambda r:r.sampled_at)
            self.counter+=1;w.send('R5','B1',report,f'R5_contract_report_{self.counter}',contract_id=self.cid)
            w.emit('R5','service_state',{'state':'REPORT_SENT','sampled_at':report.sampled_at},contract_id=self.cid)
            return []
        return super().command(w,arg)

    def on_message(self,w,m):
        p=m.payload
        if not self.cross_team_enabled and isinstance(p,dict) and p.get('kind','').startswith('m2_'):return
        if isinstance(p,dict) and p.get('kind')=='m2_status_request' and m.sender=='R1':
            payload=self.availability(w)
            if payload is not None:self.send_availability(w,payload)
            return
        if isinstance(p,dict) and p.get('kind')=='m2_service' and m.sender=='R1':
            cid=p['contract_id']
            if cid in self.served:
                return
            q=p['quote'];view=w.view('R5');mapp=view.public_map
            deadline=next(t['deadline_ms'] for t in view.own_tasks if t['id']=='red_return')
            flight=travel_ms(mapp,'H_R','K_R')+travel_ms(mapp,'K_R','F_R')
            if (view.node!='H_R' or 'R5' in w.busy or w.now+2*mapp['service_ms']+w.network.delay+flight>deadline
                or w.now+mapp['service_ms']+w.network.delay>q['report_by_ms']):
                self.cid=cid
                w.emit('R5','service_state',{'state':'REJECTED','reason':'actual service would break own return or report deadline'},contract_id=cid)
                send(self,w,'R1','m2_service_failed',reason='provider actual state cannot fulfill');return
            self.cid=cid;self.served.add(cid)
            w.emit('R5','service_state',{'state':'ACTIVE'},contract_id=self.cid)
            self.commands=deque([('observe',None),custom('provider_report'),custom('hold_delay')]+list(self.commands))
            return
        super().on_message(w,m)


def m2_controllers(card,policy):
    if policy not in ('P0','P1','P2','P3','P4','P2_equal'):
        raise ValueError('M2 requires a local P0/P1/P2/P3/P4/P2_equal policy')
    from .adaptive import adaptive_controllers
    cs=adaptive_controllers(card,policy)
    arbitration=card['m2'].get('arbitration','central')
    cs['B1']=BlueMarket('B1',list(cs['B1'].commands),policy,arbitration)
    mode=card['m2'].get('red_route_policy','fixed')
    cs['R1']=RedMarket([('at',card['red_release_ms'][0])]+move('W','D')+[('unload','red1')],
                       autonomous=mode!='fixed',allow_rebook=mode!='route_only',arbitration=arbitration)
    if mode!='fixed':
        cs['R2']=RedRouteController('R2',list(cs['R2'].commands),autonomous=True,allow_rebook=mode!='route_only')
    cs['R5']=Provider([('inspect','red_inspect'),custom('hold_delay',hops=2)]+move('K_R','H_R')+
                      [('inspect','red_patrol'),custom('hold_delay',hops=2),custom('provider_status')],policy)
    return cs
