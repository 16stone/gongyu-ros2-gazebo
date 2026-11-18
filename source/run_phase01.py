"""Small deterministic calibration batch. Existing outputs are never overwritten."""
import copy
import csv
import json
from datetime import datetime,timezone
from pathlib import Path

from gongyu.run import simulate,write_result
from gongyu.world import load_card, without_red_traffic

root = Path(__file__).resolve().parent
batch = root/'evidence/phase01_v2'
batch.mkdir(exist_ok=False)
cases = [('C0','witness'),('C0_long','witness'),('M1','P0')]
cases += [(p.stem,'P0') for p in sorted((root/'scenarios').glob('M1_t*.json'))]
summary = []
for name,policy in cases:
    path = root/'scenarios'/f'{name}.json'
    card = load_card(path)
    started = datetime.now(timezone.utc).isoformat()
    result = simulate(card,policy,f'{name}_{policy}_s0')
    write_result(result,card,policy,batch/f'{name}_{policy}_s0',started,path)
    row = {'case':name,'policy':policy,'blue1_ms':result.world.completed.get('blue1'),
           'blue2_ms':result.world.completed.get('blue2'),
           'B_on_time':result.metrics['teams']['B']['on_time'],
           'B_tasks':result.metrics['teams']['B']['released'],
           'R_on_time':result.metrics['teams']['R']['on_time'],
           'R_tasks':result.metrics['teams']['R']['released'],
           'constraint_violations':len(result.world.violations)}
    summary.append(row)
    print(json.dumps(row))
card = without_red_traffic(load_card(root/'scenarios/M1.json'))
started = datetime.now(timezone.utc).isoformat()
result = simulate(card,'P0','M1_no_red_channel_P0_s0')
write_result(result,card,'P0',batch/'M1_no_red_channel_P0_s0',started)
with (batch/'summary.csv').open('w',newline='') as f:
    writer = csv.DictWriter(f,list(summary[0]))
    writer.writeheader()
    writer.writerows(summary)
print('Saved paired no-red-channel ablation, with red unfinished tasks retained.')
