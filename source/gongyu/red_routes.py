"""Local red cargo routes, including a real acknowledged cancellation before rebooking."""
from collections import deque
from dataclasses import asdict,replace

from .contracts import utility
from .policies import Controller
from .remaining import ground_travel


def red_candidates(view,allow_rebook=True):
    if not view.inventory or view.node is None:
        return []
    task=next(t for t in view.own_tasks if t['id']==view.inventory)
    service=view.public_map['service_ms'];rows=[]
    for route in ('channel','bypass'):
        end,commands,movement=ground_travel(view,route,view.node,'D',view.now_ms,view.agent_id)
        rows.append({'id':route,'completed_ms':end+service,'active_ms':movement+service,
            'commands':commands+[('unload',view.inventory)],
            'utility':utility(end+service,task['deadline_ms'],movement+service),
            'conditional_booking':route=='channel' and not any(r['actor']==view.agent_id and not r['used']
                and r.get('cancelled_at') is None for r in view.reservations)})
    own=next((r for r in view.reservations if r['actor']==view.agent_id and not r['used']
              and r.get('cancelled_at') is None and r.get('slot_id')),None)
    if allow_rebook and own and view.node in ('E','L'):
        freed=replace(view,reservations=tuple(r for r in view.reservations if r.get('slot_id')!=own['slot_id']))
        end,commands,movement=ground_travel(freed,'channel',view.node,'D',view.now_ms+2*view.public_map['message_delay_ms'],view.agent_id)
        rows.append({'id':'rebook','completed_ms':end+service,'active_ms':movement+service,
            'slot_id':own['slot_id'],'commands':commands+[('unload',view.inventory)],
            'utility':utility(end+service,task['deadline_ms'],movement+service),
            'conditional_booking':True})
    return rows


def feasible_red_routes(view,rows):
    limits=view.public_map.get('target_constraints')
    if not limits:return list(rows)
    task=next((t for t in view.own_tasks if t['id']==view.inventory),None)
    return [r for r in rows
        if limits['spent_move_ms']+r['active_ms']-view.public_map['service_ms']<=limits['move_budget_ms']
        and (not limits.get('on_time_required',False) or task is not None and r['completed_ms']<=task['deadline_ms'])]


class RedRouteController(Controller):
    def __init__(self,actor,commands,autonomous=False,allow_rebook=True):
        super().__init__(actor,commands)
        self.autonomous=autonomous;self.allow_rebook=allow_rebook
        self.route_signature=None;self.route_choice=None
        self.cancel_pending=None;self.last_cancel_send=-2000;self.cancel_denied=set()
        # Execution-layer state (phase102). The scoring/declaration layer is untouched:
        # these fields only keep an already admitted route alive while physics clears it,
        # and let a task whose on-time window is already lost still be executed.
        self.route_committed_at=None;self.recheck_at=None;self.recovery_active=False
        # Execution-feedback interface (this round). The task layer receives an
        # explicit, logged statement of whether the physical layer can actually
        # deliver the currently held forward-dated channel grant.
        self.execution_feedback=None;self.grant_rebook_done=set()

    @staticmethod
    def _timing(w,name,default):
        card=getattr(w,'card',None)
        return int(card.get(name,default)) if isinstance(card,dict) else default

    @staticmethod
    def recently_held(w,actor,now):
        """Only a real, recent clearance hold protects an admitted departure.

        Other re-forecasts (new booking revisions, transient empty observations,
        late unadmitted routes) must keep their original semantics unchanged.
        """
        events=getattr(w,'events',None)
        if not isinstance(events,(list,tuple)):return False
        for event in reversed(events[-24:]):
            if getattr(event,'actor',None)==actor and getattr(event,'kind',None)=='physical_departure_held':
                return now-getattr(event,'t_ms',now)<=5000
        return False

    def recovery_candidate(self,view,rows,task):
        """Earliest budget-legal route when every on-time candidate has disappeared.

        The declared quota still governs *selection* in choose_route, and the referee
        still records on_time=False at the real completion instant. This only removes
        the terminal hold that would otherwise strand an own cargo forever.
        """
        limits=view.public_map.get('target_constraints')
        if not limits or not limits.get('on_time_required'):return None
        if task.get('completed_ms') is not None:return None
        # Recovery is for a cargo still at the E entrance, not for a half-finished
        # route, an L-stage wait, or a late move never admitted by the common quota.
        if view.node!='E' or self.route_choice is not None:return None
        legal=[r for r in rows if r['id'] in ('channel','bypass')
            and limits['spent_move_ms']+r['active_ms']-view.public_map['service_ms']<=limits['move_budget_ms']]
        return min(legal,key=lambda r:(r['completed_ms'],r['active_ms'])) if legal else None

    def choose_route(self,view,rows):
        legal=feasible_red_routes(view,rows)
        return max(legal,key=lambda r:r['utility']) if legal else None,dict(
            feasible_candidate_ids=[r['id'] for r in legal],
            reason='Common own on-time quota and movement budget; then own completion utility')

    def request_cancel(self,w):
        self.counter+=1;self.last_cancel_send=w.now
        w.send(self.actor,'entrance',{'kind':'reservation_cancel','slot_id':self.cancel_pending['slot_id']},
               f'cancel_{self.actor}_{self.counter}')
        w.emit(self.actor,'red_cancel_requested',dict(self.cancel_pending))

    def route_message(self,w,m):
        p=m.payload
        if not isinstance(p,dict) or p.get('kind')!='reservation_cancel_ack' or m.sender!='entrance':
            return False
        if self.cancel_pending and p['slot_id']==self.cancel_pending['slot_id']:
            w.emit(self.actor,'red_cancel_acknowledged',{'slot_id':p['slot_id'],'released':p['released']})
            if not p['released']:
                self.cancel_denied.add(p['slot_id'])
            self.cancel_pending=None;self.route_signature=None
        return True

    def on_message(self,w,m):
        if not self.route_message(w,m):
            super().on_message(w,m)

    def step(self,w):
        if self.autonomous and self.cancel_pending and w.now-self.last_cancel_send>=2000:
            self.request_cancel(w)
        super().step(w)

    def route_before_actions(self,w,locked=False):
        if not self.autonomous or locked:
            return
        # phase112: decision layers need the referee's real occupancy events.
        self.execution_world=w
        view=w.view(self.actor)
        if not view.inventory:
            self.recovery_active=False
            return
        # Finish an admitted exit/unload; a new forecast must not strand held resources.
        if view.node in ('W','D') and self.route_choice is not None:
            return
        # An admitted route can be physically held by clearance or a future booking.
        # Keep its pending move intent instead of letting a later re-forecast replace
        # it with a terminal hold; bound the wait so a genuinely stuck route is retried.
        if (self.route_choice is not None and self.commands
                and self.commands[0][0]=='move'
                and (self.recovery_active or self.recently_held(w,self.actor,w.now))):
            if self.route_committed_at is None:self.route_committed_at=w.now
            if w.now-self.route_committed_at<=self._timing(w,'route_hold_timeout_ms',30000):
                return
        task=next(t for t in view.own_tasks if t['id']==view.inventory)
        if w.now<task.get('release_ms',0):return
        if self.cancel_pending and self.cancel_pending['blocking']:
            self.commands=deque([('hold',None)])
            return
        own_grant=next((r for r in view.reservations if r['actor']==self.actor and not r['used']
                        and r.get('cancelled_at') is None and r.get('slot_id')),None)
        grace=self._timing(w,'reservation_grace_ms',2000)
        # The lapse guard is a *rescue* deadline, not a re-planning horizon: it may only
        # fire when the entry window is about to be lost. Re-planning earlier than that
        # would convert a blocking window into an earlier one and give the opponent time
        # back (observed at 147 s: 150-198 s -> 148-196 s).
        lapse_guard=self._timing(w,'grant_lapse_guard_ms',800)
        blocked=self.recently_held(w,self.actor,w.now)
        feedback=dict(node=view.node,now_ms=w.now,
                      own_slot_id=own_grant['slot_id'] if own_grant else None,
                      grant_start_ms=own_grant['start'] if own_grant else None,
                      grant_end_ms=own_grant['end'] if own_grant else None,
                      grace_ms=grace,
                      window_left_ms=(own_grant['start']+grace-w.now) if own_grant else None,
                      held_recently=blocked,
                      in_channel=(view.node in ('W','D')))
        # Execution feedback -> task layer. A forward-dated grant that the physical
        # layer cannot enter inside [start, start+grace] is not a real occupancy: if it
        # is allowed to expire, the resource is handed back to the opponent earlier than
        # in the independent baseline. Convert it into an immediate, acknowledged grant
        # while the actor is still at the entrance. This fires only for a grant that is
        # *already* blocked near its deadline, so a healthy blocking window is kept.
        if (self.autonomous and own_grant is not None and view.node in ('E','L')
                and own_grant['start']+grace-w.now<=lapse_guard
                and blocked
                and own_grant['slot_id'] not in self.grant_rebook_done
                and not self.cancel_pending):
            self.grant_rebook_done.add(own_grant['slot_id'])
            self.cancel_pending={'slot_id':own_grant['slot_id'],'blocking':True}
            self.request_cancel(w)
            self.route_signature=None;self.recheck_at=None
            self.commands=deque([('hold',None)])
            w.emit(self.actor,'grant_expiry_rebook',{
                'slot_id':own_grant['slot_id'],'grant_start_ms':own_grant['start'],
                'grant_end_ms':own_grant['end'],'now_ms':w.now,
                'window_left_ms':own_grant['start']+grace-w.now,
                'reason':'execution layer cannot enter a forward-dated grant inside its grace window; convert to an immediate acknowledged grant'})
            return
        # A grant is deliverable while its entry window has not lapsed: the
        # event-triggered rebooking above converts it into an immediate grant
        # before expiry. Only an already-expired grant is undeliverable.
        feedback['deliverable']=bool(own_grant is None
            or (view.node in ('E','L') and w.now<=own_grant['start']+grace
                and own_grant['slot_id'] not in self.grant_rebook_done))
        self.execution_feedback=feedback
        # With the switch off every added term is None/empty, so this is exactly
        # the phase111 signature (off receipt). With the switch on, a recomputed
        # physical release and a changed reservation end force a rolling re-plan.
        from . import release_aware
        active=release_aware.mechanism()!='phase111'
        rolling=(getattr(w,'channel_release_recomputed',0),) if (active and getattr(self,'rolling_enabled',False)) else ()
        signature=(view.node,view.inventory,rolling,tuple((r.get('slot_id'),r['actor'],r['start'],
            r.get('revision',0),r.get('used'),r.get('cancelled_at'),r.get('end') if active else None) for r in view.reservations))
        rows=red_candidates(view,self.allow_rebook)
        rows=[r for r in rows if r.get('slot_id') not in self.cancel_denied]
        if signature==self.route_signature:
            feasible={r['id'] for r in feasible_red_routes(view,rows)}
            if self.route_choice in feasible:return
            # A "no legal route" verdict must not freeze forever: reservations can stay
            # unchanged while clearance, channel occupancy or the clock move on.
            if self.route_choice is None and not feasible:
                if self.recheck_at is None:
                    self.recheck_at=w.now+self._timing(w,'route_recheck_ms',5000)
                if w.now<self.recheck_at:return
                self.recheck_at=None
        self.route_signature=signature
        best,details=self.choose_route(view,rows)
        self.route_choice=best['id'] if best else None
        w.emit(self.actor,'red_route_decision',{'chosen':self.route_choice,'candidates':rows,'input':asdict(view),
                                                'execution_feedback':self.execution_feedback,**details})
        # phase112: structured candidate / reservation / channel / berth ledger.
        # Never emitted when the switch is off, so the off receipt stays exact.
        if release_aware.mechanism()!='phase111':
            w.emit(self.actor,'decision_ledger',{
                'chosen':self.route_choice,'mechanism':release_aware.describe(),
                'candidate_set':[{'id':r['id'],'completed_ms':r['completed_ms'],'active_ms':r['active_ms'],
                                 'conditional_booking':r.get('conditional_booking'),'slot_id':r.get('slot_id')} for r in rows],
                'reservation_snapshot':[{'slot_id':r.get('slot_id'),'actor':r.get('actor'),
                                        'start':r.get('start'),'end':r.get('end'),'revision':r.get('revision',0)}
                                       for r in view.reservations],
                'channel_state':{'node':view.node,'now_ms':w.now,
                                'release_recompute_count':getattr(w,'channel_release_recomputed',0)},
                'berth_state':{'node':view.node,'free':release_aware.berth_free(w,view.node)},
                'source_identity':'phase112_release_aware_source'})
        if best is None:
            recovery=self.recovery_candidate(view,rows,task)
            if recovery is None:
                self.commands=deque([('hold',None)]);return
            w.emit(self.actor,'deadline_miss_recovery',{
                'task_id':view.inventory,'decision_chosen':None,'recovery_route':recovery['id'],
                'forecast_completed_ms':recovery['completed_ms'],'deadline_ms':task['deadline_ms'],
                'overdue_ms':recovery['completed_ms']-task['deadline_ms'],
                'reason':'own on-time window already lost; execute the earliest budget-legal route and keep the real on_time verdict'})
            self.route_choice=recovery['id'];self.route_committed_at=w.now
            self.recovery_active=True
            self.commands=deque(recovery['commands'])
            return
        own=next((r for r in view.reservations if r['actor']==self.actor and not r['used']
                  and r.get('cancelled_at') is None and r.get('slot_id')),None)
        if best['id']=='rebook' or best['id']=='bypass' and own:
            if not self.cancel_pending:
                self.cancel_pending={'slot_id':best.get('slot_id',own['slot_id']),
                                     'blocking':best['id']=='rebook'}
                self.request_cancel(w)
        self.route_committed_at=w.now;self.recheck_at=None;self.recovery_active=False
        self.commands=deque([('hold',None)] if best['id']=='rebook' else best['commands'])

    def before_actions(self,w):
        self.route_before_actions(w)
