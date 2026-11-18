"""Paired service-on/off M2 development conditions, all five blue policies."""
import argparse
import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path

from freeze_m2 import m2_card
from gongyu.mission import report_valid
from gongyu.model import Report
from gongyu.run import simulate,write_result


def active_work(events,card):
    active={a:0 for a in card['fleet']}
    for e in events:
        if e.actor not in active:
            continue
        if e.kind=='move_started':
            active[e.actor]+=e.payload['duration_ms']
        elif e.kind in ('load_started','unload_started','observe_started','inspect_started'):
            active[e.actor]+=card['service_ms']
    return active


def run(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);rows=[]
    conditions=[('normal',{}),('short_return',{'return_deadline_ms':34000}),
                ('long_report',{'tau_ms':20000}),('delayed_offer',{'offer_delay_ms':4000})]
    cases=[(label,m2_card(service=enabled,**parameters),policy)
           for label,parameters in conditions for enabled in (False,True)
           for policy in ('P0','P1','P2','P3','P2_equal')]
    for label,card,policy in cases:
        name=card['id']+'_'+policy;started=datetime.now(timezone.utc).isoformat()
        result=simulate(card,policy,name);dest=out/name
        assert not result.world.violations
        loads=[e for e in result.events if e.kind=='load_started']
        assert len(loads)==len({e.task_id for e in loads})
        for e in loads:
            assert report_valid(Report(**e.payload['report']),card['cargo'][e.task_id],e.t_ms)
        commits=[e for e in result.events if e.kind=='slot_exchange_committed']
        assert len(commits)<=1
        states={actor:next((e.payload['state'] for e in reversed(result.events)
                           if e.actor==actor and e.kind=='contract_state'),'IDLE') for actor in ('B1','R1')}
        work=active_work(result.events,card)
        write_result(result,card,policy,dest,started)
        manifest=json.loads((dest/'manifest.json').read_text())
        manifest.update(m2_scope='six physical entities represented by graph execution; no ROS/Gazebo mission run',
            checkpoint_prehistory=False,condition=label,local_contract_states=states,
            referee_only_message_delay_overrides=card.get('message_delay_overrides',{}),
            runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        (dest/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        (dest/'active_work.json').write_text(json.dumps(work,indent=2)+'\n')
        rows.append({'run':name,'condition':label,'policy':policy,'service_enabled':card['m2']['service_enabled'],
            'completed':result.world.completed,'contract_states':states,'slot_commits':len(commits),
            'active_ms':work,'blue_active_ms':sum(v for a,v in work.items() if a.startswith('B')),
            'red_active_ms':sum(v for a,v in work.items() if a.startswith('R')),
            'team_on_time':{team:v['on_time'] for team,v in result.metrics['teams'].items()},
            'load_sources':{e.task_id:e.payload['report']['source_id'] for e in loads}})
    (out/'comparison.json').write_text(json.dumps(rows,indent=2)+'\n')
    print(json.dumps(rows,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
