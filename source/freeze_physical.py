"""Predeclared M1 physical development profile; historical graph cards stay intact."""
import json
from pathlib import Path
from gongyu.berths import physical_card
from gongyu.world import load_card


def m1_card():
    root=Path(__file__).resolve().parent
    card=physical_card(load_card(root/'scenarios/G_M1_t6000_r0_p12000.json'))
    card.update(id='physical_M1_v3_tau6000',version='physical-timing-v1-berths-v2-egress-v1',end_ms=400000,
                online_replanning=True,protocol_margin_ms=4000,departure_clearance_ms=12000)
    estimates={'L>E':18000,'E>W':48000,'W>D':24000,'O>J':18000,'J>L':18000,
               'L>D':70000,'F>K':12000,'K>H':12000,'F_R>K_R':12000}
    card['travel_time_ms']={}
    for pair,duration in estimates.items():
        a,b=pair.split('>');card['travel_time_ms'][a+'>'+b]=duration;card['travel_time_ms'][b+'>'+a]=duration
    deadlines={'blue1':350000,'blue2':350000,'blue_inspect':40000,'red1':100000,'red2':160000,'red_inspect':10000}
    for task in card['tasks']:task['deadline_ms']=deadlines[task['id']]
    card['physical_timing_basis']={
        'run':'phase17_fleet_v1','source_revision':'3f118bcc421ee72fdf23b31e98c91eb740b5bd3c',
        'observed_completed_ms':{'D>W':13148,'O>J':13792,'E>W':36744,'W>D':10490,
                                  'W>E':41174,'E>L':9050,'J>L':10372,'four_meter_air_max':10806},
        'status':'Conservative design estimates informed by completed transitions; not statistical upper bounds.',
        'geometry_revision':'v2 changes W berths to y+/-.95 and centerline route point to(2,0); timing/deadlines unchanged from v1. Prior measured transitions are reference data, not measurements of this revised geometry.',
        'egress_revision':'v3 holds a ground follower on the same directed edge until fresh predecessor feedback is3m from the follower source berth, or the preceding move actually completes. This moves the predecessor beyond the2.5m peer obstacle-marking influence with allowance; source claim release at.55m alone is insufficient. Graph backend uses public12s as a conservative local-exit estimate, not a physical release timer. phase18_fleet_v2 first L departure cleared.55m after3652ms; roughly another1.65m/.26m/s plus margin motivates12s. Other travel estimates and deadlines unchanged.',
        'unmeasured':'Reverse directions borrow paired estimates; L-D bypass70s is an unvalidated design estimate from12m/.26m/s plus turning/settling allowance.',
        'deadline_basis':'Red1 estimate48+24+2=74s within100s; red2 booking at50 plus74=124s within160s. Blue350s covers approximately166s approach plus next air contact/protocol and70s bypass with margin. Air inspection estimated12+6+12+2=32s within40s.',
        'controls':'Frozen before this physical development run, equal across policies; tau6s, capabilities, speeds, sensing and protection are unchanged. Historical deadlines and failures remain recorded.'}
    return card


if __name__=='__main__':
    import sys
    out=Path(sys.argv[1]);out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('x') as f:json.dump(m1_card(),f,indent=2)
