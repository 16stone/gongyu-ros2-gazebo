"""Declared eight-entity development geometry; no measured G2 timing claims."""
import json,math
from pathlib import Path
from freeze_physical_m2 import physical_m2_card
from gongyu.berths import physical_card


def g2_card(red3_return_ms=86000,relay_enabled=True,six_entity_reference=False,relay_selection='hard'):
    card=physical_m2_card();card.update(id=f'G2_r3return{red3_return_ms}_relay{int(relay_enabled)}_six{int(six_entity_reference)}'
        +(f'_{relay_selection}' if relay_selection!='hard' else ''),version='G2-development-v2')
    card['geometry']['infrastructure']['red_station']=[18,-8,.3]
    patrols={}
    for actor,start,site,relay,points,deadline in (
        ('R3','N0','PN','RN',[(8,-3),(9,-3),(12,-5)],red3_return_ms),
        ('R4','S0','PS','RS',[(8,-13),(9,-13),(12,-11)],130000)):
        for node,xy in zip((start,site,relay),points):card['nodes'][node]=list(xy);card['berth_capacity'][node]=1
        for a,b,length,duration in ((start,site,1,12000),(site,relay,math.sqrt(13),26000)):
            card['edges'].append([a,b,length,'ground']);card['travel_time_ms'][a+'>'+b]=duration;card['travel_time_ms'][b+'>'+a]=duration
        prefix='red'+actor[-1]
        cfg=dict(start=start,site=site,relay=relay,inspection_task=prefix+'_inspect',report_task=prefix+'_report',return_task=prefix+'_return')
        if not six_entity_reference:
            patrols[actor]=cfg;card['fleet'][actor]=dict(mode='ground',node=start,role='inspect_and_relay',payload_interface=False)
            card['tasks'] += [dict(id=cfg['inspection_task'],team='R',kind='inspection',deadline_ms=60000,actor=actor,region=site,mode='ground'),
                dict(id=cfg['report_task'],team='R',kind='report_delivery',deadline_ms=70000,actor=actor,region=site,mode='ground'),
                dict(id=cfg['return_task'],team='R',kind='inspection',deadline_ms=deadline,actor=actor,region=start,mode='ground')]
    card['g2']=dict(manual_inspection_reports=True,relay_enabled=relay_enabled and not six_entity_reference,patrols=patrols,status_max_age_ms=6000,
                   reports_from={p['inspection_task']:p['report_task'] for p in patrols.values()})
    if relay_selection!='hard':card['g2']['relay_selection']=relay_selection
    card['g2_basis']='Development estimates only:1m ground12s and sqrt(13)m ground26s including turning/settling. R3/R4 inspect, transmit their own report and return; only real received offers can substitute for R5 carrying its report toK_R. Red station18,-8 is the same in all G2 references. Different task denominators prohibit an entity-count-only success-rate claim.'
    return physical_card(card)


if __name__=='__main__':
    import sys
    out=Path(sys.argv[1]);out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('x') as f:json.dump(g2_card(),f,indent=2)
