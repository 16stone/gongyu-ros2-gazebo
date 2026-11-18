"""Generate the eight predeclared M1 graph-development conditions before any run."""
import copy
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parent
c0 = json.loads((root/'scenarios/C0.json').read_text())
m1 = copy.deepcopy(c0)
m1.update(id='M1',version='1.1-graph',end_ms=120000,blue_deadline_ms=90000,
          initial_reports={},
          note='B1 starts at D and traverses C before sampling. B2 observes 6-8s then carries report to J. Explicit graph regions only; geometry/visibility and physical validation pending.')
m1['fleet']['B1']['node'] = 'D'
for task in m1['tasks']:
    if task['id'] in ('blue1','blue2'):
        task['deadline_ms'] = 90000
cards = {'M1':m1,'C0_long':{**c0,'id':'C0_long','tau_ms':20000}}
for tau in (6000,20000):
    for delay in (0,4000):
        for period in (12000,20000):
            c = copy.deepcopy(m1)
            c.update(id=f'M1_t{tau}_r{delay}_p{period}',tau_ms=tau,
                     red_release_ms=[delay,8000+delay],reconnect_period_ms=period)
            cards[c['id']] = c
for name,c in cards.items():
    (root/'scenarios'/f'{name}.json').write_text(json.dumps(c,indent=2)+'\n')
manifest = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((root/'scenarios').glob('*.json'))}
(root/'evidence/setup/frozen_cards_v1_1.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest,indent=2))
