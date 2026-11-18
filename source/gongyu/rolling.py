"""Forecast real staging and preserved inventory before rebuilding two-task plans."""
from dataclasses import replace

from .remaining import forecast_remaining,ground_travel


def forecast_rolling(view,candidate,initial_forecast):
    if not view.public_map.get('online_replanning'):
        return None
    if view.node is None:
        return {**candidate,'legal':False,'reason':'moving; wait for actual action boundary','score':(-1,0,0)}
    c=dict(candidate);t=view.now_ms;s=view.public_map['service_ms']
    if view.inventory:
        cargo=view.inventory
        arrival,commands,cost=ground_travel(view,c['route'],view.node,'D',t)
        finished=arrival+s
        future=replace(view,node='D',now_ms=finished,inventory=None,
            own_tasks=tuple({**task,'completed_ms':finished} if task['id']==cargo else task for task in view.own_tasks))
        c=forecast_remaining(future,c)
        c['staging_commands']=commands+[('unload',cargo)]+c['staging_commands']
        c['preserved_cargo']=cargo
        c['migration_ms']+=cost
        task=next(task for task in view.own_tasks if task['id']==cargo)
        c['score']=(c['score'][0]+int(finished<=task['deadline_ms']),-c['migration_ms'],-c['handoff_gap_ms']) if c['legal'] else c['score']
        return c
    if view.node!='L':
        at_l,staging,cost=ground_travel(view,c['route'],view.node,'L',t)
        c=initial_forecast(replace(view,node='L',now_ms=at_l),c)
        c.update(staging_commands=staging,planning_at_ms=at_l)
        c['migration_ms']+=cost
        if c['legal']:
            c['score']=(c['score'][0],-c['migration_ms'],-c['handoff_gap_ms'])
        return c
    return None
