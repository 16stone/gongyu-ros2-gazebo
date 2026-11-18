from collections import deque

from .model import Report


def move(*nodes):
    return [('move',n) for n in nodes]


class Controller:
    """A local finite-state executor. Witness mode explicitly supplies external actions."""
    def __init__(self,actor,commands,witness=False):
        self.actor = actor
        self.commands = deque(commands)
        self.witness = witness
        self.seen,self.confirmations = set(),set()
        self.counter = 0

    def on_message(self,w,m):
        a = self.actor
        if not self.witness and a == 'B2' and isinstance(m.payload,dict) and m.payload.get('kind') == 'refresh':
            self.commands = deque(move('O')+[('observe',None)]+move('J')+[('send_report','B1'),('hold',None)])
        if self.witness and isinstance(m.payload,dict):
            if m.payload.get('kind') in ('transport_proposal','support_request'):
                w.emit(a,'role_confirmed',{'request':m.message_id})
                w.send(a,'B1',{'kind':'confirm'},'confirm_'+a)
            if a == 'B1' and m.payload.get('kind') == 'confirm':
                self.confirmations.add(m.sender)
                required = {'B2','B3'} if w.card['tau_ms'] == 6000 else {'B2'}
                if self.confirmations == required:
                    w.send(a,'B2',{'kind':'commit'},'commit_B2')

    def command(self,w,arg):
        raise ValueError(f'Unsupported custom command: {arg}')

    def before_actions(self,w):
        pass

    def step(self,w):
        a = self.actor
        view = w.view(a)
        for m in view.inbox:
            if m.message_id in self.seen:
                continue
            self.seen.add(m.message_id)
            self.on_message(w,m)
        # Communication may be processed while an actuator is busy.
        if a in w.busy:
            return
        self.before_actions(w)
        while self.commands:
            kind,arg = self.commands[0]
            if kind == 'at':
                if w.now < arg:
                    return
            elif kind == 'move':
                if not w.start_move(a,arg):
                    return
                self.commands.popleft()
                return
            elif kind in ('observe','inspect','load','unload'):
                if kind == 'load' and not w.mission.can_load(a,arg,w.now,view.node):
                    # Delivery receipts travel over the same lossy link the coordinator plans from,
                    # so a crate already parked at D can still look outstanding there. This unit holds
                    # the completion, so the rest of the tour is nothing to do, not an illegal action.
                    if any(t['id']==arg and t['completed_ms'] is not None for t in view.own_tasks):
                        w.emit(a,'stale_plan_pickup_dropped',{'cargo':arg,'node':view.node})
                        self.commands.clear()
                        return
                    raise ValueError(f'invalid load actor={a} cargo={arg} t={w.now} node={view.node} reports={view.reports} inventory={w.mission.inventory} loading={w.mission.loading}')
                if not w.service(a,kind,arg):
                    return
                self.commands.popleft()
                return
            elif kind == 'report':
                reports = [r for r in view.reports if r.subject_id=='device']
                if not reports:
                    return
                r = max(reports,key=lambda r:r.sampled_at)
                if not 0 <= w.now-r.sampled_at <= r.valid_for_ms:
                    w.emit(a,'report_rejected',{'age_ms':w.now-r.sampled_at,'tau_ms':r.valid_for_ms,
                                               'reason':'expired_before_sampling'})
                    self.commands.popleft()
                    self_return = w.edges['O','J'][0]+w.edges['J','L'][0]
                    if self_return <= r.valid_for_ms:
                        recovery = move('J','O')+[('observe',None)]+move('J','L')
                    else:
                        self.counter += 1
                        w.emit(a,'self_collection_infeasible',{'return_ms':self_return,'tau_ms':r.valid_for_ms})
                        w.send(a,'B2',{'kind':'refresh'},f'refresh_{a}_{self.counter}')
                        recovery = [('await_fresh',None)]
                    self.commands.extendleft(reversed(recovery))
                    return
            elif kind == 'await_fresh':
                if not any(r.subject_id=='device' and 0<=w.now-r.sampled_at<=r.valid_for_ms for r in view.reports):
                    return
            elif kind == 'message':
                if not any(isinstance(m.payload,dict) and m.payload.get('kind')==arg for m in view.inbox):
                    return
            elif kind == 'send_report':
                reports = [r for r in view.reports if r.subject_id=='device']
                if not reports:
                    # The unit decided to forward a report it has not received yet:
                    # possible once knowledge arrives over a link instead of through
                    # a shared object. Hold the step and say so, rather than crash.
                    w.emit(a,'send_report_deferred',{'reason':'no device report in local knowledge'})
                    return
                r = max(reports,key=lambda r:r.sampled_at)
                self.counter += 1
                w.send(a,arg,r,f'report_{a}_{self.counter}')
            elif kind == 'send':
                target,payload,mid = arg
                w.send(a,target,payload,mid)
            elif kind == 'hold':
                return
            elif kind == 'role':
                w.emit(a,'role_active',{'role':arg,'node':view.node})
            elif kind == 'custom':
                replacement = self.command(w,arg)
                if replacement is None:
                    return
                self.commands.popleft()
                self.commands.extendleft(reversed(replacement))
                continue
            else:
                raise ValueError(kind)
            self.commands.popleft()


def _controllers(card,policy,legacy=False):
    if not legacy and card.get('g2'):
        from .patrol import g2_controllers
        return g2_controllers(card,policy)
    if not legacy and card.get('m2'):
        from .m2 import m2_controllers
        return m2_controllers(card,policy)
    if not legacy and policy in ('P0','P1','P2','P3','P4','P2_equal'):
        from .adaptive import adaptive_controllers
        return adaptive_controllers(card,policy)
    witness = policy == 'witness'
    if witness and card['id'] not in ('C0','C0_long'):
        raise ValueError('external witness only applies to C0')
    if policy not in ('P0','witness'):
        raise ValueError('P1-P3 not implemented yet; never silently substitute P0')
    common = {
        'R1':[('at',card['red_release_ms'][0])]+move('W','D')+[('unload','red1')],
        'R2':[('at',card['red_release_ms'][1])]+move('W','D')+[('unload','red2')],
        'R5':[('inspect','red_inspect')]+move('K_R')+[('hold',None)],
    }
    if witness:
        common.update({
            'B1':[('at',4000),('send',('B2',{'kind':'transport_proposal'},'propose_B2')),
                  ('send',('B3',{'kind':'support_request'},'request_B3')),('at',5000),('report',None),('load','blue1')]
                  +move('E','W','D')+[('unload','blue1')],
            'B2':move('J')+[('send_report','B1'),('message','commit'),('role','transport')]
                  +move('L')+[('at',13000),('report',None),('load','blue2')]
                  +move('E','W','D')+[('unload','blue2')],
            'B3':move('K')+[('message','support_request'),('at',6000)]+move('H')
                  +[('role','observe'),('observe',None),('send_report','B2'),('at',13000)]
                  +move('K','F')+[('inspect','blue_inspect')]
        })
        if card['tau_ms'] == 20000:
            common['B1'] = [c for c in common['B1'] if not (c[0]=='send' and c[1][0]=='B3')]
            common['B2'] = [c for c in common['B2'] if c != ('at',13000)]
            common['B3'] = move('K')+[('at',6000)]+move('F')+[('inspect','blue_inspect')]
    else:
        start = [] if card['fleet']['B1']['node']=='L' else move('W','E','L')
        common['B1'] = start+[('report',None),('load','blue1')]+move('E','W','D')+[('unload','blue1')]
        common['B1'] += move('W','E','L')+[('report',None),('load','blue2')]+move('E','W','D')+[('unload','blue2')]
        initial_obs = [] if card['id']=='C0' else [('at',6000),('observe',None)]
        common['B2'] = initial_obs+move('J')+[('send_report','B1'),('hold',None)]
        common['B3'] = move('K')+[('at',6000)]+move('F')+[('inspect','blue_inspect')]
        # Repeat the declared reconnect cycle after the first completed inspection.
        period = card['reconnect_period_ms']
        for release in range(period,card['end_ms'],period):
            common['B3'] += [('at',release)]+move('K')+[('at',release+6000)]+move('F')
    if not card['red_channel_enabled']:
        # Paired causal ablation: retain their tasks as unfinished, never remove them from denominator.
        common['R1']=common['R2']=[('hold',None)]
    return {a:Controller(a,c,witness) for a,c in common.items()}


def controllers(card,policy,legacy=False):
    cs=_controllers(card,policy,legacy)
    if card.get('target_mode'):
        from .modes import apply_target_mode
        cs=apply_target_mode(card,cs)
    return cs
