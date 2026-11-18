"""Own-task, reciprocal, constrained adversarial and nonresponsive target policies."""
import copy
from dataclasses import replace
from .red_routes import RedRouteController,feasible_red_routes
from .remaining import ground_travel,channel_rebooking
from .timing import travel_ms
from . import release_aware

MODES=('independent','reciprocal','adversarial','nonresponsive')


def with_target_mode(card,mode):
    if mode not in MODES or not card.get('m2'):raise ValueError('target mode requires the declared M2 task family')
    card=copy.deepcopy(card);card['target_mode']=mode
    card['target_constraints']=dict(movement_budget_ms={a:160000 if s['mode']=='ground' else 120000 for a,s in card['fleet'].items() if a.startswith('R')},
        minimum_on_time_deliveries={'R1':1,'R2':1},observation_period_ms=1000,observation_max_age_ms=2000)
    card['id']+='_'+mode
    return card


class ModeRouteController(RedRouteController):
    def __init__(self,actor,commands,mode):
        super().__init__(actor,commands,autonomous=mode!='nonresponsive',allow_rebook=True)
        self.mode=mode
        self.rolling_enabled=(mode=='adversarial' and release_aware.enabled('rolling'))

    def on_message(self,w,m):
        p=m.payload
        if isinstance(p,dict) and p.get('kind')=='m2_request' and m.sender=='B1':
            if self.mode!='nonresponsive':
                self.counter+=1;cid=p['contract_id']
                w.send(self.actor,'B1',dict(kind='m2_reject',contract_id=cid,reason='target mode does not offer cross-team service'),
                       f'{self.actor}_mode_reject_{self.counter}',contract_id=cid)
            return
        super().on_message(w,m)

    def choose_route(self,view,rows):
        if self.mode!='adversarial':return super().choose_route(view,rows)
        limits=view.public_map['target_constraints']
        feasible=feasible_red_routes(view,rows)
        messages=[m.payload for m in view.inbox if m.sender=='entrance' and isinstance(m.payload,dict) and m.payload.get('kind')=='entrance_observation']
        observation=max(messages,key=lambda p:p['observed_at']) if messages else None
        waiting=[]
        if observation and 0<=view.now_ms-observation['observed_at']<=limits['observation_max_age_ms']:
            waiting=[r for r in observation['waiting'] if r['actor'].startswith('B') and r.get('node') in ('E','L') and r['since_ms']<=observation['observed_at']]
        occupancy=travel_ms(view.public_map,'E','W')
        w=getattr(self,'execution_world',None)
        mech=release_aware.mechanism()
        scoring=release_aware.enabled('scoring',mech)
        joint=release_aware.enabled('joint',mech)
        effective_occupancy=(release_aware.effective_occupancy_ms(
            w,occupancy,view.public_map['channel_gap_ms']) if scoring else occupancy)
        freed=replace(view,reservations=tuple(r for r in view.reservations if not (r['actor']==view.agent_id and not r.get('used') and r.get('cancelled_at') is None)))
        def blue_arrival(v,node,at,actor):
            channel=ground_travel(v,'channel',node,'D',at,actor)[0]
            at_e=at+(travel_ms(v.public_map,'L','E') if node=='L' else 0)
            earlier=channel_rebooking(v,'E','W',at_e,actor)
            if earlier:channel=min(channel,earlier['arrived_ms']+travel_ms(v.public_map,'W','D'))
            return min(channel,ground_travel(v,'bypass',node,'D',at,actor)[0])
        def proxy(r):
            if r['id']!='channel':return 0
            entry=r['completed_ms']-view.public_map['service_ms']-travel_ms(view.public_map,'W','D')-occupancy
            own=next((b for b in view.reservations if b['actor']==view.agent_id and not b.get('used') and b.get('cancelled_at') is None and b.get('direction')==['E','W'] and b['start']<=entry<=b['start']+view.public_map.get('reservation_grace_ms',2000)),None)
            committed=r['id']=='channel' and own is not None
            # Execution-feedback gate (this round). The forecast in `remaining.py` now
            # respects an authoritative grant, so a held window is normally deliverable.
            # This gate covers the remaining case: when the execution layer reports that
            # the grant cannot be entered inside its grace window, the task layer must not
            # score it as pressure, because it can never be realised and the resource will
            # be handed back to the opponent anyway.
            feedback=getattr(self,'execution_feedback',None) or {}
            if own is not None and feedback.get('deliverable') is False:return 0
            approach=travel_ms(view.public_map,'L','E') if view.node=='L' else 0
            if view.node not in ('E','L') or entry<view.now_ms+approach or not committed and entry>view.now_ms+limits['observation_max_age_ms']:return 0
            occupied=own['end']-own['start'] if committed else occupancy
            # scoring: a grant cannot block the opponent for longer than the
            # physical traversal the execution layer has actually measured.
            if scoring:occupied=min(occupied,effective_occupancy)
            projected=dict(actor=view.agent_id,start=entry,end=entry+occupied,used=False,direction=['E','W'])
            occupied_view=replace(freed,reservations=freed.reservations+(projected,))
            total=0
            for peer in waiting:
                # A staging observation does not reveal readiness; use a declared crossing-length grid.
                offsets=range(0,occupancy+1,max(1,limits.get('observation_period_ms',1000))) if peer['node']=='L' else (0,)
                delays=[max(0,blue_arrival(occupied_view,peer['node'],view.now_ms+dt,peer['actor'])-blue_arrival(freed,peer['node'],view.now_ms+dt,peer['actor'])) for dt in offsets]
                total+=sum(delays)//len(delays)
            return total
        scores={r['id']:proxy(r) for r in feasible}
        task=next((t for t in view.own_tasks if t['id']==view.inventory),None)
        deadline=task['deadline_ms'] if task else view.public_map['end_ms']
        margins={r['id']:deadline-r['completed_ms'] for r in feasible}
        berth_ok=release_aware.berth_free(w,view.node) if w is not None else True
        if joint:
            key=lambda r:release_aware.joint_rank_key(
                scores[r['id']],margins[r['id']],r['active_ms'],berth_ok)
            reason='Joint ranking: blue marginal delay, own deadline margin, movement budget, berth availability'
        else:
            key=lambda r:(scores[r['id']],*r['utility'])
            reason='Common own constraints; alternative-aware marginal route delay, then own utility'
        best=max(feasible,key=key) if feasible else None
        rank_detail=[{'id':r['id'],'blue_delay_ms':scores[r['id']],
                      'red_deadline_margin_ms':margins[r['id']],'active_ms':r['active_ms'],
                      'berth_free':berth_ok,'rank_key':list(key(r))} for r in feasible]
        if w is not None and self.mode=='adversarial' and mech!='phase111':
            w.emit(self.actor,'joint_rank_detail',{
                'mechanism':release_aware.describe(),'chosen':best['id'] if best else None,
                'effective_occupancy_ms':effective_occupancy,
                'nominal_occupancy_ms':occupancy,
                'blue_alternatives':['lawful_channel_rebooking','bypass'],
                'rank_detail':rank_detail})
        extra=dict(mechanism=mech,effective_occupancy_ms=effective_occupancy if scoring else None,
                  rank_detail=rank_detail) if mech!='phase111' else {}
        return best,dict(reason=reason,
            quota_budget_forecast_feasible=bool(feasible),feasible_candidate_ids=[r['id'] for r in feasible],adversarial_proxy_ms=scores[best['id']] if best else 0,
            candidate_delay_ms=scores,entrance_observation=observation,
            proxy_scope='Conditional public-route calculation with lawful blue rebooking and alternatives. E uses current arrival; L averages a uniform one-crossing departure grid, not a learned probability or observed task loss.',
            **extra)


def apply_target_mode(card,cs):
    mode=card['target_mode']
    if mode not in MODES:raise ValueError('unknown target mode')
    for actor in ('R1','R2'):
        if mode=='reciprocal':
            if not isinstance(cs[actor],RedRouteController):cs[actor]=RedRouteController(actor,list(cs[actor].commands),autonomous=True)
            cs[actor].autonomous=True;cs[actor].allow_rebook=True
        else:cs[actor]=ModeRouteController(actor,list(cs[actor].commands),mode)
    cs['R5'].cross_team_enabled=mode=='reciprocal'
    return cs
