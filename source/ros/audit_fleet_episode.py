"""Saved configured-fleet evidence audit; not a mission-success certificate."""
import json,math
from pathlib import Path
from gongyu.berths import Berths


def audit(out,scene):
    out=Path(out);card=json.loads((Path(scene)/'scenario.json').read_text());m=json.loads((out/'metrics.json').read_text())
    assert m['mission'] is not None and m['origin_ms'] is not None
    def rows(name):return [json.loads(s) for s in (out/name).read_text().splitlines()]
    es=rows('events.jsonl');feedback=rows('feedback.jsonl');truth=rows('independent_truth.jsonl')
    by_actor={a:[r for r in truth if r['actor']==a] for a in card['fleet']}
    pool=Berths(card);targets={a:pool.position(a,s['node']) for a,s in card['fleet'].items()}
    windows=[];occupied=None;holds=[];entered=None
    assert any(e['kind']=='physical_all_ready' and set(e['payload']['actors'])==set(card['fleet']) for e in es)
    for e in es:
        a,k,p,t=e['actor'],e['kind'],e['payload'],e['t_ms']
        if k=='physical_move_requested':targets[a]=p['waypoints'][-1]
        elif k=='channel_enter':assert occupied is None;occupied=a;entered=t
        elif k=='channel_cleared':assert occupied==a;holds.append(dict(actor=a,exclusive_hold_ms=t-entered));occupied=None
        elif k=='physical_completion_confirmed':
            duration=1. if p['kind']=='move' else card['service_ms']/1000;absolute=(m['origin_ms']+t)/1000
            selected=[r for r in by_actor[a] if absolute-duration<=r['t_s']<=absolute];assert len(selected)>=20
            target=targets[a];xy=max(math.hypot(r['xyz'][0]-target[0],r['xyz'][1]-target[1]) for r in selected)
            speeds=[math.dist(x['xyz'],y['xyz'])/(y['t_s']-x['t_s']) for x,y in zip(selected,selected[1:]) if y['t_s']>x['t_s']]
            air=card['fleet'][a]['mode']=='air';height=max(abs(r['xyz'][2]-target[2]) for r in selected) if air else None
            valid=xy<=(.3 if air else .25) and max(speeds)<=.1 and (not air or height<=.2)
            windows.append(dict(actor=a,kind=p['kind'],t_ms=t,xy_error_m=xy,height_error_m=height,max_speed_m_s=max(speeds),within_independent_limits=valid))
    counts={a:sum(r['actor']==a for r in feedback) for a in card['fleet']}
    assert all(counts.values())
    result=dict(status='CHECKED_DEVELOPMENT_WINDOW',episode_status=m['status'],ended=m['ended'],feedback_counts=counts,
        physical_move_requests={a:sum(e['kind']=='physical_move_requested' and e['actor']==a for e in es) for a in card['fleet']},
        independent_windows=windows,windows_outside_limits=sum(not w['within_independent_limits'] for w in windows),
        exclusive_holds=holds,channel_still_reserved_by=occupied,
        tasks=m['mission']['tasks'],constraint_violations=m['mission']['constraint_violations'],
        scope='No completion or policy-gain claim; unfinished tasks and unfinished occupancy retained')
    (out/'independent_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='independent_windows'},indent=2))


if __name__=='__main__':
    import sys
    audit(sys.argv[1],sys.argv[2])
