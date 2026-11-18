"""Saved-event audit and plots; prediction deviations remain visible."""
import argparse
import csv
import json
from pathlib import Path

from gongyu.geometry import Geometry
from gongyu.mission import report_valid
from gongyu.model import Report
from gongyu.replay import render


def report(batch):
    batch=Path(batch);rows=json.loads((batch/'comparison.json').read_text())
    counts=dict(runs=len(rows),loads=0,channel_entries=0,observations=0,radio_endpoints=0,
                release_completions=0,predictions_matched=0,prediction_deviations=[],unpredicted=[])
    for row in rows:
        run=batch/row['run'];card=json.loads((run/'scenario.json').read_text())
        events=[json.loads(x) for x in (run/'events.jsonl').read_text().splitlines()]
        decisions=[json.loads(x) for x in (run/'decisions.jsonl').read_text().splitlines()]
        trajectory={(r['actor'],int(r['t_ms'])):r for r in csv.DictReader((run/'trajectory.csv').open())}
        g=Geometry(card['geometry'])
        def pose(actor,t):
            if actor in card['geometry']['infrastructure']:
                return card['geometry']['infrastructure'][actor]
            r=trajectory[actor,t]
            return tuple(float(r[k]) for k in ('x','y','z')) if r['node'] else None
        loaded=set();held={a:c for a,c in (('R1','red1'),('R2','red2')) if c not in card.get('initial_completed',{})}
        delivered={};occupied=None;clear=-card['channel_gap_ms']
        requested={};acknowledged={};released={}
        for e in events:
            actor,t,p=e['actor'],e['t_ms'],e['payload'];kind=e['kind']
            if kind=='load_started':
                assert e['task_id'] not in loaded|set(card.get('initial_completed',{}))
                assert actor not in held
                r=Report(**p['report']);assert report_valid(r,card['cargo'][e['task_id']],t)
                loaded.add(e['task_id']);held[actor]=e['task_id'];counts['loads']+=1
            elif kind=='delivery':
                assert held.pop(actor)==e['task_id'];delivered[e['task_id']]=t
            elif kind=='channel_enter':
                assert occupied is None and t>=clear+card['channel_gap_ms']
                occupied=actor;counts['channel_entries']+=1
            elif kind=='channel_cleared':
                assert occupied==actor;occupied=None;clear=t
            elif kind=='observation_completed':
                assert g.can_observe(pose(actor,t),card['fleet'][actor]['mode'])
                counts['observations']+=1
            elif kind=='message_arrived':
                assert t-p['sent_at']==card['message_delay_ms']
                for at in (p['sent_at'],t):
                    assert g.radio(pose(p['sender'],at),pose(actor,at))
                    assert not row['outage_ms'] or not row['outage_ms'][0]<=at<row['outage_ms'][1]
                    counts['radio_endpoints']+=1
            elif kind=='commitment_released':
                assert actor not in held
                assert p['node'] is not None
                released[actor,p['proposal_id']]=t
            elif kind=='release_requested':
                requested.setdefault(p['proposal_id'],set()).add(p['peer'])
            elif kind=='release_acknowledged':
                pid=p['proposal_id'];peer=p['peer']
                assert (peer,pid) in released and released[peer,pid]<t
                acknowledged.setdefault(pid,set()).add(peer)
            elif kind=='release_complete':
                assert requested[p['proposal_id']]<=acknowledged[p['proposal_id']]
                counts['release_completions']+=1
        assert not json.loads((run/'metrics.json').read_text())['constraint_violations']
        for d in decisions:
            assert len({c['id'] for c in d['candidates']})<=64 and d['elapsed_ms']<=100
            assert 'poses' not in d['input']
        applied=[d for d in decisions if d.get('applied')]
        d=applied[-1] if applied else decisions[0]
        chosen=next(c for c in d['candidates'] if c['id']==d['chosen'])
        for task,t in zip(('blue1','blue2'),chosen.get('deliveries_ms',[])):
            if task in card.get('initial_completed',{}):
                continue
            actual=delivered.get(task)
            if t is None:
                counts['unpredicted'].append({'run':row['run'],'task':task,'actual_ms':actual})
            elif t==actual:
                counts['predictions_matched']+=1
            else:
                counts['prediction_deviations'].append({'run':row['run'],'task':task,'decision_ms':d['t_ms'],
                                                       'predicted_ms':t,'actual_ms':actual})
    counts['limits']=['Graph only; no calibrated physical collision or RF result',
                     'Final applied predictions compared; deviations retained, not erased',
                     'Current two deliveries at action boundaries, not arbitrary fleet task allocation']
    (batch/'audit.json').write_text(json.dumps(counts,indent=2)+'\n')
    plot(batch,rows)
    for name in ('T_G_M1_t6000_r0_p12000_P0_outage35000_37000',
                 'T_G_M1_t6000_r0_p12000_P3_outage38000_40000','T_T_held_blue2_P0'):
        render(batch/name)
    print(json.dumps(counts,indent=2))


def plot(batch,rows):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    policies=['P0','P1','P2','P3','P2_equal']
    fig,axes=plt.subplots(1,3,figsize=(13,4.6),constrained_layout=True)
    for ax,outage,title in zip(axes,(None,[35000,37000],[38000,40000]),('No injected outage','First report delayed','Air service interrupted')):
        subset=[r for r in rows if not r['held_prefix'] and 'G_M1' in r['run'] and r['outage_ms']==outage]
        values=[next(r for r in subset if r['policy']==p)['completed']['blue2']/1000 for p in policies]
        bars=ax.bar(policies,values,color=['#52768c' if t<=90 else '#c17755' for t in values])
        ax.bar_label(bars,padding=3,fmt='%g');ax.axhline(90,color='#923e32',ls='--')
        ax.set(title=title,ylabel='Actual blue2 delivery (s)',ylim=(0,115))
        ax.tick_params(axis='x',labelrotation=20);ax.grid(axis='y',alpha=.15)
    fig.suptitle('Two-delivery action-boundary repair | full M1 prefixes, graph backend\nAll five policies use the same information and candidate budget; deadline = 90s',fontsize=11)
    for ext in ('png','svg'):
        fig.savefig(batch/('rolling_comparison.'+ext),dpi=180)
    plt.close(fig)
    run=batch/'T_G_M1_t6000_r0_p12000_P3_outage38000_40000'
    events=[json.loads(x) for x in (run/'events.jsonl').read_text().splitlines()]
    fig,ax=plt.subplots(figsize=(12,4.1),constrained_layout=True)
    ax.axvspan(38,40,color='#c17755',alpha=.22,label='Unknown outage')
    stages=[('release_requested',3,'Release request'),('commitment_released',2.5,'Peer exit'),
            ('release_complete',2,'ACKs received'),('reconfiguration_committed',1.5,'New commit'),
            ('load_started',1,'Valid load'),('delivery',.5,'Delivery')]
    for kind,y,label in stages:
        selected=[e for e in events if e['kind']==kind and e['t_ms']>=40000]
        grouped={}
        for e in selected:
            grouped.setdefault(e['t_ms'],[]).append(e['actor'])
        ax.scatter([t/1000 for t in grouped],[y]*len(grouped),s=35,color='#276c9c')
        if kind=='release_requested' and selected:
            first,last=selected[0]['t_ms']/1000,selected[-1]['t_ms']/1000
            ax.annotate(f'{len(selected)} requests: {first:g} to {last:g}s',((first+last)/2,y),
                        xytext=(0,10),ha='center',textcoords='offset points',fontsize=8)
        else:
            for i,(t,actors) in enumerate(grouped.items()):
                ax.annotate('/'.join(actors)+f' {t/1000:g}s',(t/1000,y),
                            xytext=(3,-17 if kind=='commitment_released' and i%2 else 8),textcoords='offset points',fontsize=8)
    ax.set(xlim=(37,94),ylim=(.2,3.4),yticks=[s[1] for s in stages],yticklabels=[s[2] for s in stages],xlabel='Simulation time (s)',
           title='Release, new handshake, actual report and delivery are separate events')
    ax.axvline(90,color='#923e32',ls='--',label='Deadline 90s');ax.grid(axis='x',alpha=.15);ax.legend(loc='upper right')
    for ext in ('png','svg'):
        fig.savefig(batch/('release_recovery.'+ext),dpi=180)
    plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('batch');report(p.parse_args().batch)
