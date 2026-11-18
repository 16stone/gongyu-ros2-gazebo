"""Graph evidence for two-task repair, preserved loads and real release messages."""
import argparse
import json
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace

from freeze_remaining import residual_air_card
from gongyu.policies import controllers
from gongyu.run import simulate,write_result
from gongyu.world import World,load_card
from run_online import fault_run


def held_card(cargo):
    card=residual_air_card();card['id']='T_held_'+cargo
    del card['initial_completed']['blue1']
    card['initial_reports']['B1']=0
    for task in card['tasks']:
        if task['id'] in ('blue1','blue2'):
            task['deadline_ms']=90000
    card['note']='Given report checkpoint; actual load starts at t=0 and finishes at t=2s before two-task repair. No synthetic inventory assignment.'
    return card


def held_run(card,policy,name,cargo):
    w=World(card,name);cs=controllers(card,policy)
    w.emit('referee','run_started',{'backend':'graph','policy':policy,'given_report_checkpoint':True})
    w.service('B1','load',cargo)
    for now in range(0,card['end_ms']+1,card['step_ms']):
        w.advance(now)
        for actor in sorted(cs):
            cs[actor].step(w)
    w.emit('referee','run_finished',w.metrics())
    return SimpleNamespace(world=w,events=w.events,metrics=w.metrics(),trajectories=w.trajectories,
                           decisions=w.decisions,diagnostics=w.diagnostics)


def run(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);cases=[];rows=[]
    for policy in ('P0','P1','P2','P3','P2_equal'):
        for outage in (None,(35000,37000),(38000,40000)):
            card=load_card('scenarios/G_M1_t6000_r0_p12000.json');card['online_replanning']=True
            cases.append((card,policy,outage,None))
    for cargo in ('blue1','blue2'):
        for policy in ('P0','P3'):
            cases.append((held_card(cargo),policy,None,cargo))
    for policy in ('P0','P3'):
        card=held_card('blue1');card['id']='T_staging_D';card['end_ms']=120000
        card['fleet']['B1']['node']='D'
        card['note']='Given report and private-task history checkpoint at D; both blue deliveries remain. Actual relocation and report acquisition must precede loading.'
        cases.append((card,policy,None,None))
    for card,policy,outage,cargo in cases:
        name='T_'+card['id']+'_'+policy+(f'_outage{outage[0]}_{outage[1]}' if outage else '')
        card['id']=name;start=datetime.now(timezone.utc).isoformat()
        result=held_run(card,policy,name,cargo) if cargo else fault_run(card,policy,name,outage) if outage else simulate(card,policy,name)
        assert not result.world.violations
        loads=[e for e in result.events if e.kind=='load_started']
        assert len(loads)==len({e.task_id for e in loads})
        for e in loads:
            report=e.payload['report']
            assert 0<=e.t_ms-report['sampled_at']<=report['valid_for_ms']
        dest=out/name;write_result(result,card,policy,dest,start)
        manifest=json.loads((dest/'manifest.json').read_text())
        manifest['fault_injection']={'radio_outage_ms':outage,'known_to_referee_only':True} if outage else None
        manifest['checkpoint_prehistory']=card.get('initial_completed',{})
        manifest['initial_load_action']=cargo
        manifest['limitations'][2]='Action-boundary repair for the current two deliveries; no moving-actuator preemption or arbitrary fleet task allocation'
        (dest/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        rows.append({'run':name,'policy':policy,'outage_ms':outage,'held_prefix':cargo,
            'completed':result.world.completed,'blue2_on_time':result.metrics['tasks']['blue2']['on_time'],
            'loads':len(loads),'rolling_applied':sum(d.get('mode')=='rolling' and d['applied'] for d in result.decisions),
            'releases':sum(e.kind=='release_complete' for e in result.events),
            'release_requests':sum(e.kind=='release_requested' for e in result.events),
            'protocol_retries':sum(e.kind=='protocol_retry' for e in result.events),
            'max_search_ms':max(d['elapsed_ms'] for d in result.decisions)})
    (out/'comparison.json').write_text(json.dumps(rows,indent=2)+'\n')
    print(json.dumps(rows,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
