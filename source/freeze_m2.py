"""Six-entity M2 design conditions; outcomes are computed by local policies."""
import copy
import json
from pathlib import Path

from gongyu.world import load_card


def m2_card(return_deadline_ms=37000,tau_ms=6000,offer_delay_ms=None,service=True):
    root=Path(__file__).resolve().parent
    card=copy.deepcopy(load_card(root/'scenarios/G_M1_t6000_r0_p12000.json'))
    card.update(id=f'M2_return{return_deadline_ms}_tau{tau_ms}_offer{offer_delay_ms or 1000}_service{int(service)}',
        version='1.0-six-entity-M2',tau_ms=tau_ms,online_replanning=True,red_release_ms=[32000,0],
        m2={'enabled':True,'service_enabled':service,'blue_future_ms':24000,'red_future_ms':32000,
            'status_max_age_ms':6000,'red_radio_window_end_ms':30000})
    card['nodes']['H_R']=[6,-8];card['edges'].append(['K_R','H_R',4,'air'])
    card['berth_capacity']['H_R']=1
    for t in card['tasks']:
        if t['id']=='red1':
            t['deadline_ms']=34000
    card['tasks'] += [
        {'id':'red_patrol','team':'R','kind':'report_delivery','deadline_ms':18000,
         'actor':'R5','region':'H_R','mode':'air'},
        {'id':'red_return','team':'R','kind':'inspection','deadline_ms':return_deadline_ms,
         'actor':'R5','region':'F_R','mode':'air'}]
    if offer_delay_ms is not None:
        card['message_delay_overrides']={'m2_offer':offer_delay_ms}
    card['note']='Full six-entity graph prefix. Future directional bookings are real resource grants, not given prior occupancy. R5 performs outward patrol and return tasks. Contract preferences use affected local tasks; no fixed success/refusal outcome. Per-offer delay, when present, is a referee-only disturbance.'
    return card


if __name__=='__main__':
    cards=[m2_card(),m2_card(service=False),m2_card(return_deadline_ms=34000),
           m2_card(tau_ms=20000),m2_card(offer_delay_ms=4000)]
    for card in cards:
        dest=Path(__file__).resolve().parent/'scenarios'/f'{card["id"]}.json'
        if dest.exists():
            raise FileExistsError(dest)
        dest.write_text(json.dumps(card,indent=2)+'\n')
