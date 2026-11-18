"""M2 development profile, frozen after graph exploration and before physical trials."""
import copy,json
from pathlib import Path
from freeze_m2 import m2_card
from freeze_physical import m1_card
from gongyu.berths import physical_card


def physical_m2_card():
    card=physical_card(m2_card(return_deadline_ms=180000));timing=m1_card()
    for key in ('end_ms','travel_time_ms','protocol_margin_ms','departure_clearance_ms'):card[key]=copy.deepcopy(timing[key])
    card['travel_time_ms'].update({'K_R>H_R':12000,'H_R>K_R':12000})
    card.update(id='physical_M2_development_v1_tau6000',version='physical-M2-development-v1',red_release_ms=[210000,0])
    card['m2'].update(blue_future_ms=160000,red_future_ms=210000,red_radio_window_end_ms=140000)
    deadlines=dict(blue1=350000,blue2=350000,blue_inspect=40000,red1=250000,red2=100000,red_inspect=10000,red_patrol=60000,red_return=180000)
    for task in card['tasks']:task['deadline_ms']=deadlines[task['id']]
    card['physical_timing_basis']={**timing['physical_timing_basis'],
        'M2_development':'Phase21 graph exploration exposed insufficient second-report support; phase22 combines external first report with existing own-team support, without altering tau, capabilities or communication.',
        'M2_unmeasured':'K_R-H_R borrows paired4m air12s estimate. No physical M2 travel measurements or outcome guarantee.',
        'M2_task_basis':'R2 independently starts0. Two future directional48s slots160/210s separated by2s gap. Red1 channel+exit+service74s gives284s from own late slot or234s from early slot; own deadline250s lies between. R5 completes outward patrol, independently holds radio window to140s and returns by180s (estimated166s). Blue350s and all hard report rules retained.',
        'M2_scope':'Development card, not an untuned holdout; parameters informed by prior M1 physical timing and phase21 graph exploration. Strong autonomous cancellation/rebooking counterbaseline must be retained.'}
    return card


if __name__=='__main__':
    import sys
    out=Path(sys.argv[1]);out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('x') as f:json.dump(physical_m2_card(),f,indent=2)
