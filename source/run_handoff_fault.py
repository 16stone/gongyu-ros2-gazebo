"""A separately labelled READY-loss counterexample; never mixed with the frozen matrix."""
import json
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace

from gongyu.policies import controllers
from gongyu.run import write_result
from gongyu.world import World,load_card

card_path=Path('scenarios/C0.json')
card=load_card(card_path)
out=Path('evidence/phase02_fault_ready_loss_v2')
if out.exists():
    raise FileExistsError(out)
start=datetime.now(timezone.utc).isoformat()
w=World(card,out.name)
cs=controllers(card,'P3')
for actor,release in zip(('R1','R2'),card['red_release_ms']):
    w.reserve(actor,release)
base_link=w.network.link
w.emit('referee','run_started',{'backend':'graph','policy':'P3','controlled_fault':'H-L down at 13000ms'})
for now in range(0,card['end_ms']+1,card['step_ms']):
    w.network.link=lambda a,b: base_link(a,b) and not (now==13000 and {a,b}=={'H','L'})
    w.advance(now)
    if now==13000:
        w.emit('referee','fault_injected',{'type':'temporary_radio_edge_loss','nodes':['H','L']})
    for actor in sorted(cs):
        cs[actor].step(w)
w.emit('referee','run_finished',w.metrics())
assert w.completed['blue_inspect']<=30000
assert not w.violations
result=SimpleNamespace(events=w.events,metrics=w.metrics(),trajectories=w.trajectories,decisions=w.decisions)
write_result(result,card,'P3',out,start,card_path)
manifest=json.loads((out/'manifest.json').read_text())
manifest['fault_injection']={'type':'temporary_radio_edge_loss','nodes':['H','L'],'t_ms':13000,
                              'separate_from_frozen_matrix':True}
(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(w.metrics(),indent=2))
