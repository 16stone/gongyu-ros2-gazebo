"""Own-task ground relays and local choices for delivering R5 inspection reports."""
from dataclasses import asdict
from .adaptive import custom
from .contracts import team_utility
from .geometry import Geometry
from .m2 import Provider,m2_controllers,send
from .policies import Controller,move
from .timing import travel_ms
from . import thresholds


class GroundInspector(Controller):
    def __init__(self,actor,config,enabled,selection='hard'):
        commands=move(config['site'])+[('inspect',config['inspection_task']),custom('patrol_report')]
        commands+=move(config['relay'])+[custom('relay_hold')]+move(config['site'],config['start'])+[('inspect',config['return_task']),('hold',None)]
        super().__init__(actor,commands);self.config=config;self.enabled=enabled;self.last_offer=-2000;self.served=False;self.release_after=0
        self.selection=selection;self.declined_at=None

    def latest_leave(self,view):
        c=self.config;deadline=next(t['deadline_ms'] for t in view.own_tasks if t['id']==c['return_task'])
        return deadline-travel_ms(view.public_map,c['relay'],c['site'])-travel_ms(view.public_map,c['site'],c['start'])-view.public_map['service_ms']

    def ready(self,w,view):
        return (self.enabled and not self.served and self.actor not in w.busy and view.node==self.config['relay']
            and w.now<self.latest_leave(view) and any(t['id']==self.config['report_task'] and t['completed_ms'] is not None for t in view.own_tasks))

    def answers(self,w,view,p):
        """Threshold mode: the request carries the requester's deadline pressure, the unit owns the rule.

        'hard' keeps the shipped behaviour, where every feasible provider answers and the requester
        picks. 'demand' is the same willingness but no advertising, so the traffic difference between
        the two is the protocol and nothing else. 'threshold' asks `gongyu.thresholds` instead, and a
        unit that declines stops waiting at the relay node -- declining is only a saving if it is a
        saving for its own task.
        """
        if self.selection in ('hard','demand'):
            return True
        if thresholds.ACTIVE is None:
            raise ValueError(f'relay_selection={self.selection} needs a threshold ledger attached; see 验证/仿生分工阈值对照.py')
        value=thresholds.stimulus(w.now,p.get('stimulus_deadline_ms'))
        answer=thresholds.ACTIVE.volunteers(self.actor,value)
        if not answer:self.declined_at=w.now
        w.emit(self.actor,'relay_offer_decided',{'selection':self.selection,'answers':answer,
               'stimulus':value,'ledger':thresholds.ACTIVE.log[-1]})
        return answer

    def offer(self,w,view):
        self.counter+=1;self.last_offer=w.now
        w.send(self.actor,'R5',dict(kind='relay_offer',node=view.node,observed_at=w.now,available_until=self.latest_leave(view)),f'{self.actor}_relay_offer_{self.counter}')

    def before_actions(self,w):
        # Advertising is the shipped protocol. A threshold unit answers requests instead, because
        # there is no stimulus for it to weigh before one arrives.
        if self.selection!='hard':return
        view=w.view(self.actor)
        if self.ready(w,view) and w.now-self.last_offer>=2000:self.offer(w,view)

    def on_message(self,w,m):
        p=m.payload
        if not isinstance(p,dict):return
        view=w.view(self.actor)
        if p.get('kind')=='relay_offer_request' and m.sender=='R5':
            if self.ready(w,view) and self.answers(w,view,p):self.offer(w,view)
        elif p.get('kind')=='inspection_report' and m.sender=='R5' and p.get('source_id')=='R5':
            if not self.ready(w,view) or w.now+3*w.network.delay>self.latest_leave(view):
                w.emit(self.actor,'relay_refused',dict(reason='actual relay state or own return budget prevents forwarding'))
                self.counter+=1;w.send(self.actor,'R5',dict(kind='relay_refused',task_id=p.get('task_id')),f'{self.actor}_relay_refused_{self.counter}');return
            self.counter+=1;w.send(self.actor,w.station,dict(p),f'{self.actor}_forward_report_{self.counter}')
            if self.selection!='hard' and thresholds.ACTIVE is not None:
                thresholds.ACTIVE.record_service(self.actor)
        elif p.get('kind')=='task_result' and m.sender==w.station and p.get('final_receiver')=='R5':
            self.counter+=1;w.send(self.actor,'R5',dict(p),f'{self.actor}_forward_receipt_{self.counter}')
            self.served=True;self.release_after=w.now+w.network.delay

    def command(self,w,arg):
        view=w.view(self.actor)
        if arg['kind']=='patrol_report':
            report=next((r for r in view.inspection_reports if r['task_id']==self.config['report_task']),None)
            if report is None:return None
            self.counter+=1;w.send(self.actor,w.station,report,f'{self.actor}_own_report_{self.counter}');return []
        if arg['kind']=='relay_hold':
            # Declining is only a saving if the unit gets its own window back, so a threshold unit
            # that answered 'no' leaves the relay node instead of waiting for a second request.
            if self.declined_at is not None:return []
            own_done=any(t['id']==self.config['report_task'] and t['completed_ms'] is not None for t in view.own_tasks)
            if w.now>=self.latest_leave(view) or own_done and (not self.enabled or self.served and w.now>=self.release_after):return []
            return None
        raise ValueError('unknown patrol command')


class RelayProvider(Provider):
    def __init__(self,commands,policy,relays,radio_end,status_age,selection='hard'):
        super().__init__(commands,policy);self.allowed_relays=tuple(relays);self.radio_end=radio_end;self.status_age=status_age
        self.selection=selection
        self.relay_offers={};self.delivery={};self.unconfirmed_reports=set();self.last_query=-2000

    def on_message(self,w,m):
        p=m.payload
        if not self.cross_team_enabled and isinstance(p,dict) and p.get('kind','').startswith('m2_'):return
        if isinstance(p,dict) and p.get('kind')=='task_result':
            if any(t['id']==p.get('task_id') and t['completed_ms'] is not None for t in w.view('R5').own_tasks):
                self.unconfirmed_reports.discard(p['task_id'])
        if isinstance(p,dict) and p.get('kind')=='relay_offer' and m.sender in self.allowed_relays:
            self.relay_offers[m.sender]=p;return
        if isinstance(p,dict) and p.get('kind')=='relay_refused' and m.sender in self.allowed_relays:
            self.relay_offers.pop(m.sender,None)
            state=self.delivery.get(p.get('task_id'))
            if state and state.get('target')==m.sender:state.pop('target',None)
            return
        if isinstance(p,dict) and p.get('kind')=='m2_service':
            if any(t['id'] in ('red_inspect','red_patrol') and t['completed_ms'] is None for t in w.view('R5').own_tasks):
                self.cid=p['contract_id'];w.emit('R5','service_state',dict(state='REJECTED',reason='own report acknowledgement not received'),contract_id=self.cid)
                send(self,w,'R1','m2_service_failed',reason='own inspection delivery unresolved');return
        super().on_message(w,m)

    def command(self,w,arg):
        view=w.view('R5');tasks={t['id']:t for t in view.own_tasks};m=view.public_map;d=m['message_delay_ms']
        if arg['kind']=='provider_status' and self.unconfirmed_reports:return self.home(view.node)
        if arg['kind']!='deliver_own_report':return super().command(w,arg)
        task_id=arg['task_id'];task=tasks[task_id]
        if task['completed_ms'] is not None:
            self.delivery.pop(task_id,None)
            return move(arg['return_to']) if arg.get('return_to') and view.node!=arg['return_to'] else []
        if w.now>task['deadline_ms']:
            self.unconfirmed_reports.add(task_id);w.emit('R5','inspection_delivery_unconfirmed',dict(task_id=task_id,reason='own actual receipt missing by deadline; station delivery is unknown'));return []
        report=next((r for r in view.inspection_reports if r['task_id']==task_id),None)
        if report is None:return None
        state=self.delivery.setdefault(task_id,dict(last_sent=-2000))
        if 'target' not in state:
            g=m['geometry'];own=(*m['nodes'][view.node],g['heights']['red_air'])
            direct=Geometry(g).radio(own,g['infrastructure'][w.station])
            flight=travel_ms(m,'H_R','K_R');return_ms=flight+travel_ms(m,'K_R','F_R')+m['service_ms']
            return_deadline=tasks['red_return']['deadline_ms'];depart=min(self.radio_end,return_deadline-return_ms)
            choices=[]
            def add(name,report_at,active,ready):
                finish=max(ready,depart)+return_ms
                if report_at<=task['deadline_ms'] and finish<=return_deadline:
                    choices.append(dict(id=name,utility=team_utility([report_at,finish],[task['deadline_ms'],return_deadline],active),report_at=report_at))
            if direct:add('direct',w.now+d,0,w.now+2*d)
            for actor,offer in self.relay_offers.items():
                if 0<=w.now-offer['observed_at']<=self.status_age and offer['available_until']>=w.now+4*d:
                    add(actor,w.now+2*d,0,w.now+4*d)
            if view.node=='H_R':add('self_move',w.now+flight+d,2*flight,w.now+2*flight+2*d)
            known_relay=any(c['id'] in self.allowed_relays for c in choices)
            latest_self=task['deadline_ms']-flight-d
            if not direct and not known_relay and self.allowed_relays and w.now<latest_self:
                if w.now-self.last_query>=2000:
                    self.last_query=w.now
                    for actor in self.allowed_relays:
                        request=dict(kind='relay_offer_request',task_id=task_id)
                        if self.selection!='hard':request['stimulus_deadline_ms']=task['deadline_ms']
                        self.counter+=1;w.send('R5',actor,request,f'R5_relay_query_{self.counter}')
                return None
            if not choices:return None
            chosen=max(sorted(choices,key=lambda c:c['id']),key=lambda c:c['utility'])
            state['chosen']=chosen['id']
            w.emit('R5','inspection_route_selected',dict(task_id=task_id,chosen=chosen['id'],candidates=choices,input=asdict(view)))
            if chosen['id']=='self_move':return move('K_R')+[custom('deliver_own_report',task_id=task_id,return_to='H_R')]
            state['target']=w.station if chosen['id']=='direct' else chosen['id']
        if w.now-state['last_sent']>=2000:
            self.counter+=1;state['last_sent']=w.now
            w.send('R5',state['target'],report,f'R5_own_inspection_{self.counter}')
        return None


def g2_controllers(card,policy):
    cs=m2_controllers(card,policy);cfg=card['g2'];selection=cfg.get('relay_selection','hard')
    for actor,patrol in cfg['patrols'].items():cs[actor]=GroundInspector(actor,patrol,cfg['relay_enabled'],selection)
    commands=[('inspect','red_inspect'),custom('deliver_own_report',task_id='red_inspect')]+move('K_R','H_R')
    commands += [('inspect','red_patrol'),custom('deliver_own_report',task_id='red_patrol'),custom('provider_status')]
    cs['R5']=RelayProvider(commands,policy,tuple(cfg['patrols']) if cfg['relay_enabled'] else (),
                           card['m2']['red_radio_window_end_ms'],cfg['status_max_age_ms'],selection)
    return cs
