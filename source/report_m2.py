"""Independent saved-event M2 resource, receipt and actual-work audit."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from gongyu.geometry import Geometry
from gongyu.mission import report_valid
from gongyu.model import Report
from gongyu.replay import render


def report(batch,visuals=True):
    batch=Path(batch);rows=json.loads((batch/'comparison.json').read_text())
    counts=dict(runs=len(rows),loads=0,observations=0,radio_endpoints=0,channel_entries=0,
        bilateral_slot_exchanges=0,actual_blue_acceptances=0,actual_red_receipts=0,
        closed_action_checks=0,quote_timing_matches=0,implemented_violations=0)
    for row in rows:
        run=batch/row['run'];card=json.loads((run/'scenario.json').read_text())
        es=[json.loads(x) for x in (run/'events.jsonl').read_text().splitlines()]
        trajectory={(r['actor'],int(r['t_ms'])):r for r in csv.DictReader((run/'trajectory.csv').open())}
        geometry=Geometry(card['geometry'])
        def pose(actor,t):
            if actor in card['geometry']['infrastructure']:
                return card['geometry']['infrastructure'][actor]
            r=trajectory[actor,t]
            return tuple(float(r[k]) for k in ('x','y','z')) if r['node'] else None
        books={};confirmations={};quotes={};committed=set();received=set();receipt_messages={}
        held={'R1':'red1','R2':'red2'};loaded=set();occupied=None;cleared=-card['channel_gap_ms']
        started={};active={a:0 for a in card['fleet']}
        for e in es:
            actor,t,p,kind=e['actor'],e['t_ms'],e['payload'],e['kind']
            if kind=='move_started':
                assert actor not in started;started[actor]=('move',t,p['duration_ms'])
            elif kind in ('load_started','unload_started','observe_started','inspect_started'):
                assert actor not in started;started[actor]=(kind.removesuffix('_started'),t,card['service_ms'])
            elif kind in ('arrived','load_completed','unload_completed','observe_completed','inspect_completed'):
                service,begin,duration=started.pop(actor)
                assert service==('move' if kind=='arrived' else kind.removesuffix('_completed'))
                assert t-begin==duration
                active[actor]+=t-begin;counts['closed_action_checks']+=1
            if kind=='reservation_granted':
                books[p['slot_id']]=dict(p)
            elif kind=='message_arrived':
                assert t-p['sent_at']==p['transmission_delay_ms']
                for at in (p['sent_at'],t):
                    assert geometry.radio(pose(p['sender'],at),pose(actor,at))
                    counts['radio_endpoints']+=1
                payload=p['payload']
                if payload.get('subject_id') and payload.get('source_id'):
                    received.add((actor,payload['source_id'],payload['sampled_at']))
                if payload.get('kind')=='m2_offer':
                    quotes[payload['contract_id']]=payload['quote']
                if actor=='entrance' and payload.get('kind')=='m2_confirm':
                    q=payload['quote'];cid=q['contract_id'];quotes[cid]=q
                    if cid not in committed:
                        assert t<=q['accept_by_ms']
                        saved,parties=confirmations.setdefault(cid,(q,set()))
                        assert saved==q and p['sender'] in q['parties']
                        parties.add(p['sender'])
                if payload.get('kind')=='m2_fulfilled':
                    receipt_messages[e['contract_id'],t]=payload
            elif kind=='slot_exchange_committed':
                cid=e['contract_id'];q=quotes[cid]
                assert cid not in committed and occupied is None
                assert confirmations[cid][1]==set(q['parties'])
                for slot,owner in zip(q['slots'],q['parties']):
                    assert books[slot]['actor']==owner and not books[slot]['used'] and t<books[slot]['start']
                for slot in q['slots']:
                    books[slot]['actor']=p['owners'][slot]
                committed.add(cid);counts['bilateral_slot_exchanges']+=1
            elif kind=='channel_enter':
                assert occupied is None and t>=cleared+card['channel_gap_ms']
                book=next(r for r in books.values() if r['actor']==actor and not r['used'] and r.get('cancelled_at') is None
                          and r['direction']==[p['from'],p['to']] and r['start']<=t<=r['start']+card['reservation_grace_ms'])
                book['used']=True;occupied=actor;counts['channel_entries']+=1
            elif kind=='reservation_expired':
                books[p['slot_id']]['used']=True
            elif kind=='reservation_cancelled':
                books[p['slot_id']]=dict(p)
            elif kind=='channel_cleared':
                assert occupied==actor;occupied=None;cleared=t
            elif kind=='observation_completed':
                r=p['report'];assert geometry.can_observe(pose(actor,t),card['fleet'][actor]['mode'])
                received.add((actor,r['source_id'],r['sampled_at']));counts['observations']+=1
            elif kind=='load_started':
                r=Report(**p['report'])
                assert e['task_id'] not in loaded and actor not in held
                assert report_valid(r,card['cargo'][e['task_id']],t)
                assert (actor,r.source_id,r.sampled_at) in received
                loaded.add(e['task_id']);held[actor]=e['task_id'];counts['loads']+=1
            elif kind=='delivery':
                assert held.pop(actor)==e['task_id']
            elif kind=='contract_state' and p['state']=='FULFILLED':
                cid=e['contract_id'];q=quotes[cid];assert cid in committed
                if actor=='B1':
                    assert ('B1','R5',p['sampled_at']) in received
                    assert p['received_at']==t and 0<=t-p['sampled_at']<=q['maximum_age_ms']
                    assert t<=q['report_by_ms'];counts['actual_blue_acceptances']+=1
                    assert q['report_sample_ms']==p['sampled_at'] and q['report_received_ms']==t
                    counts['quote_timing_matches']+=2
                elif actor=='R1':
                    receipt=receipt_messages[cid,t]
                    assert t<=q['fulfillment_ack_by_ms']
                    assert receipt['received_at']==p['actual_receiver_time']
                    assert 0<=receipt['received_at']-receipt['sampled_at']<=q['maximum_age_ms']
                    counts['actual_red_receipts']+=1
        assert not started
        assert active==row['active_ms']==json.loads((run/'active_work.json').read_text())
        metrics=json.loads((run/'metrics.json').read_text());assert not metrics['constraint_violations']
        assert row['completed']['red_return']<=next(t['deadline_ms'] for t in card['tasks'] if t['id']=='red_return')
        for cid in committed:
            q=quotes[cid]
            assert row['completed']['red1']==q['red_delivery_ms']
            assert row['completed']['red_return']==q['provider_finish_ms']
            counts['quote_timing_matches']+=2
        for e in es:
            if e['kind']=='contract_decision' and e['actor']=='B1':
                assert e['payload']['distinct_evaluated']<=64 and e['payload']['elapsed_ms']<=100
    counts['limits']=['Single contract, honest local status and quote model; not arbitrary markets',
        'Quote timing checked only for committed default trades; rejected conditional forecasts are not actual results',
        'Six graph entities; no collision, physical control or calibrated sensing/RF proof']
    (batch/'audit.json').write_text(json.dumps(counts,indent=2)+'\n')
    if visuals:
        plot(batch,rows)
    chosen=[r for r in rows if r['policy']=='P0' and r['service_enabled']]
    for row in chosen:
        render(batch/row['run'])
    print(json.dumps(counts,indent=2))


def plot(batch,rows):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    pair={r['service_enabled']:r for r in rows if r['condition']=='normal' and r['policy']=='P0'}
    fig,axes=plt.subplots(1,2,figsize=(12,4.7),constrained_layout=True)
    for on,dx,color in ((False,-.18,'#9ea9af'),(True,.18,'#39788e')):
        row=pair[on]
        values=[row['completed'][task]/1000 for task in ('blue1','blue2','red1','red_return')]
        bars=axes[0].bar([i+dx for i in range(4)],values,.34,color=color,label='Service on' if on else 'Service off')
        axes[0].bar_label(bars,padding=3,fmt='%g')
        bars=axes[1].bar([i+dx for i in range(2)],[row['blue_active_ms']/1000,row['red_active_ms']/1000],.34,color=color)
        axes[1].bar_label(bars,padding=3,fmt='%g')
    axes[0].set(xticks=range(4),xticklabels=['Blue cargo1','Blue cargo2','Red cargo1','Red return'],ylim=(0,100),ylabel='Actual completion (s)',title='Same full-prefix P0 condition')
    axes[0].legend();axes[1].set(xticks=range(2),xticklabels=['Blue team','Red team'],ylim=(0,180),ylabel='Actual active execution (s)',title='Full-round work; waiting excluded')
    for ax in axes:
        ax.grid(axis='y',alpha=.15)
    fig.suptitle('M2 slot-for-observation exchange | six graph entities, seed 0\nRed gains an on-time delivery while doing 2s more active work; active work is not energy',fontsize=11)
    for ext in ('png','svg'):
        fig.savefig(batch/('m2_pair_comparison.'+ext),dpi=180)
    plt.close(fig)
    chosen=[r for r in rows if r['policy']=='P0' and r['service_enabled']]
    fig,axes=plt.subplots(4,1,figsize=(12,9),constrained_layout=True)
    actors=['B1','R1','R5'];colors={'move_started':'#628ba3','load_started':'#8caf92','unload_started':'#8caf92','observe_started':'#d9a15d','inspect_started':'#a89abc'}
    for ax,row in zip(axes,chosen):
        card=json.loads((batch/row['run']/'scenario.json').read_text())
        es=[json.loads(x) for x in (batch/row['run']/'events.jsonl').read_text().splitlines()]
        for e in es:
            if e['actor'] in actors and e['kind'] in colors:
                duration=e['payload'].get('duration_ms',card['service_ms'])
                ax.broken_barh([(e['t_ms']/1000,duration/1000)],(actors.index(e['actor'])-.22,.44),facecolors=colors[e['kind']])
            if e['kind']=='contract_state' and e['actor'] in actors and e['payload']['state'] in ('FULFILLED','REJECTED','EXPIRED'):
                ax.scatter(e['t_ms']/1000,actors.index(e['actor']),marker='*',color='black',s=60,zorder=3)
            if e['kind']=='slot_exchange_committed':
                ax.axvline(e['t_ms']/1000,color='#367b57',ls=':',label='Actual resource commit')
        ax.set(yticks=range(3),yticklabels=actors,xlim=(0,95),ylim=(2.6,-.6),
               title=row['condition']+' | local states '+str(row['contract_states']))
        ax.grid(axis='x',alpha=.15)
    axes[-1].set_xlabel('Actual graph simulation time (s); stars = local terminal contract state, not task completion')
    fig.suptitle('M2 actual actions: profitable trade, provider refusal, blue refusal and late offer\nMotion and own patrols continue on rejected/expired contracts',fontsize=11)
    for ext in ('png','svg'):
        fig.savefig(batch/('m2_contract_timeline.'+ext),dpi=180)
    plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('batch');report(p.parse_args().batch)
