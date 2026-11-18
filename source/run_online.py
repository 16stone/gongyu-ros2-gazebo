"""Small remaining-task evidence set; checkpoint cases are not full mission runs."""
import argparse
import json
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace

from gongyu.policies import controllers
from gongyu.run import simulate,write_result
from gongyu.world import World,load_card


def fault_run(card,policy,name,outage):
    w=World(card,name);cs=controllers(card,policy)
    if card['red_channel_enabled']:
        for actor,release in zip(('R1','R2'),card['red_release_ms']):
            w.reserve(actor,release)
    link=w.network.link
    w.emit('referee','run_started',{'backend':'graph','policy':policy,'radio_outage_ms':outage})
    for now in range(0,card['end_ms']+1,card['step_ms']):
        w.network.link=lambda a,b:link(a,b) and not outage[0]<=now<outage[1]
        w.advance(now)
        if now in outage:
            w.emit('referee','fault_boundary',{'radio_outage_ms':outage,'active':now==outage[0]})
        for actor in sorted(cs):
            cs[actor].step(w)
    w.emit('referee','run_finished',w.metrics())
    return SimpleNamespace(world=w,events=w.events,metrics=w.metrics(),trajectories=w.trajectories,
                           decisions=w.decisions,diagnostics=w.diagnostics)


def audit(result,card):
    w=result.world
    assert not w.violations,w.violations
    loads=[e for e in w.events if e.kind=='load_started']
    assert len({e.task_id for e in loads})==len(loads),'duplicate loading'
    for e in loads:
        assert e.task_id not in card.get('initial_completed',{})
        r=e.payload['report']
        assert r['subject_id']=='device' and r['quality']>=1
        assert 0<=e.t_ms-r['sampled_at']<=r['valid_for_ms']
    for d in w.decisions:
        assert len({c['id'] for c in d['candidates']})<=64 and d['elapsed_ms']<=100
        if d.get('mode')=='remaining':
            selected=next(c for c in d['candidates'] if c['id']==d['chosen'])
            for task in d['input']['own_tasks']:
                if task['completed_ms'] is not None:
                    assert task['id'] not in selected.get('remaining_tasks',[])
            if d['input']['inventory'] and selected['legal']:
                assert selected['transport_actor']=='B1'
                assert not any(c[0]=='load' for c in selected['own_commands'])
    applied=[d for d in w.decisions if d.get('mode')=='remaining' and d['applied']]
    if applied:
        last=applied[-1];selected=next(c for c in last['candidates'] if c['id']==last['chosen'])
        if selected['legal'] and selected.get('forecast_comparable',True):
            for task in selected['remaining_tasks']:
                index=('blue1','blue2').index(task)
                assert w.completed.get(task)==selected['deliveries_ms'][index],(task,w.completed,selected)
    return {'loads':len(loads),'remaining_decisions':sum(d.get('mode')=='remaining' for d in w.decisions),
            'applied_remaining_plans':len(applied),'implemented_violations':len(w.violations),
            'max_search_ms':max(d['elapsed_ms'] for d in w.decisions),
            'completed':w.completed,'new_blue2_on_time':result.metrics['tasks']['blue2']['on_time']}


def run(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    cases=[]
    for base in ('R_remaining_cached','R_remaining_air','G_M1_t6000_r0_p12000'):
        card=load_card('scenarios/'+base+'.json');card['online_replanning']=True
        for policy in ('P0','P1','P2','P3','P2_equal'):
            cases.append((dict(card),policy,None))
    for outage in ((72000,72100),(71000,73000)):
        card=load_card('scenarios/G_M1_t6000_r0_p12000.json');card['online_replanning']=True
        cases.append((card,'P0',outage))
    cases.append((load_card('scenarios/R_remaining_air.json'),'P0',(0,5000)))
    rows=[]
    for card,policy,outage in cases:
        name='O_'+card['id']+'_'+policy+(f'_outage{outage[0]}_{outage[1]}' if outage else '')
        card['id']=name
        started=datetime.now(timezone.utc).isoformat()
        result=fault_run(card,policy,name,outage) if outage else simulate(card,policy,name)
        checks=audit(result,card)
        dest=out/name;write_result(result,card,policy,dest,started)
        manifest=json.loads((dest/'manifest.json').read_text())
        manifest['fault_injection']={'radio_outage_ms':outage,'known_to_referee_only':True} if outage else None
        manifest['checkpoint_prehistory']=card.get('initial_completed',{})
        (dest/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        (dest/'audit.json').write_text(json.dumps(checks,indent=2)+'\n')
        rows.append({'run':name,'policy':policy,'checkpoint':bool(card.get('initial_completed')),
                     'outage_ms':outage,**checks})
    (out/'comparison.json').write_text(json.dumps(rows,indent=2)+'\n')
    print(json.dumps(rows,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
