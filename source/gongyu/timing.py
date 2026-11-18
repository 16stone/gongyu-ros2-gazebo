"""Public travel estimates; physical completion still requires actual feedback."""


def edge_times(public):
    times={}
    for a,b,length,mode in public['edges']:
        duration=round(length/public[mode+'_speed']*1000)
        times[a,b]=times[b,a]=duration
    for key,value in public.get('travel_time_ms',{}).items():
        pair=tuple(key.split('>'))
        if pair not in times or type(value) is not int or value<=0:
            raise ValueError('invalid public travel estimate: '+str(key))
        times[pair]=value
    return times


def travel_ms(public,source,target):
    return edge_times(public)[source,target]


def contact_windows(public):
    period=public['reconnect_period_ms'];end=public['end_ms']
    if not public.get('physical_contact_hold_ms'):
        return [(4000,6000)]+[(r+4000,r+6000) for r in range(period,end,period)]
    times=edge_times(public);hold=public['physical_contact_hold_ms']
    arrival=times['F','K'];departure=max(6000,arrival+hold)
    if arrival>=end:return []
    windows=[(arrival,min(departure,end))]
    cursor=departure+times['K','F']+public['service_ms']
    for release in range(period,end,period):
        arrival=max(cursor,release)+times['F','K']
        if arrival>=end:break
        departure=max(release+6000,arrival+hold)
        windows.append((arrival,min(departure,end)))
        cursor=departure+times['K','F']
    return windows
