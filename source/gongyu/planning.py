"""Finite, transparent forecasts from delivered knowledge, never referee state."""
from itertools import product
from dataclasses import replace
from time import perf_counter

from .model import Decision, Diagnosis, Report
from .mission import report_valid
from .geometry import ground_observation
from .timing import edge_times,contact_windows


def with_shared_plan(view):
    """A pre-agreed patrol predicts a contact opportunity, not a true future pose."""
    plan = view.public_map.get('shared_blue_plan')
    if not plan:
        return view
    statuses = dict(view.teammate_status)
    current = statuses.get('B3')
    delay = view.public_map['message_delay_ms']
    if current and current.get('available_until',0)>=view.now_ms+delay:
        return view
    windows = contact_windows(view.public_map)
    for start,end in windows:
        if (current and current.get('node')=='K' and current.get('observed_at') is not None
            and start<=current.get('available_until',0)):
            continue  # A lapsed delivered stay cannot be extended by an overlapping nominal cycle.
        send = max(view.now_ms,start)
        if send+delay<=end:
            statuses['B3'] = {'node':'K','observed_at':None,'available_until':end,
                               'predicted_contact_at':send,'source':'unconfirmed_shared_plan',
                               'inspection_done':send>=plan['air_inspection_expected_ms'],
                               'inspection_deadline_ms':plan['air_inspection_deadline_ms']}
            break
    return replace(view,teammate_status=statuses)


def diagnose(view,sampling_ms):
    reports=[r for r in view.reports if r.subject_id=='device']
    if not reports:
        return Diagnosis('unknown','No device report has been received')
    r = max(reports,key=lambda r:r.sampled_at)
    margin = r.valid_for_ms-(sampling_ms-r.sampled_at)
    if sampling_ms < r.sampled_at:
        return Diagnosis('unknown','Report timestamp is in the future')
    return Diagnosis('feasible' if report_valid(r,'device',sampling_ms) else 'violated',
                     'Current report freshness at predicted sampling',margin)


def candidate_rank(row):
    return (row.get('legal',True),row.get('forecast_comparable',True),row['score'])


def search_candidates(rows,policy,budget=64,evaluate=None,wall_ms=100):
    """P2 follows strict one-block improvements. Every actual forecast consumes budget."""
    start = perf_counter()
    evaluated,visits = {},[]
    def visit(row):
        cached = row['id'] in evaluated
        if not cached:
            if len(evaluated)>=budget or (perf_counter()-start)*1000>=wall_ms:
                return None
            evaluated[row['id']] = evaluate(row) if evaluate else row
        r = evaluated[row['id']]
        visits.append({**r,'cached':cached})
        return r
    best = visit(rows[0])
    if best is None:
        raise ValueError('Budget must allow the safe current candidate')
    def better(a,b):
        return candidate_rank(a)>candidate_rank(b) or (candidate_rank(a)==candidate_rank(b) and a['id']<b['id'])
    if policy in ('P0','P1','P3','P4'):
        allowed = [r for r in rows if (policy in ('P3','P4') or (r['z'][1]==0 and (policy=='P1' or r['z'][0]==0)))]
        for row in allowed:
            r = visit(row)
            if r is not None and better(r,best):
                best = r
    elif policy in ('P2','P2_equal'):
        starts=[rows[0]]
        if policy=='P2_equal':
            starts+=next(([r] for r in rows if r['z']==(0,1,0)),[])
        global_best=best
        for initial in starts:
            current=visit(initial)
            if current is None:
                continue
            moved={current['id']}
            while True:
                next_row=current
                for row in rows:
                    if row['id'] in moved or sum(a!=b for a,b in zip(row['z'],current['z'])) != 1:
                        continue
                    r=visit(row)
                    if r is not None and (candidate_rank(r)>candidate_rank(next_row) or
                        (policy=='P2_equal' and candidate_rank(r)==candidate_rank(next_row) and next_row is current)):
                        next_row=r
                if better(next_row,global_best):
                    global_best=next_row
                if next_row['id']==current['id']:
                    break
                current=next_row
                moved.add(current['id'])
        best=global_best
    else:
        raise ValueError('Unknown policy')
    return best,visits


def forecast(view,candidate):
    from .remaining import forecast_remaining
    remaining=forecast_remaining(view,candidate)
    if remaining is not None:
        return remaining
    from .rolling import forecast_rolling
    rolling=forecast_rolling(view,candidate,forecast_initial)
    return rolling if rolling is not None else forecast_initial(view,candidate)


def forecast_initial(view,candidate):
    c = dict(candidate)
    m = view.public_map
    t,d,s = view.now_ms,m['message_delay_ms'],m['service_ms']
    tau = m['tau_ms']
    edges = edge_times(m)
    gap = m['channel_gap_ms']
    slots = [dict(x) for x in view.reservations if x.get('cancelled_at') is None]
    def cross(at,who,direction):
        channel_dt=edges[tuple(direction)]
        own=next((r for r in slots if r.get('slot_id') and r['actor']==who and not r.get('used')
                  and r.get('direction')==direction and at<=r['start']+2000),None)
        if own:
            own['used']=True
            return max(at,own['start'])+channel_dt
        for r in sorted(slots,key=lambda x:x['start']):
            if at+channel_dt+gap<=r['start']:
                break
            if at<r['end']+gap:
                at=r['end']+gap
        slots.append({'start':at,'end':at+channel_dt})
        return at+channel_dt
    def trip(at,reverse=False,who='B1'):
        if c['route']=='bypass':
            return at+edges['D','L'] if reverse else at+edges['L','D']
        a,b=('D','W') if reverse else ('L','E')
        after = cross(at+edges[a,b],who,['W','E'] if reverse else ['E','W'])
        return after+edges['E','L'] if reverse else after+edges['W','D']
    b2,b3 = view.teammate_status.get('B2'),view.teammate_status.get('B3')
    legal,reason = True,'locally forecast executable'
    deliveries = [None,None]
    migration,air_finish = 0,None
    reports=[r for r in view.reports if r.subject_id=='device' and r.quality>=1]
    known = max(reports,key=lambda r:r.sampled_at) if reports else None
    first_is_held=view.inventory=='blue1'
    fresh = first_is_held or report_valid(known,'device',t)
    def info_ready(at,mode):
        if mode=='self':
            route=ground_observation(m,'L','L')
            if route is None:
                return None,0,'self-carried report expires on the return route'
            return at+route['duration_ms'],route['movement_ms'],''
        if mode=='refresh':
            if not b2 or b2['node']!='J':
                return None,0,'observer position is unknown'
            route=ground_observation(m,'J','J',True)
            if route is None:
                return None,0,'radio report expires before receipt'
            return at+2*d+route['duration_ms'],route['movement_ms'],''
        if mode=='carry':
            if not b2 or b2['node']!='J':
                return None,0,'carrier position is unknown'
            route=ground_observation(m,'J','L',True)
            if route is None:
                return None,0,'carried report expires before same-node transfer'
            return at+2*d+route['duration_ms'],route['movement_ms']+edges['L','J'],''
        return None,0,'waiting for an unpromised future report; availability unknown'
    if c['information']=='wait':
        waiting_safe = c['support']=='fixed' and c['assignment']=='single'
        c.update(legal=waiting_safe,reason='safe waiting; future service availability unknown',deliveries_ms=deliveries,
                 migration_ms=0,handoff_gap_ms=0,score=(0,0,0) if waiting_safe else (-1,0,0),air_inspection_ms=None)
        if m.get('online_replanning'):
            c['forecast_comparable']=False
        return c
    if c['assignment']=='split' and (not b2 or b2['node']!='J' or b2.get('available_until',0)<t+d):
        legal,reason=False,'No valid delivered transport availability'
    air_report = None
    commit_at = t+3*d
    if c['support']=='air' and b3:
        commit_at = max(commit_at,b3.get('predicted_contact_at',t)+3*d)
    b2_ready = commit_at+edges['J','L']
    if c['support']=='air':
        if not b3 or b3['node']!='K' or b3.get('available_until',0)<b3.get('predicted_contact_at',t)+d:
            legal,reason=False,'No valid delivered support availability'
        else:
            h_ready = commit_at+edges['K','H']
            ready = max(h_ready,b2_ready+d) if c['assignment']=='split' else h_ready
            air_report = ready+s+d
            air_finish = air_report+edges['H','K']+edges['K','F']+s
            migration += edges['K','H']+edges['H','K']
            if not b3['inspection_done'] and air_finish>b3['inspection_deadline_ms']:
                legal,reason=False,'Would violate the air vehicle inspection commitment'
    first = t-s if first_is_held else t
    b2_report=Report(**b2['report']) if b2 and b2.get('report') else None
    b2_sample=b2_report.sampled_at if b2_report and b2_report.subject_id=='device' and b2_report.quality>=1 else None
    needs_b1_observer=False
    if legal and c['assignment']=='split' and c['support']=='fixed':
        cached=report_valid(b2_report,'device',b2_ready)
        if not fresh and c['information']=='refresh':
            route=ground_observation(m,'J','J',True)
            if route is None:
                legal,reason=False,'No observable route with a fresh radio report'
            else:
                b2_sample=commit_at+route['sample_offset_ms']
                first=commit_at+route['duration_ms']+d
                b2_ready=first+edges['J','L']
                migration+=route['movement_ms']
        elif (not cached and c['information'] in ('self','carry')) or (not fresh and c['information']=='carry'):
            route=ground_observation(m,'J','L',not fresh and c['information']=='carry')
            if route is None:
                legal,reason=False,'No fresh B2 self-observation route'
            else:
                b2_sample=commit_at+route['sample_offset_ms']
                b2_ready=commit_at+route['duration_ms']
                migration+=route['movement_ms']-edges['J','L']
                if not fresh and c['information']=='carry':
                    first=b2_ready+d
                    b2_ready+=d
    if not fresh:
        if air_report is not None:
            first = air_report
        elif c['assignment']=='split' and c['information'] in ('refresh','carry'):
            pass
        else:
            first,cost,why = info_ready(commit_at if c['assignment']=='split' else t,c['information'])
            migration += cost
            if first is None:
                legal,reason=False,why
    route_dt = edges['L','D'] if c['route']=='bypass' else edges['L','E']+edges['E','W']+edges['W','D']
    return_dt = edges['D','L'] if c['route']=='bypass' else edges['D','W']+edges['W','E']+edges['E','L']
    depart_first = max(first+s,commit_at) if first is not None and (c['assignment']=='split' or c['support']=='air') else first+s if first is not None else None
    if legal and c['assignment']=='single':
        deliveries[0] = trip(depart_first)+s
        back = trip(deliveries[0],True)
        migration += 2*route_dt+return_dt
        if known and 0<=back-known.sampled_at<=known.valid_for_ms:
            second = back
        else:
            second,cost,why = info_ready(back,c['information'])
            migration += cost
            if second is None:
                legal,reason=False,why
        if second is not None:
            deliveries[1] = trip(second+s)+s
    elif legal:
        own_sample = b2_sample
        validity=b2_report.valid_for_ms if b2_report and own_sample==b2_report.sampled_at else tau
        if own_sample is not None and 0<=b2_ready-own_sample<=validity:
            second = b2_ready
        elif air_report is not None:
            second = air_report
        elif c['information'] in ('self','carry'):
            legal,reason=False,'B2 cannot self-carry a fresh report to L'
            second=None
        else:
            # B1 completes cargo1, then performs a real ground observation for B2.
            deliveries[0]=trip(depart_first)+s
            at_l = trip(deliveries[0],True)
            observation=ground_observation(m,'L','J',True)
            second=at_l+observation['duration_ms']+d if observation else None
            needs_b1_observer=True
            migration += return_dt+(observation['movement_ms'] if observation else 0)
            if observation is None:
                legal,reason=False,'B1 observation cannot reach B2 before expiry'
        if legal:
            if deliveries[0] is None:
                previous_departure=None
                for idx,at in sorted(((0,depart_first),(1,second+s)),key=lambda x:(x[1],x[0])):
                    if previous_departure is not None:at=max(at,previous_departure+m.get('departure_clearance_ms',0))
                    deliveries[idx]=trip(at,who='B1' if idx==0 else 'B2')+s
                    previous_departure=at
            else:
                deliveries[1]=trip(second+s,who='B2')+s
        migration += 2*route_dt+edges['J','L']
    deadlines = [x['deadline_ms'] for x in view.own_tasks if x['id'] in ('blue1','blue2')]
    n = sum(at is not None and at<=due for at,due in zip(deliveries,deadlines))
    handoff = max(0,(air_report or t)-b2_ready) if c['assignment']=='split' else 0
    c.update(legal=legal,reason=reason,deliveries_ms=deliveries,migration_ms=migration,
             handoff_gap_ms=handoff,air_inspection_ms=air_finish,
             sampling_ms=[None if first_is_held else first,second] if legal else [],needs_b1_observer=needs_b1_observer,
             score=(n,-migration,-handoff) if legal else (-1,-migration,-handoff))
    return c


def candidate_rows():
    rows=[]
    for assignment,support,route,information in product(('single','split'),('fixed','air'),
                                                      ('channel','bypass'),('refresh','self','carry','wait')):
        z = (int(assignment=='split'),int(support=='air'),
             ('channel','bypass').index(route)*4+('refresh','self','carry','wait').index(information))
        rows.append(dict(id=''.join(map(str,z)),z=z,assignment=assignment,support=support,
                         route=route,information=information))
    return rows


def propose(view,policy_id,budget=64):
    start = perf_counter()
    view = with_shared_plan(view)
    rows=candidate_rows()
    best,visits=search_candidates(rows,policy_id,budget,lambda r:forecast(view,r),
                                 wall_ms=max(1,100-(perf_counter()-start)*1000))
    if policy_id=='P4':
        from .learning import ACTIVE, context_of
        if ACTIVE is None:
            raise ValueError('P4 needs a learner attached between episodes; see 验证/学习型决策对照.py')
        chosen=ACTIVE.choose(context_of(view),[r['id'] for r in visits if r.get('legal',True)])
        best=next(r for r in visits if r['id']==chosen)
    return Decision(best['id'],visits,(perf_counter()-start)*1000)
