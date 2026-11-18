"""Independent saved-clock/truth checks for the scoped R1 integration gate."""
import json,math
from pathlib import Path


def audit(out):
    out=Path(out);m=json.loads((out/'metrics.json').read_text());assert m['status']=='PASS'
    def rows(name):return [json.loads(x) for x in (out/name).read_text().splitlines()]
    es=rows('events.jsonl');feedback=rows('feedback.jsonl');truth=rows('independent_truth.jsonl')
    assert feedback and truth and m['origin_ms'] is not None
    for r in feedback:
        assert 0<=r['odom_absolute_ms']-r['tf_absolute_ms']<=200
        assert r['sampled_ms']==r['tf_absolute_ms']-m['origin_ms']
    moves=[e for e in es if e['kind']=='physical_move_requested'];assert len(moves)==2
    completions=[e for e in es if e['kind']=='physical_completion_confirmed'];assert len(completions)==3
    targets={e['payload']['goal_id']:e['payload']['waypoints'][-1] for e in moves}
    checks=[]
    for e in completions:
        kind=e['payload']['kind'];target=targets[e['payload']['goal_id']] if kind=='move' else moves[-1]['payload']['waypoints'][-1]
        absolute=(m['origin_ms']+e['t_ms'])/1000;duration=1. if kind=='move' else 2.
        selected=[r for r in truth if absolute-duration<=r['t_s']<=absolute]
        assert len(selected)>=20,(kind,len(selected))
        error=max(math.hypot(r['xyz'][0]-target[0],r['xyz'][1]-target[1]) for r in selected)
        speeds=[math.dist(a['xyz'],b['xyz'])/(b['t_s']-a['t_s']) for a,b in zip(selected,selected[1:]) if b['t_s']>a['t_s']]
        assert error<=.25 and max(speeds)<=.1,(kind,error,max(speeds))
        checks.append(dict(kind=kind,t_ms=e['t_ms'],true_window_max_error_m=error,true_window_max_speed_m_s=max(speeds)))
    enter=next(e for e in es if e['kind']=='channel_enter');clear=next(e for e in es if e['kind']=='channel_cleared')
    assert clear['t_ms']>enter['t_ms']
    delivery=next(e for e in es if e['kind']=='delivery' and e['task_id']=='red1')
    result=dict(status='PASS',feedback_timestamp_checks=len(feedback),independent_windows=checks,
        channel_exclusive_hold_ms=clear['t_ms']-enter['t_ms'],delivery_ms=delivery['t_ms'],
        on_time=m['mission']['tasks']['red1']['on_time'],scope='one physical R1 delivery; other five parked; no blue policy benefit claim')
    (out/'independent_audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


if __name__=='__main__':
    import sys
    audit(sys.argv[1])
