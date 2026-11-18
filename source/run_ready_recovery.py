"""Paired READY-loss experiment; the only treatment is same-ID retry interval."""
import argparse
import json
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace

from gongyu.policies import controllers
from gongyu.run import write_result
from gongyu.world import World,load_card


def run(out):
    out=Path(out)
    out.mkdir(parents=True,exist_ok=False)
    rows=[]
    for retry in (0,2000):
        card=load_card('scenarios/C0.json');card['ready_retry_ms']=retry
        name=f'C0_ready_retry{retry}'
        w=World(card,name);cs=controllers(card,'P3')
        for actor,release in zip(('R1','R2'),card['red_release_ms']):
            w.reserve(actor,release)
        link=w.network.link
        start=datetime.now(timezone.utc).isoformat()
        w.emit('referee','run_started',{'backend':'graph','policy':'P3'})
        for now in range(0,card['end_ms']+1,card['step_ms']):
            w.network.link=lambda a,b: link(a,b) and not (now==13000 and {a,b}=={'H','L'})
            w.advance(now)
            if now==13000:
                w.emit('referee','fault_injected',{'nodes':['H','L'],'type':'temporary_radio_edge_loss'})
            for actor in sorted(cs):
                cs[actor].step(w)
        w.emit('referee','run_finished',w.metrics())
        assert not w.violations
        assert w.completed['blue_inspect']<=30000
        assert (w.completed.get('blue2')==34000) if retry else ('blue2' not in w.completed)
        result=SimpleNamespace(events=w.events,metrics=w.metrics(),trajectories=w.trajectories,
            decisions=w.decisions,diagnostics=w.diagnostics)
        dest=out/name
        write_result(result,card,'P3',dest,start)
        manifest=json.loads((dest/'manifest.json').read_text())
        manifest['fault_injection']={'type':'temporary_radio_edge_loss','nodes':['H','L'],
            't_ms':13000,'separate_from_frozen_matrix':True}
        (dest/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        rows.append({'run':name,'retry_ms':retry,'completed':w.completed,
            'retries':sum(e.kind=='message_retry' for e in w.events)})
    (out/'comparison.json').write_text(json.dumps(rows,indent=2)+'\n')
    print(json.dumps(rows,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
