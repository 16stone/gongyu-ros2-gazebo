"""All eight frozen development conditions; no result-based deletion or retuning."""
import argparse
import csv
import json
from datetime import datetime,timezone
from pathlib import Path

from gongyu.run import simulate,write_result
from gongyu.world import load_card

def run_cases(cases,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    rows=[]
    for case in cases:
        results={}
        for policy in ('P0','P1','P2','P3'):
            card=load_card(case)
            start=datetime.now(timezone.utc).isoformat()
            r=simulate(card,policy,f'{case.stem}_{policy}_s0')
            results[policy]=r
            write_result(r,card,policy,out/f'{case.stem}_{policy}_s0',start,case)
        # Predeclared diagnostic: whenever P3's chosen forecast beats strict P2, check the stronger P2.
        choices={policy:next(c for c in r.decisions[0]['candidates'] if c['id']==r.decisions[0]['chosen'])
                 for policy,r in results.items()}
        if choices['P3']['score']>choices['P2']['score']:
            card=load_card(case);start=datetime.now(timezone.utc).isoformat()
            r=simulate(card,'P2_equal',f'{case.stem}_P2_equal_s0')
            results['P2_equal']=r
            write_result(r,card,'P2_equal',out/f'{case.stem}_P2_equal_s0',start,case)
        for policy,r in results.items():
            decision=r.decisions[0]
            chosen=next(c for c in decision['candidates'] if c['id']==decision['chosen'])
            row={'case':case.stem,'policy':policy,'chosen':chosen['id'],
                 'assignment':chosen['assignment'],'support':chosen['support'],'route':chosen['route'],
                 'information':chosen['information'],'decision_ms':decision['t_ms'],
                 'blue1_predicted_ms':chosen['deliveries_ms'][0],'blue2_predicted_ms':chosen['deliveries_ms'][1],
                 'blue1_actual_ms':r.world.completed.get('blue1'),'blue2_actual_ms':r.world.completed.get('blue2'),
                 'B_on_time':r.metrics['teams']['B']['on_time'],'B_tasks':r.metrics['teams']['B']['released'],
                 'R_on_time':r.metrics['teams']['R']['on_time'],'R_tasks':r.metrics['teams']['R']['released'],
                 'constraint_violations':len(r.world.violations),
                 'search_evaluations':decision['distinct_evaluated'],'search_wall_ms':decision['elapsed_ms']}
            rows.append(row)
            print(json.dumps(row),flush=True)
    with (out/'summary.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,list(rows[0]));writer.writeheader();writer.writerows(rows)
    print('Formal runs:',len(rows),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out');args=p.parse_args()
    root=Path(__file__).resolve().parent
    cases=[root/'scenarios/C0.json',root/'scenarios/C0_long.json']+sorted((root/'scenarios').glob('M1_t*.json'))
    run_cases(cases,args.out)