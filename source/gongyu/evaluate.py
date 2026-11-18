"""Audit actual phase-two traces and plot a predeclared mechanism comparison."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from .mission import report_valid
from .model import Report
from .geometry import Geometry


def evaluate(batch):
    batch=Path(batch)
    rows=list(csv.DictReader((batch/'summary.csv').open()))
    checks=0;predictions=0;censored=0;edges=0;maximum_wall=0;optical=0;radio=0
    for row in rows:
        run=batch/f'{row["case"]}_{row["policy"]}_s0'
        events=[json.loads(x) for x in (run/'events.jsonl').read_text().splitlines()]
        card=json.loads((run/'scenario.json').read_text())
        metrics=json.loads((run/'metrics.json').read_text())
        geometry=Geometry(card['geometry']) if 'geometry' in card else None
        if geometry:
            trajectory={(r['actor'],int(r['t_ms'])):r for r in csv.DictReader((run/'trajectory.csv').open())}
            def pose_at(actor,t):
                if actor in card['geometry']['infrastructure']:
                    return card['geometry']['infrastructure'][actor]
                r=trajectory[actor,t]
                return tuple(float(r[k]) for k in ('x','y','z')) if r['node'] else None
        assert not metrics['constraint_violations'],run
        deliveries={}
        occupied=None;last_clear=-card['channel_gap_ms']
        for e in events:
            if e['kind']=='load_started':
                r=Report(**e['payload']['report'])
                assert report_valid(r,card['cargo'][e['task_id']],e['t_ms']),e
                assert e['payload']['report_age_ms']==e['t_ms']-r.sampled_at,e
                checks+=1
            elif e['kind']=='delivery':
                assert e['task_id'] not in deliveries,e
                deliveries[e['task_id']]=e['t_ms']
            elif e['kind']=='channel_enter':
                assert occupied is None and e['t_ms']>=last_clear+card['channel_gap_ms'],e
                occupied=e['actor']
            elif e['kind']=='channel_cleared':
                assert occupied==e['actor'],e
                occupied=None;last_clear=e['t_ms']
            elif e['kind']=='message_arrived':
                assert e['payload']['arrived_at']-e['payload']['sent_at']==card['message_delay_ms'],e
                if geometry:
                    for at in (e['payload']['sent_at'],e['payload']['arrived_at']):
                        assert geometry.radio(pose_at(e['payload']['sender'],at),pose_at(e['actor'],at)),e
                        radio+=1
            elif geometry and e['kind']=='observation_completed':
                r=e['payload']['report']
                assert geometry.can_observe(pose_at(e['actor'],e['t_ms']),card['fleet'][e['actor']]['mode']),e
                optical+=1
            elif e['kind']=='service_edge_active':
                assert e['payload']['sampled_at']<=e['t_ms'],e
                edges+=1
        decisions=[json.loads(x) for x in (run/'decisions.jsonl').read_text().splitlines()]
        for d in decisions:
            assert d['distinct_evaluated']<=64,d
            assert d['elapsed_ms']<=100,d
            maximum_wall=max(maximum_wall,d['elapsed_ms'])
            assert 'poses' not in d['input'],d
            assert all(not t['id'].startswith('red') for t in d['input']['own_tasks']),d
            chosen=next(c for c in d['candidates'] if c['id']==d['chosen'])
            for cargo,predicted in zip(('blue1','blue2'),chosen['deliveries_ms']):
                if predicted is None:
                    continue
                if predicted<=card['end_ms']:
                    assert deliveries.get(cargo)==predicted,(run,cargo,predicted,deliveries.get(cargo))
                    predictions+=1
                else:
                    assert cargo not in deliveries,(run,cargo)
                    censored+=1
    result={'runs':len(rows),'load_report_checks':checks,'in_window_prediction_checks':predictions,
            'out_of_window_predictions_censored':censored,'actual_service_edges':edges,
            'geometric_observation_checks':optical,'geometric_radio_endpoint_checks':radio,
            'maximum_search_wall_ms':maximum_wall,'constraint_violations':0,
            'summary_sha256':hashlib.sha256((batch/'summary.csv').read_bytes()).hexdigest(),
            'limits':['Selected waypoint forecasts only; not a proof about every candidate or disturbances',
                      'Geometric checks only when the card supplies geometry; no calibrated sensors or propagation',
                      'No collision, physical backend or statistical generalization audit']}
    (batch/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
    plot(batch,rows)
    print(json.dumps(result,indent=2))


def plot(batch,rows):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    geometric=rows[0]['case'].startswith('G_')
    cases=['G_M1_t6000_r0_p12000','G_M1_visibleL','G_M1_t6000_r4000_p20000'] if geometric else ['M1_t6000_r0_p12000','M1_t20000_r0_p12000','M1_t6000_r4000_p20000']
    policies=['P0','P1','P2','P3','P2_equal']
    fig,axes=plt.subplots(3,1,figsize=(10,8),constrained_layout=True)
    for ax,case in zip(axes,cases):
        selected={r['policy']:r for r in rows if r['case']==case}
        for i,policy in enumerate(policies):
            r=selected.get(policy)
            if not r:
                ax.text(i,8,'not triggered',ha='center',rotation=90,fontsize=8)
                continue
            for dx,key,color in ((-.18,'blue1_actual_ms','#367fa4'),(.18,'blue2_actual_ms','#df9c5d')):
                value=float(r[key])/1000 if r[key] else float('nan')
                ax.bar(i+dx,value,.34,color=color)
                if value==value:
                    ax.text(i+dx,value+1,f'{value:g}',ha='center',fontsize=8)
        ax.axhline(90,color='#a54131',ls='--',lw=1)
        ax.set(xticks=range(len(policies)),xticklabels=policies,ylabel='Actual delivery (s)',ylim=(0,105),title=case)
        ax.grid(axis='y',alpha=.15)
    fig.suptitle('Frozen graph-development conditions | cargo1 (blue), cargo2 (orange)\nP2_equal: equal moves and two starts, checked when strict P2 loses',fontsize=11)
    fig.savefig(batch/'mechanism_comparison.png',dpi=180)
    fig.savefig(batch/'mechanism_comparison.svg')
    plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('batch');args=p.parse_args();evaluate(args.batch)
