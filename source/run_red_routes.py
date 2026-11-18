"""Matched local counterfactual: fixed, bypass choice, and acknowledged rebooking."""
import argparse
import json
from datetime import datetime,timezone
from pathlib import Path

from freeze_m2 import m2_card
from gongyu.run import simulate,write_result
from run_m2 import active_work
from report_m2 import report


def run(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);rows=[]
    for mode in ('fixed','route_only','autonomous'):
        for enabled in (False,True):
            for policy in ('P0','P3'):
                card=m2_card(service=enabled);card['m2']['red_route_policy']=mode
                card['id']=f'M2_{mode}_service{int(enabled)}_{policy}'
                started=datetime.now(timezone.utc).isoformat()
                result=simulate(card,policy,card['id']);dest=out/card['id']
                assert not result.world.violations
                assert all(t['id'] in result.world.completed for t in card['tasks'])
                work=active_work(result.events,card)
                write_result(result,card,policy,dest,started)
                (dest/'active_work.json').write_text(json.dumps(work,indent=2)+'\n')
                states={a:next((e.payload['state'] for e in reversed(result.events)
                    if e.actor==a and e.kind in ('contract_state','market_unavailable')),'IDLE') for a in ('B1','R1')}
                rows.append(dict(run=card['id'],condition=mode,policy=policy,service_enabled=enabled,
                    completed=result.world.completed,contract_states=states,active_ms=work,
                    blue_active_ms=sum(v for a,v in work.items() if a.startswith('B')),
                    red_active_ms=sum(v for a,v in work.items() if a.startswith('R'))))
    (out/'comparison.json').write_text(json.dumps(rows,indent=2)+'\n')
    report(out,visuals=False)
    for r in rows:
        print(r['run'],r['completed']['red1'],r['completed']['blue1'],r['completed']['blue2'],r['contract_states'])


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
