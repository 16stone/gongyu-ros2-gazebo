"""Local contract decisions and a bilateral, idempotent resource exchange."""
from copy import deepcopy


def utility(completed_ms,deadline_ms,active_ms):
    return (int(completed_ms<=deadline_ms),-max(0,completed_ms-deadline_ms),-active_ms,-completed_ms)


def team_utility(completions,deadlines,active_ms):
    return (sum(t<=d for t,d in zip(completions,deadlines)),
        -sum(max(0,t-d) for t,d in zip(completions,deadlines)),-active_ms,-sum(completions))


class SlotExchange:
    def __init__(self,owners):
        self.owners=dict(owners)
        self.pending={}
        self.committed={}
        self.commits=0

    def confirm(self,sender,quote,now):
        cid=quote['contract_id'];parties=quote['parties'];slots=quote['slots']
        if len(parties)!=2 or len(set(parties))!=2 or sender not in parties or len(set(slots))!=2:
            raise ValueError('exchange requires two distinct authorized owners and slots')
        if cid in self.committed:
            if quote!=self.committed[cid]:
                raise ValueError('committed contract cannot be changed')
            return True
        for expired in [k for k,(q,_) in self.pending.items() if now>q['accept_by_ms']]:
            del self.pending[expired]
        if now>quote['accept_by_ms']:
            return False
        if [self.owners.get(s) for s in slots]!=parties:
            raise ValueError('offered slots do not belong to the stated parties')
        if self.pending and cid not in self.pending:
            raise ValueError('only one unfinished exchange allowed')
        saved,confirmed=self.pending.setdefault(cid,(deepcopy(quote),set()))
        if saved!=quote:
            raise ValueError('both owners must confirm the same quote')
        confirmed.add(sender)
        if confirmed==set(parties):
            self.owners[slots[0]],self.owners[slots[1]]=parties[1],parties[0]
            self.committed[cid]=saved
            del self.pending[cid]
            self.commits+=1
            return True
        return False


class ContractPeer:
    """One local unresolved contract; outputs are sends, never peer state changes."""
    def __init__(self,actor,air_status=None):
        self.actor=actor;self.state='IDLE';self.quote=None;self.seen=set()
        self.air_status=air_status
        self.candidates=[]

    def request(self):
        self.state='REQUESTED'
        return [('R1',{'kind':'request','contract_id':'C1_exchange',
            'subject_id':'device','report_by_ms':9000,'minimum_quality':1.,'maximum_age_ms':20000,
            'slots':['early','late'],'parties':['B1','R1']})]

    def step(self,view):
        out=[];now=view.now_ms
        for message in view.inbox:
            if message.message_id in self.seen:
                continue
            self.seen.add(message.message_id)
            p=message.payload
            if not isinstance(p,dict) or p.get('contract_id')!='C1_exchange':
                continue
            kind=p.get('kind')
            if self.actor=='R1' and kind=='request' and message.sender=='B1' and self.state=='IDLE':
                self.state='REQUESTED'
                status=self.air_status
                if status:
                    deadlines=[view.own_tasks[0]['deadline_ms'],status['deadline_ms']]
                    self.candidates=[{'id':'independent','score':team_utility([38000,12000],deadlines,22000)},
                        {'id':'exchange','score':team_utility([30000,15000],deadlines,24000)}]
                # C1 supplies a valid pre-checkpoint teammate status; M2 must obtain it over its network.
                if (not status or not 0<=now-status['sampled_at']<=status['valid_for_ms']
                    or status['own_finish_with_service_ms']>status['deadline_ms']
                    or self.candidates[1]['score']<=self.candidates[0]['score']):
                    self.state='REJECTED'
                    out.append(('B1',{'kind':'reject','contract_id':p['contract_id'],
                        'reason':'own mandatory air inspection cannot be guaranteed'}))
                    continue
                self.quote={**p,'accept_by_ms':8000,'report_sample_ms':8000,
                    'red_delivery_ms':30000,'air_finish_ms':15000,
                    'fulfillment_ack_by_ms':10000,
                    'private_status_source':'valid_precheckpoint_teammate_status'}
                self.state='OFFERED'
                out.append(('B1',{'kind':'offer','contract_id':p['contract_id'],'quote':self.quote}))
            elif self.actor=='B1' and kind=='offer' and message.sender=='R1' and self.state=='REQUESTED':
                q=p['quote'];self.quote=q
                if (q.get('subject_id')!='device' or q.get('minimum_quality',0)<1
                    or q.get('maximum_age_ms',20001)>20000 or q.get('report_by_ms',9001)>9000
                    or q.get('slots')!=['early','late'] or q.get('parties')!=['B1','R1']):
                    self.state='REJECTED'
                    out.append(('R1',{'kind':'reject','contract_id':p['contract_id'],'reason':'quote weakens requested terms'}))
                    continue
                self.candidates=[{'id':'independent','completed_ms':30000,'active_ms':28000},
                    {'id':'unassisted_release','completed_ms':38000,'active_ms':28000},
                    {'id':'exchange','completed_ms':38000,'active_ms':14000}]
                for c in self.candidates:
                    c['score']=utility(c['completed_ms'],view.own_tasks[0]['deadline_ms'],c['active_ms'])
                best=max(self.candidates,key=lambda c:c['score'])
                if now>q['accept_by_ms'] or best['id']!='exchange':
                    self.state='REJECTED'
                    out.append(('R1',{'kind':'reject','contract_id':p['contract_id'],'reason':'no local utility improvement'}))
                else:
                    self.state='ACCEPTED'
                    payload={'kind':'accept','contract_id':p['contract_id'],'quote':q}
                    out.extend([('R1',payload),('entrance',payload)])
            elif self.actor=='R1' and kind=='accept' and message.sender=='B1' and self.state=='OFFERED':
                if p['quote']!=self.quote or now>self.quote['accept_by_ms']:
                    self.state='EXPIRED'
                else:
                    self.state='ACCEPTED'
                    out.append(('entrance',{'kind':'confirm','contract_id':p['contract_id'],'quote':self.quote}))
            elif kind=='commit' and message.sender=='entrance' and self.state=='ACCEPTED':
                if p['quote']!=self.quote:
                    raise ValueError('commit does not match the accepted quote')
                self.state='ACTIVE'
                if self.actor=='R1':
                    out.append(('R5',{'kind':'service_task','contract_id':p['contract_id'],'quote':self.quote}))
            elif kind=='fulfilled' and message.sender=='B1' and self.actor=='R1' and self.state=='ACTIVE':
                self.state='FULFILLED'
            elif kind=='reject' and message.sender in ('B1','R1') and self.state in ('REQUESTED','OFFERED','ACCEPTED'):
                self.state='REJECTED'
        if self.quote and now>self.quote['accept_by_ms'] and self.state in ('REQUESTED','OFFERED','ACCEPTED'):
            self.state='EXPIRED'
        receipt_deadline=None
        if self.quote:
            receipt_deadline=self.quote['fulfillment_ack_by_ms' if self.actor=='R1' else 'report_by_ms']
        if receipt_deadline is not None and now>receipt_deadline and self.state=='ACTIVE':
            self.state='FAILED'
        return out
