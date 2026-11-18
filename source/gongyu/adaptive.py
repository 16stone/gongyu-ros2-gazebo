"""Local execution of finite decisions, with delayed prepare/commit and real handoffs."""
from collections import deque
from dataclasses import asdict,replace

from .model import Report
from .mission import report_valid
from .geometry import ground_observation
from .planning import diagnose,propose,with_shared_plan,forecast,candidate_rank
from .policies import Controller,move
from .timing import travel_ms
from .remaining import ground_travel,channel_rebooking

REPORT_RETRY_MS = 2000


def custom(kind,**kwargs):
    return ('custom',{'kind':kind,**kwargs})


def path(source,target,route='channel'):
    if source==target:
        return []
    table={('L','D'):['D'] if route=='bypass' else ['E','W','D'],
           ('D','L'):['L'] if route=='bypass' else ['W','E','L'],
           ('L','O'):['J','O'],('O','L'):['J','L'],('O','J'):['J'],
           ('J','O'):['O'],('J','L'):['L'],('L','J'):['J'],
           ('K','H'):['H'],('H','F'):['K','F'],('K','F'):['F'],('F','K'):['K']}
    if (source,target) in table:
        return move(*table[source,target])
    if source=='D' and target in ('O','J'):
        return path('D','L',route)+path('L',target,route)
    raise ValueError(f'No implemented legal route {source}->{target}')


class Adaptive(Controller):
    def __init__(self,actor,commands,policy):
        super().__init__(actor,commands)
        self.policy = policy
        self.selected = None
        self.proposal = None
        self.accepted = set()
        self.required = set()
        self.peer_ready = set()
        self.pending = None
        self.committed = False
        self.commit_sent_at = None
        self.fresh_consumed = set()
        self.proposal_deadline = None
        self.service_deadline = None
        self.terminal_proposals = set()
        self.ready_outbox=None
        self.last_monitor=-1000000
        self.last_inbox_count=0
        self.last_replan=-1000000
        self.plan_revision=0
        self.collection_until=None
        self.release_requested=None
        self.releasing=None
        self.release_denied_for=set()
        self.release_receipts={}
        self.peer_released={}
        self.protocol_outbox={}
        self.commit_acked=set()
        self.last_status_request=-2000
        self.last_report_request=-1000000
        self.channel_cancel=None
        self.channel_cancel_denied=set()

    def before_actions(self,w):
        if w.card.get('m2') and w.card.get('online_replanning') and self.actor in ('B1','B2') and self.commands and not self.channel_cancel:
            view=w.view(self.actor);kind,target=self.commands[0]
            if kind=='move' and {view.node,target}=={'E','W'}:
                earlier=channel_rebooking(view,view.node,target,w.now,self.actor)
                if earlier and earlier['slot_id'] not in self.channel_cancel_denied:
                    self.channel_cancel={**earlier,'last_sent':w.now}
                    self.send(w,'entrance',{'kind':'reservation_cancel','slot_id':earlier['slot_id']},'channel_cancel')
                    w.emit(self.actor,'channel_rebook_requested',earlier)
                    self.commands.appendleft(custom('wait_channel_cancel'))
        if self.release_requested:
            self.release_peer(w)
        if w.card.get('online_replanning') and self.actor=='B2' and self.pending and all(kind=='hold' for kind,_ in self.commands):
            cargo=next((arg for kind,arg in self.pending.get('residual_workflow',[]) if kind=='unload'),'blue2')
            if any(t['id']==cargo and t['completed_ms'] is not None for t in w.view(self.actor).own_tasks):
                self.phase(w,'RELEASED','transport completed with local receipt')
                self.terminal_proposals.add(self.proposal);self.pending=None;self.committed=False;self.ready_outbox=None
                self.commands=deque([custom('status'),('hold',None)])
        if self.releasing:
            return
        if self.actor in ('B1','B2') and self.awaiting_support_report(w):
            until=self.support_until(w)
            if self.support_overdue(w):
                self.support_fallback(w,w.view(self.actor))
            elif until is not None and w.now>=until-w.card['tau_ms'] and (
                    w.now-self.last_report_request>=REPORT_RETRY_MS):
                self.last_report_request=w.now
                self.send(w,'B3',{'kind':'status_request','include_report':True},'report_request')
                w.emit(self.actor,'support_report_rerequested',{'proposal_id':self.proposal,
                                                              'service_until':until})
            return
        if self.actor!='B1' or not w.card.get('online_replanning') or self.selected is None:
            return
        view=w.view(self.actor)
        remaining=[t for t in view.own_tasks if t['id'] in ('blue1','blue2') and t['completed_ms'] is None]
        if not remaining or view.node not in ('L','D','J','O') or w.now-self.last_replan<500:
            return
        if self.required and self.proposal not in self.terminal_proposals and (
            not self.committed or 'B2' in self.required or ('B3' in self.required and not self.fresh_consumed)):
            return  # An unresolved prepare, delivery or observation is still a live commitment.
        if self.collection_until is not None and w.now<self.collection_until:
            return
        if self.selected['information']=='wait' and w.now-self.last_status_request>=2000:
            self.last_status_request=w.now
            for peer in ('B2','B3'):
                self.send(w,peer,{'kind':'status_request'},'status_request')
        self.replan_remaining(w,view)

    def awaiting_support_report(self,w):
        """True while this unit is blocked on an air report that never landed."""
        if not w.card.get('online_replanning') or self.releasing or self.fresh_consumed:
            return False
        live = (self.pending or self.selected) or {}
        if live.get('support') != 'air':
            return False
        # An empty queue is also a wait: the unit has run out of lawful work and would
        # otherwise idle until a peer physically carries the bad news.
        return not self.commands or self.commands[0] == ('await_fresh',None)

    def support_until(self,w):
        if self.pending and self.pending.get('service_until') is not None:
            return self.pending['service_until']
        return self.service_deadline

    def support_overdue(self,w):
        """The pull has had its round trips; waiting longer cannot yield a valid report."""
        until=self.support_until(w)
        return until is not None and w.now>=until+REPORT_RETRY_MS+2*w.network.delay

    def support_fallback(self,w,view):
        """Replace a hopeless wait with a lawful local observation, or say so out loud."""
        a=self.actor
        self.ready_outbox=None
        route=ground_observation(view.public_map,view.node,view.node) if view.node=='L' else None
        if route is not None:
            w.emit(a,'support_report_self_collected',{'proposal_id':self.proposal,
                    'node':view.node,'service_until':self.support_until(w)})
            # Only the waiting commands are exchanged; a queued load still follows the
            # observation, so abandoning a peer report never abandons the delivery.
            waiting = (('await_fresh',None), custom('fresh'))
            while self.commands and self.commands[0] in waiting:
                self.commands.popleft()
            recovery=move(*route['to_observation'])+[('observe',None)]+move(*route['from_observation'])
            self.commands.extendleft(reversed(recovery+[custom('fresh')]))
            return
        w.emit(a,'support_report_unreachable',{'proposal_id':self.proposal,'node':view.node,
                'service_until':self.support_until(w)})
        if a=='B1':
            self.abort(w,'support report never arrived')
            return
        self.commands=deque([custom('travel',target='D'),
                ('send',('B1',{'kind':'reject','proposal_id':self.proposal,
                    'reason':'support report never arrived'},'carried_timeout_'+self.proposal)),
                custom('hold_delay'),custom('travel',target='J'),('hold',None)])

    def replan_remaining(self,w,view,initial=False):
        self.last_replan=w.now
        locked=set()
        if self.proposal not in self.terminal_proposals:
            locked=set(self.required)
        view=replace(view,public_map={**view.public_map,'unresolved_commitments':sorted(locked)})
        decision=propose(view,self.policy)
        best=next(c for c in decision.candidates if c['id']==decision.chosen)
        current=forecast(with_shared_plan(view),self.selected) if self.selected else None
        timed_out=self.collection_until is not None and w.now>=self.collection_until
        unfinished=[t for t in view.own_tasks if t['id'] in ('blue1','blue2') and t['completed_ms'] is None]
        apply=initial or (len(unfinished)==1 and not self.selected.get('remaining_tasks')) or timed_out or (
            best['legal'] and candidate_rank(best)>candidate_rank(current))
        mode='remaining' if len(unfinished)==1 else 'rolling'
        record={'t_ms':w.now,'actor':'B1','policy':self.policy,'mode':mode,**asdict(decision),
            'input':asdict(with_shared_plan(view)),'applied':apply,
            'reason':'collection acknowledgement timed out' if timed_out else 'remaining task boundary' if apply else 'no proven improvement',
            'distinct_evaluated':len({c['id'] for c in decision.candidates})}
        w.decisions.append(record)
        if not apply or not best['legal']:
            return []
        if not initial and self.required and self.proposal not in self.terminal_proposals:
            record.update(applied=False,reason='waiting for old commitment release acknowledgement')
            self.abort(w,'plan repair requires released participants')
            return []
        self.collection_until=None;self.selected=best;self.plan_revision+=1
        commands=list(best.get('staging_commands',[]))+[custom('residual_prepare' if 'own_commands' in best else 'initial_prepare')]
        if not initial:
            self.commands=deque(commands)
        w.emit('B1',mode+'_plan_selected',{'revision':self.plan_revision,'prediction':best,
            'completed_receipts':{t['id']:t['completed_ms'] for t in view.own_tasks if t['completed_ms'] is not None}})
        return commands

    def step(self,w):
        for key,outgoing in list(self.protocol_outbox.items()):
            peer,kind=key;pid=outgoing['payload']['proposal_id']
            acknowledged=peer in (self.accepted if kind=='prepare' else self.commit_acked)
            if pid!=self.proposal or pid in self.terminal_proposals or acknowledged:
                self.protocol_outbox.pop(key,None)
            elif not self.releasing and w.now<=self.proposal_deadline and w.now-outgoing['last_sent']>=2000:
                w.emit(self.actor,'protocol_retry',{'proposal_id':pid,'peer':peer,'kind':kind})
                self.send(w,peer,outgoing['payload'],kind)
        if self.releasing and w.now-self.releasing['last_sent']>=2000:
            self.request_next_release(w)
        if self.actor=='B1' and self.required and self.proposal and w.now>self.proposal_deadline:
            if not self.committed:
                self.abort(w,'prepare confirmations timed out')
        super().step(w)
        retry_ms=w.card.get('ready_retry_ms',2000 if w.card.get('online_replanning') else 0)
        if retry_ms and self.ready_outbox:
            outgoing=self.ready_outbox
            if self.proposal in self.terminal_proposals or self.fresh_consumed:
                self.ready_outbox=None
            elif w.now-outgoing['last_attempt']>=retry_ms:
                # A retransmission is only real if the link accepts it: the transport
                # keys on message_id, so the retry has to carry a fresh one.
                mid=self.send(w,outgoing['target'],outgoing['payload'],outgoing['prefix'])
                w.emit(self.actor,'message_retry',{'message_id':mid,'replaces':outgoing['id'],'to':outgoing['target']})
        w.retry_station_report(self.actor)
        self.monitor(w)

    def monitor(self,w):
        if self.actor!='B1' or self.selected is None:
            return
        view=w.view(self.actor)
        changed=len(view.inbox)!=self.last_inbox_count
        if not changed and w.now-self.last_monitor<500:
            return
        self.last_monitor=w.now;self.last_inbox_count=len(view.inbox)
        remaining=[t for t in view.own_tasks if t['completed_ms'] is None]
        current=w.busy.get(self.actor)
        samples=[t for t in self.selected.get('sampling_ms',[]) if t is not None]
        sample=max(w.now,next((t for t in samples if t>=w.now),w.now))
        diagnosis=diagnose(view,sample)
        status,reason=diagnosis.status,diagnosis.reason
        if not remaining:
            status,reason='done','All locally assigned deliveries have actual completion receipts'
        elif view.inventory or current and current[0] in ('load','unload'):
            status,reason='report_not_required','A lawful load has started or cargo is already held'
        elif self.selected['assignment']=='split' and any(t['id']=='blue1' and t['completed_ms'] is not None for t in view.own_tasks):
            status,reason='unknown','Delegated delivery has no received completion acknowledgement'
        elif status!='feasible' and sample>w.now:
            status,reason='unknown','A future observation/report is predicted but has not been received'
        w.diagnostics.append({'t_ms':w.now,'actor':self.actor,'trigger':'message' if changed else 'periodic',
             'node':view.node,'inventory':view.inventory,'own_action':current[0] if current else None,
             'status':status,'reason':reason,'report_margin_ms':diagnosis.report_margin_ms,
             'deadline_margin_ms':min((t['deadline_ms']-w.now for t in remaining),default=None),
             'predicted_sampling_ms':sample,'received_message_count':len(view.inbox),
             'last_received_message_id':view.inbox[-1].message_id if view.inbox else None,
             'reports':[asdict(r) for r in view.reports],
             'known_tasks':list(view.own_tasks),'proposal_id':self.proposal})

    def send(self,w,target,payload,prefix):
        if w.card.get('online_replanning') and payload.get('kind')=='ready' and self.proposal:
            payload={**payload,'proposal_id':self.proposal}
        self.counter += 1
        mid=f'{prefix}_{self.actor}_{self.counter}'
        w.send(self.actor,target,payload,mid)
        if w.card.get('online_replanning') and self.actor=='B1' and payload.get('kind') in ('prepare','commit'):
            self.protocol_outbox[target,payload['kind']]={'payload':payload,'last_sent':w.now}
        if payload.get('kind')=='ready':
            self.ready_outbox={'id':mid,'prefix':prefix,'target':target,'payload':payload,'last_attempt':w.now}
        return mid

    def phase(self,w,state,role):
        w.emit(self.actor,'role_state',{'state':state,'role':role,'node':w.view(self.actor).node,
                                      'proposal_id':self.proposal})

    def request_next_release(self,w):
        state=self.releasing
        peer=next((p for p in state['peers'] if p not in state['acked']),None)
        if peer is None:
            self.finish_release(w)
            return
        self.send(w,peer,{'kind':'release_request','proposal_id':state['proposal_id']},'release')
        state['last_sent']=w.now
        w.emit(self.actor,'release_requested',{'proposal_id':state['proposal_id'],'peer':peer})

    def finish_release(self,w):
        state=self.releasing;pid=state['proposal_id']
        self.terminal_proposals.add(pid);self.required=set();self.pending=None;self.committed=False
        self.selected=None;self.collection_until=None;self.releasing=None
        self.commands=deque([custom('bootstrap')])
        w.emit('B1','release_complete',{'proposal_id':pid,'reason':state['reason']})

    def reoffer_task_results(self,w):
        """Re-send receipts for deliveries the coordinator may never have heard about.

        The world keys each completion receipt on a fixed message id, so a copy lost in
        flight is gone for good and the planner would re-plan an already delivered cargo.
        A release answer is retried by the coordinator until it arrives, so carrying the
        receipts on every one of them makes the knowledge eventually reliable.
        """
        for t in w.view(self.actor).own_tasks:
            if t['kind'] != 'delivery' or t['completed_ms'] is None:
                continue
            self.counter += 1
            w.send(self.actor,'B1',{'kind':'task_result','task_id':t['id'],
                'completed_ms':t['completed_ms']},f'task_result_reoffer_{t["id"]}_{self.counter}')

    def release_peer(self,w):
        request=self.release_requested;self.release_requested=None
        if w.view(self.actor).inventory:
            self.send(w,'B1',{'kind':'release_denied','proposal_id':request['proposal_id'],
                'reason':'held cargo must stay with its lawful owner'},'release_denied')
            return
        old=self.proposal
        self.terminal_proposals.add(old);self.pending=None;self.committed=False;self.ready_outbox=None
        self.release_receipts[old]=w.now
        node=w.view(self.actor).node
        self.phase(w,'RELEASED','old commitment released at actual action boundary')
        w.emit(self.actor,'commitment_released',{'proposal_id':old,'node':node})
        self.send(w,'B1',{'kind':'release_ack','proposal_id':old,'released_at':w.now},'release_ack')
        self.reoffer_task_results(w)
        pause=self.actor=='B2' or any(t['id']=='blue_inspect' and t['completed_ms'] is not None
                                     for t in w.view(self.actor).own_tasks)
        commands=path(node,'F')+[custom('air_finish')] if self.actor=='B3' else path(node,'J')+[custom('status'),('hold',None)]
        self.commands=deque(([custom('hold_delay')] if pause else [])+commands)

    def release_message(self,w,m):
        p=m.payload;kind=p.get('kind');pid=p.get('proposal_id')
        if kind=='release_request' and self.actor in ('B2','B3') and m.sender=='B1':
            if pid in self.terminal_proposals or pid!=self.proposal:
                self.send(w,'B1',{'kind':'release_ack','proposal_id':pid,
                    'released_at':self.release_receipts.get(pid,-1)},'release_ack')
                self.reoffer_task_results(w)
            else:
                self.release_requested=p
            return True
        state=self.releasing
        if kind not in ('release_ack','release_denied'):
            return False
        if self.actor=='B1' and kind=='release_ack' and pid==self.proposal and p.get('released_at',-1)>=0:
            # A peer that ended its own service reports the release before any request is
            # possible; forgetting it would leave the coordinator asking a peer that already
            # answered, and it may be out of radio contact by the time the plan breaks.
            self.peer_released[pid,m.sender]=p['released_at']
            if not state and m.sender=='B3' and self.fresh_consumed:
                self.required.discard('B3')
                w.emit('B1','release_acknowledged',{'proposal_id':pid,'peer':'B3','reason':'natural execution end'})
        if self.actor!='B1' or not state or pid!=state['proposal_id']:
            return True
        peer=next((p for p in state['peers'] if p not in state['acked']),None)
        if peer is None or m.sender!=peer:
            return True
        if kind=='release_denied':
            self.release_denied_for.add(pid)
            self.commands=state['resume'];self.releasing=None
            w.emit('B1','release_refused',{'proposal_id':pid,'peer':peer,'reason':p['reason']})
            return True
        state['acked'].add(peer)
        w.emit('B1','release_acknowledged',{'proposal_id':pid,'peer':peer})
        if set(state['peers'])!=state['acked']:
            self.request_next_release(w)
            return True
        self.finish_release(w)
        return True

    def on_message(self,w,m):
        p = m.payload
        if isinstance(p,Report):
            if report_valid(p,'device',w.now):
                self.collection_until=None
            if p.source_id=='B3' and self.actor in ('B1','B2'):
                if report_valid(p,'device',w.now):
                    self.ready_outbox=None
                w.emit(self.actor,'service_report_received',{'source':'B3','sampled_at':p.sampled_at,
                       'received_at':w.now,'report_age_ms':w.now-p.sampled_at})
            return
        if not isinstance(p,dict):
            return
        if m.sender=='entrance' and p.get('kind')=='reservation_cancel_ack' and self.channel_cancel and p['slot_id']==self.channel_cancel['slot_id']:
            if not p['released']:self.channel_cancel_denied.add(p['slot_id'])
            w.emit(self.actor,'channel_rebook_acknowledged',{'slot_id':p['slot_id'],'released':p['released']})
            self.channel_cancel=None
            return
        if w.card.get('online_replanning') and self.release_message(w,m):
            return
        if p.get('proposal_id') in self.terminal_proposals:
            return
        a = self.actor
        if p.get('kind')=='status_request' and a in ('B2','B3') and m.sender in ('B1','B2'):
            if m.sender=='B1':
                self.command(w,{'kind':'status'})
            if p.get('include_report'):
                reports=[r for r in w.view(a).reports if r.subject_id=='device']
                if reports:
                    latest=max(reports,key=lambda r:r.sampled_at)
                    # A copy that cannot arrive inside its own freshness window is not evidence.
                    if report_valid(latest,'device',w.now+w.network.delay):
                        self.counter+=1
                        w.send(a,m.sender,latest,f'resent_report_{a}_{self.counter}')
            return
        if p.get('kind')=='task_result' and a=='B1' and m.sender=='B2' and self.selected:
            cargo=self.selected.get('cargo_id','blue2') if self.selected.get('assignment')=='split' else None
            if p['task_id']==cargo:
                self.required.discard('B2')
        if p.get('kind')=='prepare' and a in ('B2','B3'):
            if self.pending and self.proposal==p['proposal_id']:
                self.send(w,'B1',{'kind':'accept','proposal_id':self.proposal},'accept')
                return
            if p.get('residual_workflow') and (a in w.busy or w.view(a).inventory):
                self.send(w,'B1',{'kind':'reject','proposal_id':p['proposal_id'],'reason':'actuator or held cargo is committed'},'reject')
                return
            if w.now>p['expires_at']:
                self.send(w,'B1',{'kind':'reject','proposal_id':p['proposal_id'],'reason':'expired prepare'},'reject')
                w.emit(a,'proposal_rejected',{'reason':'expired prepare'})
                return
            if self.pending and self.proposal!=p['proposal_id']:
                self.send(w,'B1',{'kind':'reject','proposal_id':p['proposal_id'],'reason':'already committed'},'reject')
                return
            # The air vehicle checks its own real commitment, not the coordinator's forecast.
            if a=='B3':
                local=w.view(a);m=local.public_map
                own = next(t for t in local.own_tasks if t['id']=='blue_inspect')
                lower_finish = (w.now+4*w.network.delay+travel_ms(m,'K','H')
                    +travel_ms(m,'H','K')+travel_ms(m,'K','F')+2*m['service_ms'])
                if own['completed_ms'] is None and lower_finish>own['deadline_ms']:
                    self.send(w,'B1',{'kind':'reject','proposal_id':p['proposal_id'],
                                     'reason':'own inspection commitment infeasible'},'reject')
                    w.emit(a,'proposal_rejected',{'reason':'own inspection commitment infeasible'})
                    return
            self.proposal=p['proposal_id']
            self.pending=p
            self.peer_ready=set();self.fresh_consumed=set()
            self.phase(w,'CONFIRMED',p['role'])
            self.send(w,'B1',{'kind':'accept','proposal_id':self.proposal},'accept')
            self.commands=deque([custom('commit_wait'),('hold',None)])
        elif p.get('kind')=='accept' and a=='B1' and p['proposal_id']==self.proposal:
            self.accepted.add(m.sender)
            if self.accepted==self.required and not self.committed:
                self.committed=True
                self.commit_sent_at=w.now
                for peer in sorted(self.required):
                    self.send(w,peer,{'kind':'commit','proposal_id':self.proposal},'commit')
                w.emit(a,'reconfiguration_committed',{'proposal_id':self.proposal,'participants':sorted(self.required)})
        elif p.get('kind')=='commit' and p.get('proposal_id')==self.proposal and self.pending:
            self.committed=True
            if w.card.get('online_replanning'):
                self.send(w,'B1',{'kind':'commit_ack','proposal_id':self.proposal},'commit_ack')
        elif p.get('kind')=='commit_ack' and a=='B1' and p['proposal_id']==self.proposal and m.sender in self.required:
            self.commit_acked.add(m.sender)
        elif p.get('kind')=='ready':
            if p.get('proposal_id') is not None and p['proposal_id']!=self.proposal:
                return
            self.peer_ready.add(m.sender)
        elif p.get('kind')=='collect' and a=='B2' and not self.pending:
            mode=p['mode'];receiver=p['receiver']
            dest='J' if mode=='refresh' else 'L'
            route=ground_observation(w.view(a).public_map,w.view(a).node,dest,True)
            if route is None:
                w.emit(a,'collection_unavailable',{'receiver':receiver,'destination':dest})
                return
            self.commands=deque(move(*route['to_observation'])+[('observe',None)]+move(*route['from_observation'])
                                +[('send_report',receiver),custom('hold_delay')])
            if dest=='L':
                self.commands.append(custom('travel',target='J'))
            self.commands.extend([('hold',None)])
        elif p.get('kind')=='reject' and a=='B1' and p['proposal_id']==self.proposal:
            self.abort(w,p['reason'])
        elif p.get('kind')=='service_failed' and a=='B2' and self.pending and p['proposal_id']==self.proposal:
            self.terminal_proposals.add(self.proposal)
            self.phase(w,'RELEASED','transport after failed support')
            self.pending=None;self.committed=False
            # Carry the failure notification to the coordinator using the same graph/network.
            self.commands=deque([custom('travel',target='D'),
                ('send',('B1',{'kind':'reject','proposal_id':self.proposal,'reason':p['reason']},'carried_failure_'+self.proposal)),
                custom('hold_delay'),custom('travel',target='J'),('hold',None)])
        elif p.get('kind')=='abort' and p.get('proposal_id')==self.proposal:
            self.terminal_proposals.add(self.proposal)
            self.pending=None;self.committed=False
            self.phase(w,'RELEASED','proposal cancelled')
            if a=='B3':
                self.commands=deque(path(w.view(a).node,'F')+[custom('air_finish'),('hold',None)])
            else:
                self.commands=deque(path(w.view(a).node,'J')+[('hold',None)])

    def abort(self,w,reason):
        if w.card.get('online_replanning') and self.required:
            if not self.releasing and self.proposal not in self.release_denied_for:
                # Peers that announced their own release earlier already answered; asking them
                # again would stall the coordinator behind a peer that has nothing left to do.
                acked={p for (pid,p) in self.peer_released
                       if pid==self.proposal and p in self.required}
                self.releasing={'proposal_id':self.proposal,'peers':sorted(self.required),
                    'acked':acked,'last_sent':w.now,'reason':reason,'resume':deque(self.commands)}
                w.emit(self.actor,'reconfiguration_release_started',{'proposal_id':self.proposal,
                    'reason':reason,'peers':sorted(self.required),'service_until':self.service_deadline})
                cargo=w.view(self.actor).inventory or w.mission.loading.get(self.actor)
                # Waiting for a release ack in a radio dead zone is waiting forever: L is the
                # only node with edges to all of J, K and H, so the handshake is done from there.
                self.commands=deque((self.deliver(cargo) if cargo else [])+[custom('travel',target='L'),('hold',None)])
                self.request_next_release(w)
            return
        if self.proposal in self.terminal_proposals:
            return
        self.terminal_proposals.add(self.proposal)
        for peer in sorted(self.required):
            self.send(w,peer,{'kind':'abort','proposal_id':self.proposal},'abort')
        w.emit(self.actor,'reconfiguration_aborted',{'reason':reason})
        self.required=set();self.pending=None
        self.selected={**self.selected,'assignment':'single','support':'fixed','information':'refresh'}
        # Preserve a load already in progress; never cancel a valid physical service as completed.
        if self.actor in w.busy and w.busy[self.actor][0]=='load':
            cargo=w.mission.loading[self.actor]
            self.commands=deque(self.deliver(cargo)+(self.second() if cargo=='blue1' else []))
        elif w.view(self.actor).inventory:
            cargo=w.view(self.actor).inventory
            self.commands=deque(self.deliver(cargo)+(self.second() if cargo=='blue1' else []))
        elif any(t['id']=='blue1' and t['completed_ms'] is not None for t in w.view(self.actor).own_tasks):
            self.commands=deque(self.second())
        elif self.actor not in w.busy and w.view(self.actor).node=='L':
            self.commands=deque(self.first()+self.second())
        else:
            self.commands.extend(self.second())

    def first(self):
        return [custom('fresh'),('load','blue1'),custom('commit_barrier')]+self.deliver('blue1')

    def deliver(self,cargo):
        return [custom('travel',target='D'),('unload',cargo)]

    def second(self):
        return [custom('travel',target='L'),custom('fresh'),('load','blue2')]+self.deliver('blue2')

    def set_deadlines(self,w,view):
        margin=view.public_map.get('protocol_margin_ms',0)
        self.proposal_deadline=w.now+20000
        if margin:
            status=with_shared_plan(view).teammate_status.get('B3',{}) if self.selected['support']=='air' else {}
            contact=status.get('predicted_contact_at',w.now)
            self.proposal_deadline=min(w.card['end_ms'],max(self.proposal_deadline,contact+3*w.network.delay+margin))
        sampling=[t for t in self.selected.get('sampling_ms',[]) if t is not None]
        self.service_deadline=max([self.proposal_deadline]+[t+2*w.network.delay+margin for t in sampling])
        if view.public_map.get('physical_contact_hold_ms') and self.selected['support']=='air':
            deliveries=[t for t in self.selected.get('deliveries_ms',[]) if t is not None]
            deadlines=[t['deadline_ms'] for t in view.own_tasks if t['id'] in ('blue1','blue2') and t['completed_ms'] is None]
            if deliveries and deadlines:
                # READY is an actual rendezvous; spend existing task slack before abandoning a late peer.
                self.service_deadline+=max(0,min(deadlines)-max(deliveries))
        if margin or view.public_map.get('physical_contact_hold_ms'):
            self.service_deadline=min(self.service_deadline,w.card['end_ms'])

    def command(self,w,arg):
        kind,a = arg['kind'],self.actor
        view=w.view(a)
        if kind=='wait_channel_cancel':
            if self.channel_cancel is None:return []
            if w.now-self.channel_cancel['last_sent']>=2000:
                self.channel_cancel['last_sent']=w.now
                self.send(w,'entrance',{'kind':'reservation_cancel','slot_id':self.channel_cancel['slot_id']},'channel_cancel')
            return None
        if kind=='status':
            hold_until=None
            if a=='B3' and 'until' in arg and w.card.get('physical_contact_hold_ms'):
                hold_until=min(w.card['end_ms'],max(arg['until'],w.now+w.card['physical_contact_hold_ms']))
            qualified=[r for r in view.reports if r.subject_id=='device' and r.quality>=1]
            report=max(qualified,key=lambda r:r.sampled_at) if qualified else None
            p={'kind':'status','node':view.node,'observed_at':w.now,
               'available_until':hold_until if hold_until is not None else arg.get('until',w.card['end_ms']),
               'report_sampled_at':report.sampled_at if report else None,
               'report':asdict(report) if report else None,'source':'delivered_status'}
            if w.card.get('online_replanning'):
                p['inventory']=view.inventory
                if a in w.busy or self.pending:
                    p['available_until']=w.now
            if a=='B3':
                task=next(t for t in view.own_tasks if t['id']=='blue_inspect')
                p.update(inspection_done=task['completed_ms'] is not None,inspection_deadline_ms=task['deadline_ms'])
            self.send(w,'B1',p,'status')
            return [('at',hold_until)] if hold_until is not None else []
        if kind=='bootstrap':
            if all(t['completed_ms'] is not None for t in view.own_tasks if t['id'] in ('blue1','blue2')):
                return [('hold',None)]
            if w.card.get('online_replanning') and (view.inventory or self.terminal_proposals or
                    any(t.get('completed_ms') is not None for t in view.own_tasks if t['id'] in ('blue1','blue2'))):
                if w.now<w.network.delay:
                    return None
                return self.replan_remaining(w,view,initial=True)
            # Initial stale cache cannot trigger a decision before the first real observation arrives.
            if (not any(r.subject_id=='device' and r.sampled_at>=0 for r in view.reports)
                and not (w.card.get('m2') and 'B2' in view.teammate_status)):
                return None
            decision=propose(view,self.policy)
            self.selected=next(c for c in decision.candidates if c['id']==decision.chosen)
            w.decisions.append({'t_ms':w.now,'actor':a,'policy':self.policy,**asdict(decision),
                                'input':asdict(with_shared_plan(view)),
                                'diagnosis':asdict(diagnose(view,w.now)),
                                'distinct_evaluated':len({c['id'] for c in decision.candidates})})
            w.emit(a,'decision_selected',{'id':decision.chosen,'policy':self.policy,
                   'prediction':self.selected})
            return list(self.selected.get('staging_commands',[]))+[custom('residual_prepare' if 'own_commands' in self.selected else 'initial_prepare')]
        if kind=='initial_prepare':
            if self.selected['information']=='wait':
                return [('hold',None)]
            self.proposal=f'{w.run_id}_reconfigure' if not self.plan_revision else f'{w.run_id}_rolling_{self.plan_revision}'
            self.accepted=set();self.peer_ready=set();self.required=set();self.committed=False;self.commit_acked=set()
            self.commit_sent_at=None;self.fresh_consumed=set()
            self.set_deadlines(w,view)
            if self.selected['assignment']=='split':
                self.required.add('B2')
            if self.selected['support']=='air':
                self.required.add('B3')
            fresh=any(report_valid(r,'device',w.now) for r in view.reports)
            recipients=[]
            if self.selected['assignment']=='split':
                recipients.append('B2')
            if not fresh:
                recipients.append('B1')
            for peer in sorted(self.required):
                role='transport' if peer=='B2' else 'observe'
                self.send(w,peer,{'kind':'prepare','role':role,'proposal_id':self.proposal,
                        'route':self.selected['route'],'support':self.selected['support'],
                        'recipients':recipients,'information':self.selected['information'],
                        'first_needs_report':not fresh,
                        'expires_at':self.proposal_deadline,'service_until':self.service_deadline},'prepare')
                w.emit(a,'role_state',{'state':'PROPOSED','provider':peer,'role':role,'proposal_id':self.proposal})
            if 'B1' in recipients and self.selected['support']=='air':
                self.send(w,'B3',{'kind':'ready'},'ready')
            commands=self.first()
            if self.selected['assignment']=='single':
                commands+=self.second()
            elif self.selected['support']=='fixed' and self.selected.get('needs_b1_observer'):
                # A future B1 observation is a real service, never a synthetic report.
                commands += [custom('travel',target='L'),custom('observe_for',target='J',receiver='B2')]
            return commands
        if kind=='residual_prepare':
            selected=self.selected
            if not selected.get('remaining_tasks'):
                return [('hold',None)]
            if w.now<selected.get('request_at',w.now):
                return None
            self.proposal=f'{w.run_id}_remaining_{self.plan_revision}'
            self.accepted=set();self.peer_ready=set();self.required=set(selected.get('required',[]));self.commit_acked=set()
            self.committed=not self.required;self.commit_sent_at=w.now if not self.required else None
            self.fresh_consumed=set();self.set_deadlines(w,view)
            for peer in sorted(self.required):
                self.send(w,peer,{'kind':'prepare','proposal_id':self.proposal,
                    'role':'transport' if peer=='B2' else 'observe','route':selected['route'],
                    'support':selected['support'],'information':selected['information'],
                    'recipients':[selected['transport_actor']] if selected['support']=='air' else [],
                    'first_needs_report':selected.get('requires_new_report',False),
                    'residual_workflow':selected['peer_commands'][peer],
                    'expires_at':self.proposal_deadline,'service_until':self.service_deadline},'prepare')
            if selected['support']=='air' and selected['transport_actor']=='B1':
                self.send(w,'B3',{'kind':'ready'},'ready')
            return selected['own_commands']
        if kind=='travel':
            route=self.selected['route'] if self.selected else self.pending.get('route','channel') if self.pending else 'channel'
            return path(view.node,arg['target'],route)
        if kind=='commit_barrier':
            if not self.required:
                return []
            if self.commit_sent_at is None or w.now<self.commit_sent_at+w.network.delay:
                return None
            return []
        if kind=='fresh':
            reports=[r for r in view.reports if report_valid(r,'device',w.now)]
            if reports:
                r=max(reports,key=lambda r:r.sampled_at)
                if r.source_id=='B3' and r.sampled_at not in self.fresh_consumed:
                    self.fresh_consumed.add(r.sampled_at)
                    w.emit(a,'service_edge_active',{'provider':'B3','consumer':a,'sampled_at':r.sampled_at,
                           'received_and_valid_at':w.now,'proposal_id':self.proposal})
                return []
            old=max(view.reports,key=lambda r:r.sampled_at) if view.reports else None
            if old:
                w.emit(a,'report_rejected',{'age_ms':w.now-old.sampled_at,'tau_ms':old.valid_for_ms,'reason':'expired_before_sampling'})
            if self.pending or self.selected and self.selected['support']=='air' and not self.committed:
                return [('await_fresh',None),custom('fresh')]
            if self.selected and self.selected['support']=='air' and not self.fresh_consumed:
                return [('await_fresh',None),custom('fresh')]
            mode=self.selected['information'] if self.selected else 'refresh'
            if mode=='self':
                if self.required and (self.commit_sent_at is None or w.now<self.commit_sent_at+w.network.delay):
                    return None
                route=ground_observation(view.public_map,'L','L')
                if route is None:
                    w.emit(a,'collection_unavailable',{'mode':'self'})
                    return [('hold',None)]
                return move(*route['to_observation'])+[('observe',None)]+move(*route['from_observation'])+[custom('fresh')]
            if self.selected and self.selected['assignment']=='split':
                return [('await_fresh',None),custom('fresh')]
            self.send(w,'B2',{'kind':'collect','mode':mode,'receiver':a},'collect')
            if w.card.get('online_replanning'):
                next_sample=next((x for x in self.selected.get('sampling_ms',[]) if x is not None and x>=w.now),w.now+20000)
                self.collection_until=next_sample+2*w.network.delay
            return [('await_fresh',None),custom('fresh')]
        if kind=='commit_wait':
            if w.now>self.pending['expires_at']:
                role=self.pending['role']
                self.terminal_proposals.add(self.proposal)
                self.pending=None;self.committed=False
                self.phase(w,'RELEASED',role)
                return path(view.node,'F')+[custom('air_finish')] if a=='B3' else [('hold',None)]
            if not self.committed:
                return None
            self.phase(w,'MOVING',self.pending['role'])
            if self.pending.get('residual_workflow'):
                return self.pending['residual_workflow']
            if a=='B2':
                prefix=[]
                fixed=self.pending['support']=='fixed'
                mode=self.pending['information']
                at_l=ground_travel(view,self.pending['route'],view.node,'L',w.now,a)[0]
                valid_at_l=any(report_valid(r,'device',at_l) for r in view.reports)
                if fixed and mode=='refresh' and self.pending['first_needs_report']:
                    prefix=[custom('observe_for',target='J',receiver='B1')]
                elif fixed and mode in ('self','carry') and (not valid_at_l or self.pending['first_needs_report'] and mode=='carry'):
                    prefix=[custom('observe_to',target='L',remote=mode=='carry' and self.pending['first_needs_report'])]
                commands=prefix+[custom('travel',target='L'),custom('ready')]
                if fixed and mode=='carry' and self.pending['first_needs_report']:
                    commands += [('send_report','B1'),custom('hold_delay')]
                return commands+[custom('fresh'),('load','blue2'),custom('active'),custom('travel',target='D'),('unload','blue2')]
            return [custom('travel',target='H'),custom('ready'),custom('support_service')]
        if kind=='ready':
            self.phase(w,'READY',self.pending['role'])
            if a=='B2' and self.pending['support']=='air':
                self.send(w,'B3',{'kind':'ready'},'ready')
            return []
        if kind in ('observe_for','observe_to'):
            route=ground_observation(view.public_map,view.node,arg['target'],kind=='observe_for' or arg.get('remote',False))
            if route is None:
                w.emit(a,'collection_unavailable',{'destination':arg['target']})
                return [('hold',None)]
            commands=move(*route['to_observation'])+[('observe',None)]+move(*route['from_observation'])
            if kind=='observe_for':
                commands += [('send_report',arg['receiver']),custom('hold_delay')]
            return commands
        if kind=='active':
            self.phase(w,'ACTIVE',self.pending['role'])
            return []
        if kind=='support_service':
            recipients=self.pending['recipients']
            if not set(recipients)<=self.peer_ready:
                own=next(t for t in view.own_tasks if t['id']=='blue_inspect')
                latest=self.pending['service_until']
                if own['completed_ms'] is None:
                    latest=min(latest,own['deadline_ms']-travel_ms(view.public_map,'H','K')
                        -travel_ms(view.public_map,'K','F')-w.card['service_ms']-w.network.delay)
                if w.now>=latest:
                    for peer in ('B1','B2'):
                        self.send(w,peer,{'kind':'service_failed' if peer=='B2' else 'reject',
                                  'proposal_id':self.proposal,'reason':'support READY timed out'},'failed')
                    self.phase(w,'RELEASED','observe')
                    self.terminal_proposals.add(self.proposal)
                    self.pending=None
                    return [custom('hold_delay')]+path(view.node,'F')+[custom('air_finish')]
                return None
            commands=[]
            if recipients:
                commands=[('observe',None)]
                for peer in recipients:
                    commands.append(('send_report',peer))
                commands += [custom('active'),custom('hold_delay')]
            commands += [custom('travel',target='F'),custom('air_finish')]
            return commands
        if kind=='hold_delay':
            return [('at',w.now+w.network.delay*arg.get('hops',1))]
        if kind=='air_finish':
            own=next(t for t in view.own_tasks if t['id']=='blue_inspect')
            self.phase(w,'RELEASED','observe')
            if w.card.get('online_replanning') and self.pending:
                old=self.proposal
                self.terminal_proposals.add(old);self.release_receipts[old]=w.now
                self.pending=None;self.committed=False;self.ready_outbox=None
                w.emit(a,'commitment_released',{'proposal_id':old,'node':view.node,
                    'reason':'local service execution ended; report receipt is not assumed'})
                self.send(w,'B1',{'kind':'release_ack','proposal_id':old,'released_at':w.now},'release_ack')
            finish=w.now+(w.card['service_ms'] if own['completed_ms'] is None else 0)
            commands=[('inspect','blue_inspect')] if own['completed_ms'] is None else []
            period=w.card['reconnect_period_ms']
            # Rejoin the same pre-agreed patrol instead of silently deleting future own activity.
            for release in range(period,w.card['end_ms'],period):
                if release>=finish:
                    commands += [('at',release)]+move('K')+[custom('status',until=release+6000),('at',release+6000)]+move('F')
            return commands
        raise ValueError(kind)


def adaptive_controllers(card,policy):
    from .policies import controllers
    all_controllers=controllers(card,'P0',legacy=True)
    initial=[] if card['fleet']['B1']['node']=='L' else path('D','L')
    all_controllers['B1']=Adaptive('B1',initial+[custom('bootstrap')],policy)
    obs=[] if card['id'].startswith('C0') else [('at',6000),('observe',None)]
    after_observe=move('J')
    if 'geometry' in card:
        if card.get('travel_time_ms'):
            # Preserve the scheduled O observation and actual stale-report evidence on physical cards.
            obs=[('at',6000),('observe',None)]
        else:
            obs=[('at',6000),custom('observe_to',target='J',remote=True)]
            after_observe=[]
        all_controllers['R5']=Adaptive('R5',[('inspect','red_inspect'),custom('hold_delay',hops=2)]+move('K_R')+[('hold',None)],policy)
    all_controllers['B2']=Adaptive('B2',obs+after_observe+[custom('status'),('send_report','B1'),('hold',None)],policy)
    air=move('K')+[custom('status',until=6000),('at',6000)]+move('F')+[('inspect','blue_inspect')]
    for release in range(card['reconnect_period_ms'],card['end_ms'],card['reconnect_period_ms']):
        air += [('at',release)]+move('K')+[custom('status',until=release+6000),('at',release+6000)]+move('F')
    all_controllers['B3']=Adaptive('B3',air,policy)
    if card.get('residual_checkpoint'):
        all_controllers['B1']=Adaptive('B1',[custom('bootstrap')],policy)
        all_controllers['B2']=Adaptive('B2',[custom('status'),('hold',None)],policy)
        all_controllers['B3']=Adaptive('B3',[custom('status',until=card['end_ms']),('hold',None)],policy)
    return all_controllers
