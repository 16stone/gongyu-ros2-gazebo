"""Audit saved remaining-task traces and make report figures (not screenshots)."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from gongyu.geometry import Geometry
from gongyu.mission import report_valid
from gongyu.model import Report
from gongyu.replay import render


def report(batch):
    batch=Path(batch);rows=json.loads((batch/'comparison.json').read_text())
    counts=dict(runs=len(rows),load_checks=0,prediction_checks=0,channel_entries=0,
                observation_checks=0,radio_endpoint_checks=0,implemented_violations=0)
    for row in rows:
        run=batch/row['run'];card=json.loads((run/'scenario.json').read_text())
        events=[json.loads(x) for x in (run/'events.jsonl').read_text().splitlines()]
        decisions=[json.loads(x) for x in (run/'decisions.jsonl').read_text().splitlines()]
        trajectory={(r['actor'],int(r['t_ms'])):r for r in csv.DictReader((run/'trajectory.csv').open())}
        geometry=Geometry(card['geometry'])
        def pose(actor,t):
            if actor in card['geometry']['infrastructure']:
                return card['geometry']['infrastructure'][actor]
            r=trajectory[actor,t]
            return tuple(float(r[k]) for k in ('x','y','z')) if r['node'] else None
        delivered={};loaded=set();occupied=None;last_clear=-card['channel_gap_ms']
        for e in events:
            if e['kind']=='load_started':
                r=Report(**e['payload']['report'])
                assert report_valid(r,card['cargo'][e['task_id']],e['t_ms'])
                assert e['payload']['report_age_ms']==e['t_ms']-r.sampled_at
                assert e['task_id'] not in loaded|set(card.get('initial_completed',{}))
                loaded.add(e['task_id']);counts['load_checks']+=1
            elif e['kind']=='delivery':
                assert e['task_id'] not in delivered
                delivered[e['task_id']]=e['t_ms']
            elif e['kind']=='channel_enter':
                assert occupied is None and e['t_ms']>=last_clear+card['channel_gap_ms']
                occupied=e['actor'];counts['channel_entries']+=1
            elif e['kind']=='channel_cleared':
                assert occupied==e['actor']
                occupied=None;last_clear=e['t_ms']
            elif e['kind']=='observation_completed':
                assert geometry.can_observe(pose(e['actor'],e['t_ms']),card['fleet'][e['actor']]['mode'])
                counts['observation_checks']+=1
            elif e['kind']=='message_arrived':
                assert e['payload']['arrived_at']-e['payload']['sent_at']==card['message_delay_ms']
                for t in (e['payload']['sent_at'],e['payload']['arrived_at']):
                    assert geometry.radio(pose(e['payload']['sender'],t),pose(e['actor'],t))
                    outage=row['outage_ms']
                    assert not outage or not outage[0]<=t<outage[1]
                    counts['radio_endpoint_checks']+=1
        assert not json.loads((run/'metrics.json').read_text())['constraint_violations']
        applied=[d for d in decisions if d.get('mode')=='remaining' and d['applied']]
        if applied:
            d=applied[-1];c=next(c for c in d['candidates'] if c['id']==d['chosen'])
            for task in c.get('remaining_tasks',[]):
                assert delivered.get(task)==c['deliveries_ms'][('blue1','blue2').index(task)]
                counts['prediction_checks']+=1
        else:
            d=decisions[0];c=next(c for c in d['candidates'] if c['id']==d['chosen'])
            for task,t in zip(('blue1','blue2'),c['deliveries_ms']):
                assert delivered.get(task)==t
                counts['prediction_checks']+=1
    counts['limits']=['Graph traces only; no physical collision or calibrated radio audit',
                     'Final applied predictions checked, not every discarded candidate',
                     'Checkpoint prehistory is supplied, not newly executed',
                     'One remaining delivery at L/D only; full rolling multi-task planning pending']
    (batch/'audit.json').write_text(json.dumps(counts,indent=2)+'\n')
    plot(batch,rows)
    for name in ('O_R_remaining_cached_P1','O_R_remaining_air_P3',
                 'O_G_M1_t6000_r0_p12000_P0_outage71000_73000'):
        render(batch/name)
    paths=[p for p in batch.rglob('*') if p.is_file() and p.name!='artifact_index.json']
    index={str(p.relative_to(batch)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    (batch/'artifact_index.json').write_text(json.dumps(index,indent=2)+'\n')
    print(json.dumps(counts,indent=2))


def plot(batch,rows):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    policies=['P0','P1','P2','P3','P2_equal']
    fig,axes=plt.subplots(1,3,figsize=(13,4.5),constrained_layout=True)
    for ax,case,deadline in zip(axes,('R_remaining_cached','R_remaining_air','G_M1_t6000_r0_p12000'),(18,25,90)):
        subset=[r for r in rows if r['run'].startswith('O_'+case+'_') and not r['outage_ms']]
        values=[next(r for r in subset if r['policy']==p)['completed']['blue2']/1000 for p in policies]
        bars=ax.bar(policies,values,color=['#52768c' if t<=deadline else '#c17755' for t in values])
        ax.bar_label(bars,padding=3,fmt='%g');ax.axhline(deadline,color='#923e32',ls='--',label='deadline')
        ax.set(title=case,ylabel='Actual blue2 delivery (s)',ylim=(0,max(values+[deadline])+9))
        ax.tick_params(axis='x',labelrotation=20);ax.grid(axis='y',alpha=.15);ax.legend()
    fig.suptitle('Remaining-task evidence | first two cases start from supplied history\nGraph event plots, not Gazebo screenshots; P2_equal uses equal moves and two starts',fontsize=11)
    for ext in ('png','svg'):
        fig.savefig(batch/('remaining_comparison.'+ext),dpi=180)
    plt.close(fig)
    name='O_G_M1_t6000_r0_p12000_P0_outage71000_73000'
    events=[json.loads(x) for x in (batch/name/'events.jsonl').read_text().splitlines()]
    plans=[e for e in events if e['kind']=='remaining_plan_selected']
    fig,ax=plt.subplots(figsize=(10,3.8),constrained_layout=True)
    ax.axvspan(71,73,color='#c17755',alpha=.25,label='Unknown radio outage')
    for e in plans:
        ax.scatter(e['t_ms']/1000,1,color='#276c9c')
        ax.annotate('Replan '+str(e['payload']['revision']),(e['t_ms']/1000,1),xytext=(3,12),textcoords='offset points')
    for kind,y,label,color in (('load_started',.7,'Load','#367e57'),('delivery',.4,'Delivery','#704e97')):
        for e in events:
            if e['kind']==kind and e['task_id']=='blue2':
                ax.scatter(e['t_ms']/1000,y,color=color)
                ax.annotate(f"{label} {e['t_ms']/1000:g}s",(e['t_ms']/1000,y),xytext=(3,9),textcoords='offset points')
    ax.axvline(90,ls='--',color='#923e32',label='Deadline 90s')
    ax.set(xlim=(48,110),ylim=(.2,1.3),yticks=[],xlabel='Simulation time (s)',
           title='Expired delayed report does not cancel retry | blue2 delivered late at 100s')
    ax.grid(axis='x',alpha=.15);ax.legend(loc='lower left')
    for ext in ('png','svg'):
        fig.savefig(batch/('stale_report_recovery.'+ext),dpi=180)
    plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('batch');report(p.parse_args().batch)
